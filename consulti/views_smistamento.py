"""
Il tavolo di smistamento dell'eco nel passo «Carica gli esami»: avvio dello
smistamento automatico dopo il caricamento della cartella, stato letto con
htmx, «Sposta in...» (e trascinamento) di un file, «Confermo lo
smistamento». Solo chi ha aperto la richiesta e solo finche' e' in BOZZA
(stesse regole degli allegati: consulti/views.py). La logica sta in
eco/smistamento/ (tavolo.py, esecuzione.py); qui solo richieste e risposte.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.tipi import TipoEsame
from .models import Allegato
from .permessi import caso_del_richiedente


def _bozza_eco(request, pk):
    richiesta = caso_del_richiedente(request.user, pk)
    if richiesta.tipo_esame != TipoEsame.ECO:
        raise Http404
    return richiesta


def _al_tavolo(richiesta, ancora=''):
    return redirect(reverse('consulti:passo_carica', args=[richiesta.pk]) + (f'#{ancora}' if ancora else ''))


def _vuole_json(request):
    return 'application/json' in request.headers.get('Accept', '')


@login_required
@require_POST
def avvia(request, pk):
    """Dopo il caricamento della cartella: parte lo smistamento automatico."""
    from eco.smistamento import esecuzione
    richiesta = _bozza_eco(request, pk)
    if not richiesta.modificabile:
        return JsonResponse({'errore': 'La richiesta non e\' piu\' in bozza.'}, status=403)
    s = esecuzione.avvia(richiesta, request.user)
    if _vuole_json(request):
        return JsonResponse({'smistamento': s.pk, 'stato': s.stato,
                             'url_stato': reverse('consulti:smistamento_stato', args=[richiesta.pk])})
    return _al_tavolo(richiesta)


@login_required
@require_GET
def stato(request, pk):
    """Frammento htmx: «sto smistando» finche' l'ultimo smistamento e' in
    corso; poi chiede alla pagina di ricaricarsi (HX-Refresh) per mostrare
    il tavolo con le proposte."""
    from eco.smistamento import esecuzione
    richiesta = _bozza_eco(request, pk)
    in_corso = esecuzione.in_corso(richiesta)
    if in_corso is None:
        risposta = HttpResponse('')
        risposta['HX-Refresh'] = 'true'
        return risposta
    return render(request, 'consulti/percorso/_smistamento_in_corso.html',
                  {'richiesta': richiesta, 'smistamento': in_corso})


@login_required
@require_POST
def sposta(request, pk):
    """Un file in un'altra riga, nel referto o fra i «da smistare»; se il
    posto e' occupato i due file si scambiano. Solo una proposta."""
    from eco.smistamento import tavolo
    richiesta = _bozza_eco(request, pk)
    if not richiesta.modificabile:
        messages.error(request, 'La richiesta non e\' piu\' in bozza: i file non si spostano.')
        return redirect('consulti:dettaglio', pk=pk)
    allegato = get_object_or_404(Allegato, pk=request.POST.get('allegato') or None, richiesta=richiesta)
    destinazione = request.POST.get('destinazione', '')
    try:
        p = tavolo.sposta(richiesta, allegato, destinazione, nota=request.POST.get('nota'))
    except tavolo.SpostamentoNonValido as e:
        if _vuole_json(request):
            return JsonResponse({'errore': str(e)}, status=400)
        messages.error(request, str(e))
        return _al_tavolo(richiesta)
    ancora = f'proiezione_{p.proiezione_id}' if p.proiezione_id else ('eco_referto' if p.referto else 'da-smistare')
    if _vuole_json(request):
        return JsonResponse({'ok': True, 'ancora': ancora})
    return _al_tavolo(richiesta, ancora)


