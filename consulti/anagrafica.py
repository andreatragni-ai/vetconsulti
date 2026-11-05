"""
L'archivio pazienti: ritrovare Luna senza riscriverla (05/11/2026).

Il modello e' `PazienteArchivio` (consulti/models.py), che ne spiega la
forma; qui c'e' cio' che se ne fa:

- `archivio_di` e `cerca`: lo scope. L'archivio e' della **clinica** (di
  chi chiede, se e' un libero professionista): nessun'altra query deve
  filtrare a mano, o un giorno un filtro dimenticato mostrera' i pazienti
  di un'altra clinica.
- `registra`: l'aggiornamento, chiamato da `Richiesta.invia()`. L'archivio
  si riempie da solo dai casi inviati, non da una pagina «nuovo paziente».
- `casi_del_paziente` e `puo_leggere_per_storico`: lo storico.

## Cosa si precompila e cosa no

Nome, specie, razza, sesso, data di nascita e cognome del proprietario:
sono gli stessi fra un esame e l'altro. **Il peso no**, mai: cambia, ed e'
il denominatore degli indici normalizzati del referto. Nemmeno l'eta' in
anni, se e' stata scritta piu' di `MESI_ETA_FRESCA` mesi fa: «8 anni» di
due anni fa e' una bugia, e la pagina lo dice invece di riempire il campo.

## Lo storico attraversa i colleghi (deciso con Andre il 05/11/2026)

`casi_del_paziente` ritorna tutti i casi di quel paziente, compresi quelli
aperti da un altro collega della clinica e quelli refertati da un altro
esperto: e' il punto dell'anagrafica (sapere che a marzo Luna aveva gia'
un'eco). Chi puo' APRIRE quei casi non cambia: gli elenchi restano per
utente, e l'unica eccezione ai permessi e' `puo_leggere_per_storico`, che
lascia l'esperto assegnato leggere il PDF dei referti firmati dello stesso
paziente — con un ACCESSO_STORICO nell'audit del caso che ha letto.
"""

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from .models import PazienteArchivio, Richiesta, StatoRichiesta
from .nomi import chiave_archivio

# Oltre questi mesi l'eta' in anni non si precompila piu': si richiede.
MESI_ETA_FRESCA = 6
GIORNI_ETA_FRESCA = MESI_ETA_FRESCA * 30


# ── Lo scope: di chi e' l'archivio ──────────────────────────────────────────

def archivio_di(richiedente):
    """Le voci che `richiedente` puo' vedere e aggiornare: quelle della sua
    clinica, oppure le sue se e' un libero professionista."""
    if richiedente is None:
        return PazienteArchivio.objects.none()
    if richiedente.clinica_id:
        return PazienteArchivio.objects.filter(clinica_id=richiedente.clinica_id)
    return PazienteArchivio.objects.filter(clinica__isnull=True, richiedente=richiedente)


def voce(richiedente, pk):
    """La voce `pk` se e' nell'archivio di `richiedente`, altrimenti None:
    l'unico modo di passare da un id dell'URL a una voce."""
    if not pk:
        return None
    return archivio_di(richiedente).filter(pk=pk).first()


def cerca(richiedente, testo, limite=8):
    """I pazienti il cui nome o il cui proprietario contiene `testo` (da due
    lettere), i piu' recenti per primi."""
    testo = (testo or '').strip()
    if len(testo) < 2:
        return PazienteArchivio.objects.none()
    trovati = archivio_di(richiedente).filter(
        models.Q(nome__icontains=testo) | models.Q(cognome_proprietario__icontains=testo))
    return trovati.order_by(models.F('visto_il').desc(nulls_last=True), 'nome')[:limite]


# ── L'eta': fresca o da richiedere ─────────────────────────────────────────

def eta_fresca(voce_archivio, oggi=None):
    """Vero se l'eta' in anni della voce si puo' ancora precompilare."""
    if not (voce_archivio and voce_archivio.eta_testo and voce_archivio.eta_dal):
        return False
    oggi = oggi or timezone.localdate()
    return (oggi - voce_archivio.eta_dal).days <= GIORNI_ETA_FRESCA


# ── L'aggiornamento: lo fa l'invio ─────────────────────────────────────────

