"""
Il lato del richiedente: «Le mie richieste», upload degli allegati della
richiesta guidata (semplice e a pezzi), rimozione, invio, annullamento,
riassegnazione di un caso declinato, e la pagina del caso con il referto
firmato e il racconto dell'audit. I quattro passi della richiesta guidata
stanno in `views_percorso.py`; il lato del refertatore in
`views_decisione.py` e in `referti/views.py`.

Lo staff vede tutto in lettura e non agisce (consulti/permessi.py).
"""

import logging
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Refertatore
from . import caricamento, percorso, upload_chunk
from .models import Allegato, Richiesta, StatoRichiesta, TransizioneNonValida
from .permessi import caso_del_richiedente, e_refertatore_assegnato, registra_accesso_staff
from .racconto import racconta

logger = logging.getLogger('consulti')


def _richieste_visibili(utente):
    """Chi vede cosa. Staff tutto; richiedente le sue; refertatore quelle
    assegnate a lui o non assegnate nei tipi in cui e' referente, mai le
    bozze (una bozza e' ancora di chi la scrive)."""
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
        filtro |= (Q(refertatore=refertatore) | Q(refertatore__isnull=True, tipo_esame__in=tipi)) & \
            ~Q(stato=StatoRichiesta.BOZZA)
    return qs.filter(filtro)


def _richiesta_o_404(utente, pk):
    try:
        return _richieste_visibili(utente).get(pk=pk)
    except Richiesta.DoesNotExist:
        raise Http404


@login_required
def mie_richieste(request):
    """Le richieste di chi chiede (tutte per lo staff). Chi e' solo
    refertatore ha la sua pagina: i casi ricevuti."""
    richiedente = getattr(request.user, 'richiedente', None)
    if request.user.is_staff:
        richieste = _richieste_visibili(request.user)
    elif richiedente is not None:
        richieste = _richieste_visibili(request.user).filter(richiedente=richiedente)
    elif hasattr(request.user, 'refertatore'):
        return redirect('consulti:casi_ricevuti')
    else:
        richieste = Richiesta.objects.none()
    return render(request, 'consulti/mie_richieste.html', {
        'richieste': richieste,
        'puo_richiedere': bool(richiedente and richiedente.puo_richiedere),
    })


@login_required
def dettaglio(request, pk):
    """La pagina del caso per chi l'ha chiesto (e per lo staff, in lettura).
    Il refertatore assegnato va alla sua pagina di refertazione; chi ha
    chiesto, finche' il caso e' in bozza, riprende la richiesta guidata dal
    primo passo incompleto."""
    from referti.blocchi import classificazione_leggibile

    richiesta = _richiesta_o_404(request.user, pk)
    e_richiedente = richiesta.richiedente.user_id == request.user.id
    if not e_richiedente and e_refertatore_assegnato(request.user, richiesta):
        return redirect('referti:refertazione', pk=pk)
    if e_richiedente and richiesta.modificabile:
        return redirect(percorso.url_passo(richiesta, percorso.passo_da_riprendere(richiesta)))
    registra_accesso_staff(request.user, richiesta, 'caso')
    intestatario = richiesta.intestatario()
    intestatario_label = intestatario.denominazione + ('' if richiesta.clinica_id else ' (libero professionista)')
    referto = getattr(richiesta, 'referto', None)
    # Chi ha chiesto vede SOLO le versioni firmate, mai la copia di lavoro.
    versioni = list(referto.versioni.all()) if referto is not None else []
    ultima = versioni[0] if versioni else None
    return render(request, 'consulti/dettaglio.html', {
        'richiesta': richiesta,
        'intestatario_label': intestatario_label,
        'allegati': richiesta.allegati.all(),
        'racconto': racconta(richiesta.audit.select_related('utente'), per_staff=request.user.is_staff),
        'e_richiedente': e_richiedente,
        'ultima': ultima,
        'versioni': versioni,
        'classificazione_ultima': classificazione_leggibile(richiesta.tipo_esame, ultima.classificazione)
        if ultima else [],
        'esperti': (percorso.esperti_con_prezzo(richiesta.tipo_esame, richiesta.urgenza)
                    if e_richiedente and richiesta.stato == StatoRichiesta.DECLINATA else []),
        'puo_annullare': e_richiedente and richiesta.stato in (StatoRichiesta.BOZZA, StatoRichiesta.INVIATA),
    })