@login_required
@require_POST
def conferma(request, pk):
    """«Confermo lo smistamento»: le proposte diventano ProiezioneCaricata
    (e il PDF proposto diventa il referto dell'ecografo)."""
    from eco.smistamento import tavolo
    richiesta = _bozza_eco(request, pk)
    if not richiesta.modificabile:
        messages.error(request, 'La richiesta non e\' piu\' in bozza.')
        return redirect('consulti:dettaglio', pk=pk)
    note = {}
    for chiave, valore in request.POST.items():
        if chiave.startswith('nota_'):
            try:
                note[int(chiave[5:])] = valore
            except ValueError:
                continue
    try:
        righe, da_smistare = tavolo.conferma(richiesta, request.user, note)
    except tavolo.SmistamentoNonValido as e:
        messages.error(request, str(e))
        return _al_tavolo(richiesta, 'filmati-liberi')
    frase = f'Smistamento confermato: {righe} {"riga" if righe == 1 else "righe"} con il loro file.'
    if da_smistare:
        frase += f' {da_smistare} file restano da smistare: il collega li vede in fondo, fuori dalle righe.'
    messages.success(request, frase)
    return _al_tavolo(richiesta)


# ── Contesto del tavolo per il passo 3 (views_percorso.contesto_caricamento) ──

ICONE = {'video': 'camera-reels', 'immagine': 'image', 'pdf': 'file-earmark-pdf', 'dicom': 'file-earmark-medical'}


def contesto_tavolo(richiesta, ctx):
    """Aggiunge alle righe del passo 3 il file proposto (`riga['posto']`) e
    prepara referto, file da smistare, stato dell'ultimo smistamento e
    quante proposte aspettano la conferma."""
    from consulti.caricamento import genere_file
    from eco.models import ProiezioneCatalogo, PropostaSmistamento, in_ordine
    from eco.smistamento import esecuzione, tavolo
    from eco.smistamento.motore import chiave_naturale

    tavolo.assicura_proposte(richiesta)
    proposte = list(PropostaSmistamento.objects.filter(richiesta=richiesta)
                    .select_related('allegato', 'proiezione', 'seconda_scelta'))
    confermate, referti = tavolo.stato_confermato(richiesta)
    catalogo = in_ordine(ProiezioneCatalogo.objects.filter(attiva=True))

    def posto(p):
        confermata = tavolo.e_confermata(p, confermate, referti)
        genere = genere_file(p.allegato.nome_originale or p.allegato.file.name, p.allegato.mime)
        return {'proposta': p, 'allegato': p.allegato, 'confermata': confermata, 'genere': genere,
                'icona': ICONE.get(genere, 'file-earmark'), 'bollino': tavolo.bollino(p, confermata),
                'voci': tavolo.destinazioni(richiesta, p.allegato, catalogo)}

    per_riga = {p.proiezione_id: posto(p) for p in proposte if p.proiezione_id}
    vuote = 0
    for g in ctx.get('gruppi_eco', []):
        g['pieni'] = 0
        for r in g['obbligatorie'] + g['facoltative']:
            r['posto'] = per_riga.get(r['proiezione'].id)
            if r['proiezione'].obbligatoria:
                g['pieni'] += bool(r['posto'])
                vuote += not r['posto']
    for r in ctx.get('righe_libere', []):
        r['posto'] = per_riga.get(r['proiezione'].id)
    da_smistare = sorted((p for p in proposte if p.da_smistare),
                         key=lambda p: (chiave_naturale(p.percorso_originale or p.allegato.nome_originale), p.pk))
    referto = next((p for p in proposte if p.referto), None)
    ultimo = richiesta.smistamenti.first()
    sicure = sum(1 for p in proposte if p.sicura and not p.da_smistare)
    return {
        'tavolo': True,
        'posto_referto': posto(referto) if referto else None,
        'da_smistare': [posto(p) for p in da_smistare],
        'n_file_eco': len(proposte),
        'n_sicure': sicure,
        'n_da_verificare': sum(1 for p in proposte if not p.da_smistare and not p.sicura
                               and not tavolo.e_confermata(p, confermate, referti)),
        'righe_vuote_obbligatorie': vuote,
        'smistamento': ultimo,
        'smistamento_in_corso': esecuzione.in_corso(richiesta),
        'modifiche_da_confermare': sum(1 for p in proposte if not tavolo.e_confermata(p, confermate, referti)),
    }
