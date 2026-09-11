"""
Le pagine della richiesta guidata (consulti/percorso.py): quattro passi,
un solo pulsante principale per passo, sempre in fondo.

Prima che la bozza esista (passi 1 e 2 di una richiesta nuova) le rotte
sono `nuova/` e `nuova/esame/` e i dati del paziente stanno in sessione;
dopo, ogni passo e' `<pk>/<passo>/` e salva sulla Richiesta. Solo chi ha
aperto la richiesta vede i passi (404 per tutti gli altri, refertatore e
staff compresi: una bozza e' ancora di chi la scrive), e solo finche' e' in
BOZZA: dopo l'invio si torna alla pagina del caso.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from core.tipi import TipoEsame
from listino.prezzi import PrezzoNonDisponibile, prezzo_effettivo
from . import caricamento, percorso, regole, upload_chunk
from .forms import EsameForm, PazienteForm
from .permessi import caso_del_richiedente

CAMPI_PAZIENTE = ('nome', 'specie', 'razza', 'sesso', 'data_nascita', 'eta_anni', 'peso_kg', 'cognome_proprietario')
CAMPI_ESAME = ('tipo_esame', 'refertatore', 'urgenza', 'quesito', 'anamnesi', 'terapia')

# Cosa servira' caricare, per le schede del tipo di esame (passo 2).
TIPI = (
    {'valore': TipoEsame.ECG, 'icona': 'activity',
     'cosa': 'il tracciato in PDF oppure una foto nitida.'},
    {'valore': TipoEsame.HOLTER, 'icona': 'clock-history',
     'cosa': 'il referto del software Holter in PDF; il file dell\'apparecchio, se vuoi.'},
    {'valore': TipoEsame.ECO, 'icona': 'heart-pulse',
     'cosa': 'il referto dell\'ecografo in PDF e le proiezioni richieste, filmati o immagini.'},
)


def _richiedente_o_redirect(request):
    """(richiedente, None) se l'utente puo' aprire una richiesta, altrimenti
    (None, redirect) con il messaggio che spiega perche'."""
    richiedente = getattr(request.user, 'richiedente', None)
    if richiedente is None:
        messages.error(request, 'Solo un richiedente puo\' aprire una richiesta.')
        return None, redirect('consulti:mie_richieste')
    if not richiedente.e_libero_professionista and richiedente.clinica_id is None:
        messages.warning(request, 'Indica prima la tua clinica nel profilo.')
        return None, redirect('accounts:profilo_richiedente')
    return richiedente, None


def _bozza(request, pk):
    """(richiesta, None) se e' una bozza di chi chiede; 404 se non e' sua;
    (richiesta, redirect alla pagina del caso) se e' gia' partita."""
    richiesta = caso_del_richiedente(request.user, pk)
    if not richiesta.modificabile:
        messages.info(request, 'La richiesta non e\' piu\' in bozza: qui la vedi, ma non si modifica.')
        return richiesta, redirect('consulti:dettaglio', pk=pk)
    return richiesta, None


def _grezzi(post, campi):
    """I valori del POST da tenere in sessione (JSON): solo i campi del form."""
    return {c: post.get(c) for c in campi if post.get(c) not in (None, '')}


# Testi che il form ripulisce (razza come nell'elenco, maiuscole sui nomi, data
# gg/mm/aaaa): in sessione vanno gia' puliti, cosi' il passo 2 e il ritorno al passo 1 li
# mostrano come verranno salvati.
TESTI_PULITI = ('nome', 'razza', 'cognome_proprietario')


def _paziente_in_sessione(form, post):
    grezzi = _grezzi(post, CAMPI_PAZIENTE)
    for campo in TESTI_PULITI:
        if form.cleaned_data.get(campo):
            grezzi[campo] = form.cleaned_data[campo]
        else:
            grezzi.pop(campo, None)
    if form.cleaned_data.get('data_nascita'):
        grezzi['data_nascita'] = form.cleaned_data['data_nascita'].strftime('%d/%m/%Y')
    return grezzi


def _tipi(form):
    scelto = form['tipo_esame'].value()
    return [{**t, 'etichetta': TipoEsame(t['valore']).label, 'scelto': scelto == t['valore']} for t in TIPI]


