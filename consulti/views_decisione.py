"""
Il lato del refertatore sui casi: l'elenco dei casi ricevuti e le decisioni
(prendi in carico, anche **con riserva**, declina, non refertabile) piu' le
richieste di integrazione. La pagina dove si decide e si referta e'
`referti:refertazione`; qui ci sono le rotte POST e l'elenco. Solo il
refertatore assegnato agisce: per tutti gli altri 404.

## Accettare con riserva (24/09/2026)

Da quando un esame incompleto puo' essere inviato, l'esperto ha una via di
mezzo fra prendere in carico e declinare: accetta, scrive cosa gli manca e
il richiedente puo' caricarlo sul caso gia' partito. Il caso resta
PRESA_IN_CARICO e i tempi continuano a correre: la riserva non li ferma,
perche' fermarli vorrebbe dire che un caso puo' restare appeso per sempre.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.http import require_POST

from notifiche import servizi

from . import regole
from .forms import DeclinaForm, IntegrazioneForm, NonRefertabileForm
from .models import Richiesta, StatoRichiesta, TransizioneNonValida
from .permessi import caso_del_refertatore

STATI_DA_LAVORARE = (StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO)


def _riga(r, adesso):
    """Una riga dell'elenco: ore e scadenza da regole (4 ore se urgente)."""
    scadenza = regole.scadenza(r)
    return {
        'richiesta': r,
        'eta': timesince(r.inviata_il, adesso, depth=1) if r.inviata_il else '—',
        'ore_risposta': regole.ore_risposta(r),
        'scadenza': scadenza,
        'in_ritardo': bool(scadenza and adesso > scadenza and r.stato in STATI_DA_LAVORARE),
    }


@login_required
def casi_ricevuti(request):
    """I casi assegnati al refertatore: prima quelli da lavorare (urgenti in
    cima, poi dal piu' vecchio), sotto gli ultimi chiusi."""
    refertatore = getattr(request.user, 'refertatore', None)
    if refertatore is None:
        return redirect('consulti:mie_richieste')
    adesso = timezone.now()
    base = (Richiesta.objects.filter(refertatore=refertatore).exclude(stato=StatoRichiesta.BOZZA)
            .select_related('richiedente__user', 'clinica', 'paziente', 'refertatore'))
    aperti = list(base.filter(stato__in=STATI_DA_LAVORARE)
              .annotate(da_decidere=Case(When(stato=StatoRichiesta.INVIATA, then=Value(0)), default=Value(1),
                                         output_field=IntegerField()))
              .order_by('-urgenza', 'da_decidere', 'inviata_il'))
    chiusi = base.exclude(stato__in=STATI_DA_LAVORARE).order_by('-chiusa_il')[:50]
    return render(request, 'consulti/casi_ricevuti.html', {
        'aperti': [_riga(r, adesso) for r in aperti],
        'chiusi': [_riga(r, adesso) for r in chiusi],
        'da_decidere': sum(1 for r in aperti if r.stato == StatoRichiesta.INVIATA),
    })


@login_required
@require_POST
def prendi_in_carico(request, pk):
    """Con `riserva=si` nel POST serve anche il testo di cosa manca: il caso
    si prende lo stesso e parte la richiesta di integrazione."""
    richiesta = caso_del_refertatore(request.user, pk)
    riserva = request.POST.get('riserva') == 'si'
    form = IntegrazioneForm(request.POST) if riserva else None
    if riserva and not form.is_valid():
        errori = ' '.join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f'Accettazione con riserva: {errori}')
        return redirect('referti:refertazione', pk=pk)
    try:
        integrazione = richiesta.prendi_in_carico(
            request.user.refertatore, request.user, riserva=riserva,
            motivo_riserva=form.cleaned_data['testo'] if riserva else '')
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('referti:refertazione', pk=pk)
    if integrazione is not None:
        servizi.avvisa_integrazione_chiesta(richiesta, integrazione)
        messages.success(request, f'{richiesta.codice} preso in carico con riserva: '
                                  'ho scritto a chi ha chiesto cosa serve.')
    else:
        messages.success(request, f'Hai preso in carico {richiesta.codice}: il referto e\' tuo.')
    return redirect('referti:refertazione', pk=pk)


@login_required
@require_POST
def chiedi_integrazione(request, pk):
    """Altre integrazioni durante la presa in carico: stesso meccanismo
    della riserva, senza cambiare stato."""
    richiesta = caso_del_refertatore(request.user, pk)
    form = IntegrazioneForm(request.POST)
    if not form.is_valid():
        errori = ' '.join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f'Richiesta di integrazioni: {errori}')
        return redirect('referti:refertazione', pk=pk)
    try:
        integrazione = richiesta.chiedi_integrazione(form.cleaned_data['testo'], request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('referti:refertazione', pk=pk)
    servizi.avvisa_integrazione_chiesta(richiesta, integrazione)
    messages.success(request, 'Richiesta inviata: chi ha chiesto il consulto puo\' caricare i file che servono.')
    return redirect('referti:refertazione', pk=pk)


@login_required
@require_POST
def declina(request, pk):
    richiesta = caso_del_refertatore(request.user, pk)
    form = DeclinaForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Per declinare serve un motivo: lo legge chi ha chiesto.')
        return redirect('referti:refertazione', pk=pk)
    try:
        richiesta.declina(form.cleaned_data['motivo'], request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('referti:refertazione', pk=pk)
    from notifiche.servizi import avvisa_caso_declinato
    avvisa_caso_declinato(richiesta, request.user.refertatore)
    messages.success(request, f'{richiesta.codice} declinato: il caso torna a chi l\'ha chiesto.')
    return redirect('consulti:casi_ricevuti')


@login_required
@require_POST
def non_refertabile(request, pk):
    """Chiude il caso senza referto e SENZA prestazione (da confermare con
    Andre: oggi un caso non refertabile non si fattura)."""
    richiesta = caso_del_refertatore(request.user, pk)
    form = NonRefertabileForm(request.POST, tipo_esame=richiesta.tipo_esame)
    if not form.is_valid():
        errori = ' '.join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f'Non refertabile: {errori}')
        return redirect('referti:refertazione', pk=pk)
    try:
        richiesta.segna_non_refertabile(form.cleaned_data['motivo'], request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('referti:refertazione', pk=pk)
    from notifiche.servizi import avvisa_non_refertabile
    avvisa_non_refertabile(richiesta)
    messages.success(request, f'{richiesta.codice} segnato come non refertabile: il richiedente e\' avvisato.')
    return redirect('consulti:casi_ricevuti')
