"""
La pagina di refertazione e le rotte del referto.

Una pagina sola per il refertatore assegnato, che cambia con lo stato:

- INVIATA: visore degli allegati + dati del caso + decisione (prendi in
  carico / declina), cosi' si decide guardando il materiale;
- PRESA_IN_CARICO: visore + editor del referto (bozza, salvataggio
  automatico ogni 30 s) + firma + «non refertabile»;
- REFERTATA: referto firmato, storico versioni, rettifica;
- altri stati: in lettura.

Salvare e firmare sono rotte DIVERSE: `salva_bozza` non cambia mai lo stato,
`firma` e `rettifica` lavorano sul testo gia' salvato (la pagina salva
prima di mandare la conferma).
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from consulti import regole
from consulti.forms import DeclinaForm, NonRefertabileForm
from consulti.models import StatoAllegato, StatoRichiesta, TransizioneNonValida
from consulti.motivi import FRASI_DECLINA
from consulti.permessi import (caso_del_refertatore, e_refertatore_assegnato, e_richiedente,
                               registra_accesso_staff)
from consulti.racconto import racconta
from core.views_media import consegna
from . import pdf
from .blocchi import classificazione_leggibile
from .forms import RefertoForm
from .models import Referto, RefertoGiaFirmato, RefertoNonFirmabile, VersioneReferto

STATI_CON_EDITOR = (StatoRichiesta.PRESA_IN_CARICO, StatoRichiesta.REFERTATA)


def _voci_visore(richiesta):
    """Gli allegati per il visore, con l'etichetta della proiezione eco se
    c'e'. Il primo PDF (o il primo in assoluto) e' quello aperto all'arrivo."""
    proiezioni = {}
    for pc in richiesta.proiezioni.select_related('proiezione'):
        proiezioni.setdefault(pc.allegato_id, pc.proiezione.nome)
    voci = [{'allegato': a, 'genere': a.genere, 'proiezione': proiezioni.get(a.id)}
            for a in richiesta.allegati.exclude(stato=StatoAllegato.SCARTATO)]
    iniziale = next((v for v in voci if v['genere'] == 'pdf'), voci[0] if voci else None)
    return voci, iniziale


def _frasi_declina(refertatore):
    frasi = list(FRASI_DECLINA)
    if refertatore.assente_al:
        frasi = [f'Assente fino al {refertatore.assente_al:%d/%m/%Y}.' if f.startswith('Assente') else f
                 for f in frasi]
    return frasi


@login_required
def refertazione(request, pk):
    if request.user.is_staff and not hasattr(request.user, 'refertatore'):
        return redirect('consulti:dettaglio', pk=pk)
    richiesta = caso_del_refertatore(request.user, pk)
    if richiesta.stato == StatoRichiesta.BOZZA:
        raise Http404
    referto = None
    form = None
    if richiesta.stato == StatoRichiesta.PRESA_IN_CARICO:
        referto, _ = Referto.objects.get_or_create(richiesta=richiesta)
    else:
        referto = Referto.objects.filter(richiesta=richiesta).first()
    if referto is not None and richiesta.stato in STATI_CON_EDITOR:
        form = RefertoForm(instance=referto)
    versioni = list(referto.versioni.all()) if referto else []
    voci, iniziale = _voci_visore(richiesta)
    ore = regole.ore_risposta_dichiarate(richiesta)
    scadenza = richiesta.inviata_il + timedelta(hours=ore) if richiesta.inviata_il else None
    return render(request, 'referti/refertazione.html', {
        'richiesta': richiesta,
        'referto': referto,
        'form': form,
        'versioni': versioni,
        'ultima': versioni[0] if versioni else None,
        'classificazione_ultima': (classificazione_leggibile(richiesta.tipo_esame, versioni[0].classificazione)
                                   if versioni else []),
        'rettifica_in_corso': bool(referto and referto.firmato and referto.modificato_dopo_la_firma()),
        'voci_visore': voci,
        'iniziale': iniziale,
        'ore_dichiarate': ore,
        'scadenza': scadenza,
        'form_declina': DeclinaForm(),
        'frasi_declina': _frasi_declina(richiesta.refertatore),
        'form_nr': NonRefertabileForm(tipo_esame=richiesta.tipo_esame),
        'racconto': racconta(richiesta.audit.select_related('utente')),
    })


@login_required
@require_POST
def salva_bozza(request, pk):
    """Salva la copia di lavoro. Mai una firma, mai un cambio di stato.
    Con htmx risponde un frammento con l'ora del salvataggio."""
    richiesta = caso_del_refertatore(request.user, pk)
    if richiesta.stato not in STATI_CON_EDITOR:
        messaggio = f'Il caso e\' «{richiesta.get_stato_display()}»: il referto non si modifica.'
        if request.htmx:
            return render(request, 'referti/_stato_salvataggio.html', {'errore': messaggio}, status=409)
        messages.error(request, messaggio)
        return redirect('referti:refertazione', pk=pk)
    referto, _ = Referto.objects.get_or_create(richiesta=richiesta)
    form = RefertoForm(request.POST, instance=referto)
    if not form.is_valid():
        errore = '; '.join(f'{form.fields[c].label}: {" ".join(e)}' if c in form.fields else ' '.join(e)
                           for c, e in form.errors.items())
        if request.htmx:
            return render(request, 'referti/_stato_salvataggio.html', {'errore': errore}, status=400)
        messages.error(request, f'Bozza non salvata: {errore}')
        return redirect('referti:refertazione', pk=pk)
    form.save()
    if request.htmx:
        return render(request, 'referti/_stato_salvataggio.html', {'salvato_il': timezone.localtime()})
    messages.success(request, 'Bozza salvata.')
    return redirect('referti:refertazione', pk=pk)