def _contesto_esperti(form):
    tipo = form['tipo_esame'].value()
    urgenza = form['urgenza'].value()
    if isinstance(urgenza, str):
        urgenza = urgenza in ('on', 'true', '1', 'True')
    selezionato = form['refertatore'].value()
    esperti = percorso.esperti_con_prezzo(tipo, bool(urgenza)) if tipo in TipoEsame.values else []
    return {
        'tipo_scelto': tipo if tipo in TipoEsame.values else '',
        'tipo_label': TipoEsame(tipo).label.lower() if tipo in TipoEsame.values else '',
        'esperti': esperti, 'urgenza': bool(urgenza),
        'nessuno_per_urgenza': bool(urgenza and esperti and not any(e['accetta_urgenze'] for e in esperti)),
        'selezionato': str(selezionato or ''),
    }


# ── Passo 1: paziente ────────────────────────────────────────────────────────

@login_required
def nuova_paziente(request):
    """Passo 1 di una richiesta nuova: i dati restano in sessione fino alla
    fine del passo 2. `?ricomincia=1` li butta."""
    richiedente, uscita = _richiedente_o_redirect(request)
    if uscita:
        return uscita
    if request.GET.get('ricomincia'):
        request.session.pop(percorso.SESSIONE_PAZIENTE, None)
        request.session.pop(percorso.SESSIONE_ESAME, None)
        return redirect('consulti:nuova')
    salvati = request.session.get(percorso.SESSIONE_PAZIENTE)
    if request.method == 'POST':
        form = PazienteForm(request.POST)
        if form.is_valid():
            request.session[percorso.SESSIONE_PAZIENTE] = _paziente_in_sessione(form, request.POST)
            return redirect('consulti:nuova_esame')
    else:
        form = PazienteForm(initial=salvati or {})
    return render(request, 'consulti/percorso/paziente.html', {
        'form': form, 'richiesta': None, 'ripreso': bool(salvati) and request.method != 'POST',
        'passi': percorso.indicatore(1, paziente_in_sessione=bool(salvati)),
        'puo_richiedere': richiedente.puo_richiedere,
    })


@login_required
def passo_paziente(request, pk):
    richiesta, uscita = _bozza(request, pk)
    if uscita:
        return uscita
    form = PazienteForm(request.POST or None, instance=richiesta.paziente)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(percorso.url_passo(richiesta, 2))
    return render(request, 'consulti/percorso/paziente.html', {
        'form': form, 'richiesta': richiesta, 'passi': percorso.indicatore(1, richiesta),
    })


# ── Passo 2: esame ed esperto ────────────────────────────────────────────────

@login_required
def nuova_esame(request):
    """Passo 2 di una richiesta nuova. «Avanti» crea la bozza (Richiesta +
    Paziente) e porta al caricamento; «Indietro» tiene quanto scritto."""
    richiedente, uscita = _richiedente_o_redirect(request)
    if uscita:
        return uscita
    dati_paziente = request.session.get(percorso.SESSIONE_PAZIENTE)
    if not dati_paziente:
        return redirect('consulti:nuova')
    if request.method == 'POST':
        if request.POST.get('azione') == 'indietro':
            request.session[percorso.SESSIONE_ESAME] = _grezzi(request.POST, CAMPI_ESAME)
            return redirect('consulti:nuova')
        form = EsameForm(request.POST)
        form_p = PazienteForm(dati_paziente)
        if not form_p.is_valid():
            messages.error(request, 'Controlla i dati del paziente.')
            return redirect('consulti:nuova')
        if form.is_valid():
            with transaction.atomic():
                richiesta = form.save(commit=False)
                richiesta.richiedente = richiedente
                richiesta.clinica = richiedente.clinica
                richiesta.save()
                paziente = form_p.save(commit=False)
                paziente.richiesta = richiesta
                paziente.save()
                richiesta.registra('CREATA', request.user, tipo=richiesta.tipo_esame)
            request.session.pop(percorso.SESSIONE_PAZIENTE, None)
            request.session.pop(percorso.SESSIONE_ESAME, None)
            return redirect(percorso.url_passo(richiesta, 3))
    else:
        salvati = request.session.get(percorso.SESSIONE_ESAME)
        form = EsameForm(initial=salvati or {})
    return render(request, 'consulti/percorso/esame.html', {
        'form': form, 'richiesta': None, 'tipi': _tipi(form), **_contesto_esperti(form),
        'passi': percorso.indicatore(2, paziente_in_sessione=True),
        'nome_paziente': dati_paziente.get('nome', ''),
    })