def _solo_richiedente_in_bozza(request, richiesta):
    if richiesta.richiedente.user_id != request.user.id:
        raise Http404
    if not richiesta.modificabile:
        raise TransizioneNonValida('La richiesta non e\' piu\' in bozza: gli allegati non si toccano.')


def _intero(valore):
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


def _vuole_json(request):
    """Il JS della pagina chiede JSON; senza JavaScript il modulo fa una POST
    normale e si torna alla pagina con un messaggio."""
    return 'application/json' in request.headers.get('Accept', '')


def _torna_al_caricamento(richiesta, slot='', proiezione_id=None):
    """Al passo 3, sulla zona appena usata (le zone hanno per id la chiave
    dell'elemento: 'ecg', 'eco_referto', 'proiezione_12', ...)."""
    ancora = f'#proiezione_{proiezione_id}' if slot == caricamento.SLOT_PROIEZIONE and proiezione_id else \
        (f'#{slot}' if slot else '')
    return redirect(reverse('consulti:passo_carica', args=[richiesta.pk]) + ancora)


@login_required
@require_POST
def carica_allegato(request, pk):
    """Un file in una zona del passo «Carica gli esami». La categoria la
    decide `caricamento` da zona + tipo di file; in una riga di proiezione
    nasce anche la ProiezioneCaricata. `sostituisci` = id del file che
    questo prende il posto."""
    richiesta = _richiesta_o_404(request.user, pk)
    json = _vuole_json(request)
    slot = request.POST.get('slot', '')
    try:
        _solo_richiedente_in_bozza(request, richiesta)
    except TransizioneNonValida as e:
        if json:
            return _json_errore(str(e), status=403)
        messages.error(request, str(e))
        return redirect('consulti:dettaglio', pk=pk)
    file_caricato = request.FILES.get('file')
    errore = None
    allegato = None
    if file_caricato is None:
        errore = 'Scegli un file da caricare.'
    elif file_caricato.size > settings.ALLEGATO_MAX_BYTE:
        errore = (f'Il file supera {settings.ALLEGATO_MAX_BYTE // (1024 * 1024)} MB: '
                  f'trascinalo nella zona con JavaScript attivo, parte il caricamento a pezzi.')
    else:
        try:
            allegato = caricamento.allega(
                richiesta, file_caricato, file_caricato.name, slot, request.user,
                proiezione_id=_intero(request.POST.get('proiezione')),
                sostituisci_id=_intero(request.POST.get('sostituisci')),
                mime=getattr(file_caricato, 'content_type', ''), nota=request.POST.get('nota', ''))
        except caricamento.CaricamentoNonValido as e:
            errore = str(e)
    if json:
        if errore:
            return _json_errore(errore)
        return JsonResponse({'allegato': allegato.id, 'nome': allegato.nome_originale})
    if errore:
        messages.error(request, errore)
    else:
        messages.success(request, f'«{allegato.nome_originale}» caricato.')
    return _torna_al_caricamento(richiesta, slot, _intero(request.POST.get('proiezione')))


@login_required
@require_POST
def elimina_allegato(request, pk, allegato_pk):
    """Solo in bozza e solo chi ha aperto la richiesta: dopo l'invio gli
    allegati sono cio' che il refertatore ha visto, e non si toccano. Con
    l'allegato se ne va anche la sua ProiezioneCaricata."""
    richiesta = _richiesta_o_404(request.user, pk)
    try:
        _solo_richiedente_in_bozza(request, richiesta)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('consulti:dettaglio', pk=pk)
    allegato = get_object_or_404(Allegato, pk=allegato_pk, richiesta=richiesta)
    nome = caricamento.rimuovi(allegato, request.user)
    messages.success(request, f'«{nome}» rimosso.')
    return _torna_al_caricamento(richiesta)


