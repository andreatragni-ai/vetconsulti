"""
Dashboard «Le mie richieste», creazione di una richiesta in bozza, upload
degli allegati (semplice e a pezzi). Il flusso guidato per tipo di esame e
la refertazione arrivano nelle fasi successive.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Refertatore
from core.tipi import TipoEsame
from listino.prezzi import PrezzoNonDisponibile, prezzo_effettivo
from . import regole, upload_chunk
from .forms import AllegatoForm, NuovaRichiestaForm, PazienteForm
from .models import Allegato, CategoriaAllegato, Richiesta, StatoRichiesta, TransizioneNonValida

logger = logging.getLogger('consulti')


def _richieste_visibili(utente):
    """Chi vede cosa. Staff tutto; richiedente le sue; refertatore quelle
    assegnate a lui o non assegnate nei tipi in cui e' referente."""
    qs = Richiesta.objects.select_related('richiedente__user', 'clinica', 'refertatore__user', 'paziente')
    if utente.is_staff:
        return qs
    filtro = Q(pk__in=[])
    richiedente = getattr(utente, 'richiedente', None)
    if richiedente is not None:
        filtro |= Q(richiedente=richiedente)
    refertatore = getattr(utente, 'refertatore', None)
    if refertatore is not None:
        tipi = list(refertatore.competenze.filter(referente=True).values_list('tipo_esame', flat=True))
        filtro |= Q(refertatore=refertatore) | (
            Q(refertatore__isnull=True, tipo_esame__in=tipi) & ~Q(stato=StatoRichiesta.BOZZA))
    return qs.filter(filtro)


def _richiesta_o_404(utente, pk):
    try:
        return _richieste_visibili(utente).get(pk=pk)
    except Richiesta.DoesNotExist:
        raise Http404


@login_required
def mie_richieste(request):
    richieste = _richieste_visibili(request.user)
    richiedente = getattr(request.user, 'richiedente', None)
    return render(request, 'consulti/mie_richieste.html', {
        'richieste': richieste,
        'puo_richiedere': bool(richiedente and richiedente.puo_richiedere),
    })


def _esperti_con_prezzo(tipo, urgenza=False):
    """Refertatori referenti per il tipo, con prezzo e tempo accanto."""
    righe = []
    for r in Refertatore.referenti_per(tipo):
        comp = r.competenza_per(tipo)
        try:
            prezzo = prezzo_effettivo(tipo, refertatore=r, urgenza=urgenza)
        except PrezzoNonDisponibile:
            prezzo = None
        righe.append({'refertatore': r, 'prezzo': prezzo,
                      'tempo': comp.tempo_risposta_ore if comp else None})
    return righe


@login_required
@require_GET
def esperti(request):
    """Frammento htmx: il select degli esperti per il tipo scelto."""
    tipo = request.GET.get('tipo_esame', TipoEsame.ECG)
    if tipo not in TipoEsame.values:
        raise Http404
    urgenza = request.GET.get('urgenza') in ('on', 'true', '1')
    return render(request, 'consulti/_esperti.html', {
        'esperti': _esperti_con_prezzo(tipo, urgenza), 'selezionato': request.GET.get('refertatore')})


@login_required
def nuova_richiesta(request):
    richiedente = getattr(request.user, 'richiedente', None)
    if richiedente is None:
        messages.error(request, 'Solo un richiedente puo\' aprire una richiesta.')
        return redirect('consulti:mie_richieste')
    if not richiedente.e_libero_professionista and richiedente.clinica_id is None:
        messages.warning(request, 'Indica prima la tua clinica nel profilo.')
        return redirect('accounts:profilo_richiedente')

    form = NuovaRichiestaForm(request.POST or None, prefix='r')
    form_p = PazienteForm(request.POST or None, prefix='p')
    if request.method == 'POST' and form.is_valid() and form_p.is_valid():
        with transaction.atomic():
            richiesta = form.save(commit=False)
            richiesta.richiedente = richiedente
            richiesta.clinica = richiedente.clinica
            richiesta.save()
            paziente = form_p.save(commit=False)
            paziente.richiesta = richiesta
            paziente.save()
            richiesta.registra('CREATA', request.user, tipo=richiesta.tipo_esame)
        messages.success(request, f'Richiesta {richiesta.codice} creata in bozza: ora carica gli allegati.')
        return redirect('consulti:dettaglio', pk=richiesta.pk)

    tipo = form.data.get('r-tipo_esame') or TipoEsame.ECG
    return render(request, 'consulti/nuova_richiesta.html', {
        'form': form, 'form_p': form_p,
        'esperti': _esperti_con_prezzo(tipo if tipo in TipoEsame.values else TipoEsame.ECG),
        'puo_richiedere': richiedente.puo_richiedere,
        'selezionato': form.data.get('r-refertatore', ''),
    })