@login_required
@require_POST
def firma(request, pk):
    """Prima firma, dal testo salvato. Solo il refertatore assegnato."""
    richiesta = caso_del_refertatore(request.user, pk)
    referto = Referto.objects.filter(richiesta=richiesta).first()
    if referto is None or not (referto.conclusioni or '').strip():
        messages.error(request, 'Le conclusioni sono vuote: scrivile e salva prima di firmare.')
        return redirect('referti:refertazione', pk=pk)
    try:
        versione = referto.firma(request.user)
    except (RefertoGiaFirmato, RefertoNonFirmabile, TransizioneNonValida, PermissionError) as e:
        messages.error(request, str(e))
        return redirect('referti:refertazione', pk=pk)
    from notifiche.servizi import avvisa_referto_pronto
    inviata = avvisa_referto_pronto(richiesta, versione)
    messages.success(request, f'Referto {richiesta.codice} firmato.'
                     + (' Il richiedente e\' stato avvisato via email.' if inviata
                        else ' ATTENZIONE: l\'email al richiedente non e\' partita.'))
    return redirect('referti:refertazione', pk=pk)


@login_required
@require_POST
def rettifica(request, pk):
    """Emette la versione n+1 dalla copia di lavoro salvata e dal motivo salvato."""
    richiesta = caso_del_refertatore(request.user, pk)
    referto = get_object_or_404(Referto, richiesta=richiesta)
    try:
        versione = referto.rettifica(request.user)
    except (RefertoNonFirmabile, PermissionError) as e:
        messages.error(request, str(e))
        return redirect('referti:refertazione', pk=pk)
    from notifiche.servizi import avvisa_referto_rettificato
    avvisa_referto_rettificato(richiesta, versione)
    messages.success(request, f'Rettifica emessa: versione {versione.numero}. Il richiedente e\' stato avvisato.')
    return redirect('referti:refertazione', pk=pk)


@login_required
@xframe_options_sameorigin
def anteprima(request, pk):
    """PDF della copia di lavoro, con la scritta BOZZA. Solo il refertatore."""
    richiesta = caso_del_refertatore(request.user, pk)
    referto = get_object_or_404(Referto, richiesta=richiesta)
    risposta = HttpResponse(pdf.genera_pdf(referto), content_type='application/pdf')
    risposta['Content-Disposition'] = f'inline; filename="{richiesta.codice}_anteprima.pdf"'
    return risposta


# ── PDF delle versioni firmate ───────────────────────────────────────────────

def _puo_vedere_versioni(utente, richiesta):
    return utente.is_staff or e_richiedente(utente, richiesta) or e_refertatore_assegnato(utente, richiesta)


def _consegna_versione(request, versione):
    richiesta = versione.referto.richiesta
    registra_accesso_staff(request.user, richiesta, f'PDF referto v{versione.numero}')
    nome = pdf.nome_file(versione)
    if not versione.pdf:
        contenuto = pdf.contenuto_pdf(versione)
        if contenuto is None:
            raise Http404
    return consegna(versione.pdf.name, nome_scaricato=nome)


@login_required
def stampa(request, pk):
    """PDF dell'ultima versione firmata del referto `pk`. Per il refertatore,
    finche' non e' firmato, e' l'anteprima della bozza."""
    referto = get_object_or_404(Referto.objects.select_related('richiesta__richiedente'), pk=pk)
    richiesta = referto.richiesta
    if not _puo_vedere_versioni(request.user, richiesta):
        raise Http404
    ultima = referto.ultima_versione
    if ultima is not None:
        return _consegna_versione(request, ultima)
    if e_refertatore_assegnato(request.user, richiesta):
        return redirect('referti:anteprima', pk=richiesta.pk)
    raise Http404  # il richiedente e lo staff non vedono bozze


@login_required
def stampa_versione(request, pk):
    versione = get_object_or_404(VersioneReferto.objects.select_related('referto__richiesta__richiedente'), pk=pk)
    if not _puo_vedere_versioni(request.user, versione.referto.richiesta):
        raise Http404
    return _consegna_versione(request, versione)