@login_required
def passo_esame(request, pk):
    richiesta, uscita = _bozza(request, pk)
    if uscita:
        return uscita
    form = EsameForm(request.POST or None, instance=richiesta)
    if request.method == 'POST':
        indietro = request.POST.get('azione') == 'indietro'
        if form.is_valid():
            form.save()
            return redirect(percorso.url_passo(richiesta, 1 if indietro else 3))
        if indietro:
            # Tornando indietro con un campo non valido non si salva nulla:
            # resta l'ultima versione buona, e lo si dice.
            messages.warning(request, 'Le modifiche all\'esame non erano complete e non sono state salvate.')
            return redirect(percorso.url_passo(richiesta, 1))
    return render(request, 'consulti/percorso/esame.html', {
        'form': form, 'richiesta': richiesta, 'tipi': _tipi(form), **_contesto_esperti(form),
        'passi': percorso.indicatore(2, richiesta), 'nome_paziente': richiesta.paziente.nome,
    })


@login_required
@require_GET
def esperti(request):
    """Frammento htmx: le schede degli esperti per il tipo scelto, con i
    prezzi con o senza urgenza."""
    from django.http import Http404
    tipo = request.GET.get('tipo_esame', '')
    if tipo not in TipoEsame.values:
        raise Http404
    urgenza = request.GET.get('urgenza') in ('on', 'true', '1')
    esperti = percorso.esperti_con_prezzo(tipo, urgenza)
    return render(request, 'consulti/percorso/_esperti.html', {
        'esperti': esperti, 'selezionato': request.GET.get('refertatore', ''),
        'tipo_scelto': tipo, 'tipo_label': TipoEsame(tipo).label.lower(), 'urgenza': urgenza,
        'nessuno_per_urgenza': bool(urgenza and esperti and not any(e['accetta_urgenze'] for e in esperti)),
    })


# ── Passo 3: carica gli esami ────────────────────────────────────────────────

def _file_per_categorie(allegati, categorie):
    return [a for a in allegati if a.categoria in categorie]


TESTI_ZONA = {
    # tipo_media -> (testo con il mouse, testo al tocco, sottotesto)
    'CLIP': ('Trascina qui il filmato', 'Tocca per scegliere il filmato',
             'MP4, AVI, MOV o DICOM · massimo 10 secondi'),
    'STATICA': ('Trascina qui l\'immagine', 'Tocca per scegliere l\'immagine', 'JPG, PNG o DICOM'),
    'ENTRAMBI': ('Trascina qui il filmato o l\'immagine', 'Tocca per scegliere il file',
                 'Un file: filmato (massimo 10 secondi) oppure immagine'),
}
ATTESO = {'CLIP': ('camera-reels', 'Filmato'), 'STATICA': ('image', 'Immagine'),
          'ENTRAMBI': ('collection-play', 'Filmato o immagine')}


def _riga_proiezione(p, caricate):
    """Una riga del catalogo nel passo 3: la proiezione, le immagini di
    riferimento (la prima grande, le altre miniature), il file caricato
    (ProiezioneCaricata con l'allegato: una riga = un file) e la zona finche'
    la riga e' vuota."""
    testo, testo_tocco, sottotesto = TESTI_ZONA.get(p.tipo_media, TESTI_ZONA['ENTRAMBI'])
    if p.tipo_media != 'STATICA':
        sottotesto += f' · fino a {settings.ECO_CLIP_MAX_BYTE // (1024 * 1024)} MB'
    icona, atteso = ATTESO.get(p.tipo_media, ATTESO['ENTRAMBI'])
    immagini = list(p.immagini.all())
    return {'proiezione': p, 'caricate': caricate, 'fatta': bool(caricate), 'zona_aperta': not caricate,
            'immagini': immagini, 'prima': immagini[0] if immagini else None, 'altre': immagini[1:],
            'accetta': caricamento.accetta_per(p), 'filmato': p.tipo_media in ('CLIP', 'ENTRAMBI'),
            'testo': testo, 'testo_tocco': testo_tocco, 'sottotesto': sottotesto,
            'icona_atteso': icona, 'atteso': atteso}