@login_required
def dettaglio(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    e_richiedente = richiesta.richiedente.user_id == request.user.id
    form_a = AllegatoForm(tipo_esame=richiesta.tipo_esame)
    intestatario = richiesta.intestatario()
    intestatario_label = intestatario.denominazione + ('' if richiesta.clinica_id else ' (libero professionista)')
    return render(request, 'consulti/dettaglio.html', {
        'richiesta': richiesta,
        'intestatario_label': intestatario_label,
        'allegati': richiesta.allegati.all(),
        'audit': richiesta.audit.select_related('utente'),
        'form_a': form_a,
        'e_richiedente': e_richiedente,
        'motivo_blocco': regole.perche_non_puoi_inviare(richiesta) if richiesta.modificabile else None,
        'upload_max_byte': upload_chunk.max_byte(),
    })


def _solo_richiedente_in_bozza(request, richiesta):
    if richiesta.richiedente.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    if not richiesta.modificabile:
        raise TransizioneNonValida('La richiesta non e\' piu\' in bozza: gli allegati non si toccano.')


@login_required
@require_POST
def carica_allegato(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    try:
        _solo_richiedente_in_bozza(request, richiesta)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('consulti:dettaglio', pk=pk)
    form = AllegatoForm(request.POST, request.FILES, tipo_esame=richiesta.tipo_esame)
    if form.is_valid():
        Allegato.da_upload(richiesta, form.cleaned_data['file'], form.cleaned_data['categoria'], request.user)
        messages.success(request, 'Allegato caricato.')
    else:
        for errori in form.errors.values():
            for e in errori:
                messages.error(request, e)
    return redirect('consulti:dettaglio', pk=pk)


@login_required
@require_POST
def elimina_allegato(request, pk, allegato_pk):
    """Solo in bozza e solo chi ha aperto la richiesta: dopo l'invio gli
    allegati sono cio' che il refertatore ha visto, e non si toccano."""
    richiesta = _richiesta_o_404(request.user, pk)
    try:
        _solo_richiedente_in_bozza(request, richiesta)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('consulti:dettaglio', pk=pk)
    allegato = get_object_or_404(Allegato, pk=allegato_pk, richiesta=richiesta)
    nome = allegato.nome_originale
    allegato.proiezioni.all().delete()
    if allegato.file:
        allegato.file.delete(save=False)
    allegato.delete()
    richiesta.registra('ALLEGATO_ELIMINATO', request.user, allegato=allegato_pk, nome=nome)
    messages.success(request, f'Allegato «{nome}» eliminato.')
    return redirect('consulti:dettaglio', pk=pk)


@login_required
@require_POST
def invia(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    if richiesta.richiedente.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    try:
        richiesta.invia(request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('consulti:dettaglio', pk=pk)
    from notifiche.servizi import avvisa_caso_arrivato
    avvisa_caso_arrivato(richiesta)
    messages.success(request, f'Richiesta {richiesta.codice} inviata a {richiesta.refertatore}.')
    return redirect('consulti:dettaglio', pk=pk)


@login_required
@require_POST
def annulla(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    if richiesta.richiedente.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    try:
        richiesta.annulla(request.user)
        messages.success(request, f'Richiesta {richiesta.codice} annullata.')
    except TransizioneNonValida as e:
        messages.error(request, str(e))
    return redirect('consulti:dettaglio', pk=pk)


# ── Upload a pezzi ───────────────────────────────────────────────────────────
# Tre endpoint JSON: stato, pezzo, concludi. Il client (JS in dettaglio.html)
# calcola l'impronta SHA-256, chiede lo stato e riparte da dove era.

def _json_errore(messaggio, status=400, **extra):
    return JsonResponse({'errore': messaggio, **extra}, status=status)


@login_required
@require_GET
def upload_stato(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    try:
        return JsonResponse({'ricevuti': upload_chunk.quanto_ho(request.GET.get('impronta', ''))})
    except upload_chunk.UploadNonValido as e:
        return _json_errore(str(e))


@login_required
@require_POST
def upload_pezzo(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    try:
        _solo_richiedente_in_bozza(request, richiesta)
    except TransizioneNonValida as e:
        return _json_errore(str(e), status=403)
    impronta = request.POST.get('impronta', '')
    pezzo = request.FILES.get('pezzo')
    if pezzo is None:
        return _json_errore('Manca il pezzo.')
    try:
        offset = int(request.POST.get('offset', ''))
    except ValueError:
        return _json_errore('Offset non valido.')
    try:
        ricevuti = upload_chunk.ricevi_pezzo(impronta, offset, pezzo.read())
    except upload_chunk.UploadNonValido as e:
        try:
            presenti = upload_chunk.quanto_ho(impronta)
        except upload_chunk.UploadNonValido:
            return _json_errore(str(e))
        return _json_errore(str(e), status=409, ricevuti=presenti)
    return JsonResponse({'ricevuti': ricevuti})


@login_required
@require_POST
def upload_concludi(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    try:
        _solo_richiedente_in_bozza(request, richiesta)
    except TransizioneNonValida as e:
        return _json_errore(str(e), status=403)
    impronta = request.POST.get('impronta', '')
    categoria = request.POST.get('categoria', CategoriaAllegato.ALTRO)
    if categoria not in CategoriaAllegato.values:
        return _json_errore('Categoria non valida.')
    nome = (request.POST.get('nome') or 'file')[:255]
    try:
        percorso = upload_chunk.concludi(impronta)
    except upload_chunk.UploadNonValido as e:
        return _json_errore(str(e))
    with open(percorso, 'rb') as f:
        allegato = Allegato(richiesta=richiesta, categoria=categoria, nome_originale=nome,
                            dimensione=percorso.stat().st_size, sha256=impronta,
                            caricato_da=request.user)
        allegato.file.save(nome, File(f), save=True)
    upload_chunk.abbandona(impronta)
    richiesta.registra('ALLEGATO_CARICATO', request.user, allegato=allegato.id, categoria=categoria,
                       nome=nome, a_pezzi=True)
    return JsonResponse({'allegato': allegato.id, 'nome': allegato.nome_originale})