def registra(richiesta):
    """Porta in archivio il paziente di una richiesta appena inviata e lega
    la fotografia alla voce. Ritorna la voce (None se la richiesta non ha
    un paziente o non ha un richiedente con uno scope).

    L'ultimo invio vince: i campi della voce diventano quelli del caso, cosi'
    una razza corretta a mano resta corretta anche la volta dopo. Se il nome
    non combacia piu' con la voce legata (il collega ha scritto un altro
    animale sopra una bozza precompilata) il legame si rifa' da zero.
    """
    paziente = getattr(richiesta, 'paziente', None)
    richiedente = richiesta.richiedente
    if paziente is None or richiedente is None:
        return None
    chiave = chiave_archivio(paziente.nome, paziente.specie, paziente.cognome_proprietario)
    trovata = paziente.archivio
    if trovata is not None and trovata.chiave != chiave:
        trovata = None
    if trovata is None:
        trovata = archivio_di(richiedente).filter(chiave=chiave).first()
    if trovata is None:
        trovata = PazienteArchivio(clinica=richiedente.clinica, richiedente=richiedente)

    trovata.nome = paziente.nome
    trovata.specie = paziente.specie
    trovata.razza = paziente.razza
    trovata.sesso = paziente.sesso
    trovata.data_nascita = paziente.data_nascita
    trovata.cognome_proprietario = paziente.cognome_proprietario
    # `eta_dal` si muove solo quando l'eta' CAMBIA: rinviare un caso con la
    # stessa eta' precompilata non la rende di nuovo fresca.
    if paziente.eta_testo != trovata.eta_testo or (paziente.eta_testo and not trovata.eta_dal):
        trovata.eta_dal = timezone.localdate() if paziente.eta_testo else None
    trovata.eta_testo = paziente.eta_testo
    trovata.visto_il = richiesta.inviata_il or timezone.now()
    try:
        with transaction.atomic():
            trovata.save()
    except IntegrityError:
        # Due colleghi hanno inviato lo stesso paziente nello stesso istante:
        # vince chi e' arrivato primo, questo caso si aggancia alla sua voce.
        trovata = archivio_di(richiedente).get(chiave=chiave)
    if paziente.archivio_id != trovata.pk:
        paziente.archivio = trovata
        paziente.save(update_fields=['archivio'])
    return trovata


# ── Lo storico ─────────────────────────────────────────────────────────────

def casi_del_paziente(voce_archivio, escludi=None):
    """I casi (mai le bozze) di quel paziente, dal piu' recente. Attraversa
    i colleghi della clinica e gli esperti: vedere che c'e' un'eco di marzo
    e' il motivo per cui l'anagrafica esiste."""
    if voce_archivio is None:
        return Richiesta.objects.none()
    casi = (Richiesta.objects.filter(paziente__archivio=voce_archivio)
            .exclude(stato=StatoRichiesta.BOZZA)
            .select_related('paziente', 'refertatore__user', 'richiedente__user', 'referto')
            .order_by(models.F('inviata_il').desc(nulls_last=True)))
    if escludi is not None and escludi.pk:
        casi = casi.exclude(pk=escludi.pk)
    return casi


def altri_casi(richiesta):
    """Lo storico da mostrare sulla pagina di un caso: gli altri casi dello
    stesso paziente."""
    paziente = getattr(richiesta, 'paziente', None)
    return casi_del_paziente(paziente.archivio if paziente else None, escludi=richiesta)


def puo_leggere_per_storico(utente, richiesta):
    """L'eccezione ai permessi: l'esperto assegnato a un ALTRO caso dello
    stesso paziente puo' leggere i referti firmati di questo. Serve a chi
    referta oggi l'eco di Luna per vedere l'ECG di marzo di un collega.
    Non apre la pagina del caso ne' gli allegati: solo il PDF firmato
    (referti/views.py), e lascia un ACCESSO_STORICO nell'audit."""
    ref = getattr(utente, 'refertatore', None)
    paziente = getattr(richiesta, 'paziente', None)
    archivio_id = getattr(paziente, 'archivio_id', None)
    if ref is None or not archivio_id:
        return False
    return (Richiesta.objects.filter(paziente__archivio_id=archivio_id, refertatore=ref)
            .exclude(pk=richiesta.pk).exists())


def storico_per(utente, richiesta, limite=10):
    """Le righe dello storico da mostrare a `utente` sulla pagina di
    `richiesta`: [{caso, url, url_pdf}].

    `url` c'e' solo per i casi che quell'utente puo' aprire davvero (i suoi,
    o quelli che referta; lo staff tutti): un caso del collega si vede nella
    riga ma non si apre, perche' gli elenchi restano per utente. `url_pdf`
    c'e' quando il referto e' firmato e lo puo' leggere — e' li' che passa
    l'eccezione di `puo_leggere_per_storico`."""
    from django.urls import reverse

    from .permessi import e_refertatore_assegnato, e_richiedente, puo_leggere_referto

    righe = []
    for caso in casi_del_paziente(getattr(getattr(richiesta, 'paziente', None), 'archivio', None),
                                  escludi=richiesta)[:limite]:
        url = None
        if e_refertatore_assegnato(utente, caso):
            url = reverse('referti:refertazione', args=[caso.pk])
        elif e_richiedente(utente, caso) or utente.is_staff:
            url = reverse('consulti:dettaglio', args=[caso.pk])
        referto = getattr(caso, 'referto', None)
        url_pdf = (reverse('referti:stampa', args=[referto.pk])
                   if referto is not None and referto.firmato and puo_leggere_referto(utente, caso) else None)
        righe.append({'caso': caso, 'url': url, 'url_pdf': url_pdf})
    return righe