@login_required
@require_POST
def invia(request, pk):
    richiesta = caso_del_richiedente(request.user, pk)
    try:
        richiesta.invia(request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        if richiesta.modificabile:
            return redirect(percorso.url_passo(richiesta, 4))
        return redirect('consulti:dettaglio', pk=pk)
    from notifiche.servizi import avvisa_caso_arrivato
    avvisa_caso_arrivato(richiesta)
    # Cosa succede adesso lo dice il riquadro della pagina del caso (_esito_caso.html).
    messages.success(request, f'Richiesta inviata a {richiesta.refertatore}.')
    return redirect('consulti:dettaglio', pk=pk)


@login_required
@require_POST
def annulla(request, pk):
    """Solo chi ha chiesto, e solo prima della presa in carico (la regola e'
    in Richiesta.annulla)."""
    richiesta = caso_del_richiedente(request.user, pk)
    try:
        richiesta.annulla(request.user)
        messages.success(request, f'Richiesta {richiesta.codice} annullata.')
    except TransizioneNonValida as e:
        messages.error(request, str(e))
    return redirect('consulti:dettaglio', pk=pk)


@login_required
@require_POST
def riassegna(request, pk):
    """Un caso declinato torna al richiedente, che lo gira a un altro esperto
    (il select e' lo stesso della nuova richiesta: `_esperti.html`)."""
    richiesta = caso_del_richiedente(request.user, pk)
    refertatore = Refertatore.objects.filter(pk=request.POST.get('r-refertatore') or None).first()
    try:
        richiesta.riassegna(refertatore, request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('consulti:dettaglio', pk=pk)
    from notifiche.servizi import avvisa_caso_arrivato
    avvisa_caso_arrivato(richiesta)
    messages.success(request, f'{richiesta.codice} girato a {refertatore}.')
    return redirect('consulti:dettaglio', pk=pk)


# ── Upload a pezzi ───────────────────────────────────────────────────────────
# Tre endpoint JSON: stato, pezzo, concludi. Il client (static/consulti/js/
# carica.js) calcola l'impronta SHA-256, chiede lo stato e riparte da dove
# era. Stato e concludi ricevono anche la zona (slot, proiezione,
# sostituisci): lo stato la controlla PRIMA che partano centinaia di MB,
# concludi la usa per creare l'allegato con la stessa regola della POST
# semplice (consulti/caricamento.py).

def _json_errore(messaggio, status=400, **extra):
    return JsonResponse({'errore': messaggio, **extra}, status=status)


def _zona_dal_post(dati):
    return {'slot': dati.get('slot', ''), 'proiezione_id': _intero(dati.get('proiezione')),
            'sostituisci_id': _intero(dati.get('sostituisci')), 'nota': dati.get('nota', '')}


@login_required
@require_GET
def upload_stato(request, pk):
    richiesta = _richiesta_o_404(request.user, pk)
    if request.GET.get('slot'):
        try:
            _solo_richiedente_in_bozza(request, richiesta)
            zona = _zona_dal_post(request.GET)
            caricamento.controlla(richiesta, zona['slot'], request.GET.get('nome', ''), request.GET.get('mime', ''),
                                  proiezione_id=zona['proiezione_id'], sostituisci_id=zona['sostituisci_id'],
                                  dimensione=_intero(request.GET.get('dimensione')), nota=zona['nota'])
        except (TransizioneNonValida, caricamento.CaricamentoNonValido) as e:
            return _json_errore(str(e))
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
    nome = os.path.basename(request.POST.get('nome') or 'file')[:255]
    mime = request.POST.get('mime', '')
    zona = _zona_dal_post(request.POST)
    try:
        caricamento.controlla(richiesta, zona['slot'], nome, mime, proiezione_id=zona['proiezione_id'],
                              sostituisci_id=zona['sostituisci_id'], nota=zona['nota'])
        percorso_file = upload_chunk.concludi(impronta)
    except (caricamento.CaricamentoNonValido, upload_chunk.UploadNonValido) as e:
        return _json_errore(str(e))
    try:
        with open(percorso_file, 'rb') as f:
            allegato = caricamento.allega(richiesta, File(f, name=nome), nome, zona['slot'], request.user,
                                          proiezione_id=zona['proiezione_id'],
                                          sostituisci_id=zona['sostituisci_id'], nota=zona['nota'],
                                          mime=mime, impronta=impronta, a_pezzi=True)
    except caricamento.CaricamentoNonValido as e:
        upload_chunk.abbandona(impronta)
        return _json_errore(str(e))
    upload_chunk.abbandona(impronta)
    return JsonResponse({'allegato': allegato.id, 'nome': allegato.nome_originale})