def _gruppi_eco(per_proiezione):
    """Le righe del catalogo raggruppate per finestra acustica (nell'ordine
    di eco.models.ORDINE_FINESTRE), dentro la finestra prima le obbligatorie
    e poi le facoltative, ciascuna con i filmati prima delle immagini; i
    filmati liberi a parte, in fondo. Una finestra con tutte le obbligatorie
    caricate si presenta chiusa."""
    from eco.models import ORDINE_FINESTRE, Finestra, ProiezioneCatalogo, in_ordine
    catalogo = ProiezioneCatalogo.objects.filter(attiva=True).prefetch_related('immagini')
    righe = [_riga_proiezione(p, per_proiezione.get(p.id, [])) for p in in_ordine(catalogo)]
    gruppi = []
    for finestra in ORDINE_FINESTRE:
        della = [r for r in righe if r['proiezione'].finestra == finestra and not r['proiezione'].libera]
        if not della:
            continue
        obbligatorie = [r for r in della if r['proiezione'].obbligatoria]
        facoltative = [r for r in della if not r['proiezione'].obbligatoria]
        fatte = sum(1 for r in obbligatorie if r['fatta'])
        facoltative_caricate = sum(1 for r in facoltative if r['fatta'])
        gruppi.append({
            # ALTRO si chiama «Filmati liberi» (che pero' stanno nel loro gruppo in
            # fondo): proiezioni non libere senza finestra sono «Altre proiezioni».
            'finestra': finestra,
            'etichetta': 'Altre proiezioni' if finestra == Finestra.ALTRO else Finestra(finestra).label,
            'obbligatorie': obbligatorie, 'facoltative': facoltative,
            'fatte': fatte, 'totale': len(obbligatorie), 'facoltative_caricate': facoltative_caricate,
            'completa': fatte == len(obbligatorie),
        })
    liberi = [r for r in righe if r['proiezione'].libera]
    return {'gruppi_eco': gruppi, 'righe_libere': liberi,
            'etichetta_liberi': Finestra.ALTRO.label,
            'liberi_caricati': sum(1 for r in liberi if r['fatta']),
            'max_clip_mb': settings.ECO_CLIP_MAX_BYTE // (1024 * 1024),
            'max_clip': settings.ECO_CLIP_MAX_BYTE}


def _lista_a_gruppi(elementi):
    """La lista di controllo (gli elementi della regola, nel loro ordine)
    divisa sotto titoli per finestra acustica, solo per leggerla meglio con
    tante righe: [{etichetta, elementi, fatti}]. Il primo gruppo (i file che
    non sono proiezioni) non ha titolo."""
    from eco.models import Finestra, ProiezioneCatalogo
    finestre = dict(ProiezioneCatalogo.objects.filter(
        pk__in=[e.proiezione_id for e in elementi if e.proiezione_id]).values_list('pk', 'finestra'))
    gruppi = []
    for e in elementi:
        etichetta = Finestra(finestre[e.proiezione_id]).label if e.proiezione_id in finestre else ''
        if not gruppi or gruppi[-1]['etichetta'] != etichetta:
            gruppi.append({'etichetta': etichetta, 'elementi': [], 'fatti': 0})
        gruppi[-1]['elementi'].append(e)
        gruppi[-1]['fatti'] += e.fatto
    return gruppi


def contesto_caricamento(richiesta):
    """Cosa mostra il passo 3: la lista di controllo (dalla regola di
    invio), le zone per tipo e i file gia' caricati in ciascuna. I file che
    non stanno in nessuna zona (es. da una versione vecchia del portale)
    finiscono in «Altri file», con la possibilita' di rimuoverli."""
    allegati = list(richiesta.allegati.order_by('caricato_il', 'pk'))
    elementi = regole.elementi_obbligatori(richiesta)
    mostrati = set()
    mancanti = [e for e in elementi if not e.fatto]
    ctx = {'elementi': elementi, 'fatti': len(elementi) - len(mancanti), 'totale': len(elementi),
           'mancanti': mancanti, 'perche_fermo': regole.frase_mancanti([e.frase for e in mancanti]),
           'lista_a_gruppi': _lista_a_gruppi(elementi)}

    def zona(slot):
        files = _file_per_categorie(allegati, caricamento.CATEGORIE_PER_SLOT[slot])
        mostrati.update(a.pk for a in files)
        return {'slot': slot, 'files': files, 'accetta': caricamento.ACCETTA[slot]}

    if richiesta.tipo_esame == TipoEsame.ECG:
        ctx['zona_ecg'] = zona(caricamento.SLOT_ECG)
    elif richiesta.tipo_esame == TipoEsame.HOLTER:
        ctx['zona_holter_referto'] = zona(caricamento.SLOT_HOLTER_REFERTO)
        ctx['zona_holter_file'] = zona(caricamento.SLOT_HOLTER_FILE)
    elif richiesta.tipo_esame == TipoEsame.ECO:
        ctx['zona_eco_referto'] = zona(caricamento.SLOT_ECO_REFERTO)
        per_proiezione = {}
        for pc in richiesta.proiezioni.select_related('allegato').order_by('allegato__caricato_il', 'pk'):
            per_proiezione.setdefault(pc.proiezione_id, []).append(pc)
            mostrati.add(pc.allegato_id)
        ctx.update(_gruppi_eco(per_proiezione))
        # Il tavolo di smistamento: ogni file dell'eco sta in una riga, nel
        # referto o fra i «da smistare» (consulti/views_smistamento.py).
        from .views_smistamento import contesto_tavolo
        ctx.update(contesto_tavolo(richiesta, ctx))
        mostrati.update(a.pk for a in allegati)
    ctx['altri_file'] = [a for a in allegati if a.pk not in mostrati]
    return ctx


@login_required
def passo_carica(request, pk):
    richiesta, uscita = _bozza(request, pk)
    if uscita:
        return uscita
    return render(request, 'consulti/percorso/carica.html', {
        'richiesta': richiesta, 'passi': percorso.indicatore(3, richiesta),
        'max_semplice': settings.ALLEGATO_MAX_BYTE, 'max_pezzi': upload_chunk.max_byte(),
        **contesto_caricamento(richiesta),
    })


# ── Passo 4: riepilogo e invio ──────────────────────────────────────────────

def _allegati_in_ordine(richiesta):
    """I file per il riepilogo: prima quelli che non sono proiezioni (referto,
    tracciato), poi le proiezioni nell'ordine delle righe del passo 3."""
    allegati = list(richiesta.allegati.order_by('caricato_il', 'pk').prefetch_related('proiezioni__proiezione'))

    def chiave(a):
        pc = next(iter(a.proiezioni.all()), None)
        return (1, pc.proiezione.chiave_ordine()) if pc else (0, ())
    return sorted(allegati, key=chiave)


@login_required
def passo_riepilogo(request, pk):
    richiesta, uscita = _bozza(request, pk)
    if uscita:
        return uscita
    prezzo = None
    if richiesta.refertatore_id:
        try:
            prezzo = prezzo_effettivo(richiesta.tipo_esame, refertatore=richiesta.refertatore,
                                      urgenza=richiesta.urgenza)
        except PrezzoNonDisponibile:
            prezzo = None
    motivo = regole.perche_non_puoi_inviare(richiesta)
    # Dove si corregge cio' che blocca: il primo passo incompleto, oppure il
    # profilo se il blocco e' la fatturazione o l'approvazione.
    passo = percorso.passo_da_riprendere(richiesta)
    return render(request, 'consulti/percorso/riepilogo.html', {
        'richiesta': richiesta, 'paziente': richiesta.paziente, 'passi': percorso.indicatore(4, richiesta),
        'prezzo': prezzo, 'motivo_blocco': motivo,
        'url_correggi': percorso.url_passo(richiesta, passo) if motivo and passo < 4 else None,
        'allegati': _allegati_in_ordine(richiesta),
        'ore_risposta': regole.ore_risposta(richiesta) if richiesta.refertatore_id else None,
    })
