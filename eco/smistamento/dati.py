"""
Le strutture dati dello smistamento: niente Django qui dentro, cosi' il
motore (motore.py) si prova con dati finti e il comando di valutazione lo
usa tale e quale sulle immagini del banco di prova.
"""

from dataclasses import dataclass, field

# Tipi di tracciato, come li chiede la lettura AI e come si derivano dal nome
# della riga del catalogo (righe.tracciato_di).
BIDIMENSIONALE = '2D'
M_MODE = 'M'
PULSATO = 'PW'
CONTINUO = 'CW'
TDI = 'TDI'
TRACCIATI = (BIDIMENSIONALE, M_MODE, PULSATO, CONTINUO, TDI)
NOMI_TRACCIATO = {BIDIMENSIONALE: 'bidimensionale', M_MODE: 'M-mode', PULSATO: 'Doppler pulsato',
                  CONTINUO: 'Doppler continuo', TDI: 'TDI'}

# Colore dai pixel (colore.py).
COLOR = 'color'
BMODE = 'bmode'
INCERTO = 'incerto'

# Confidenza della lettura AI, dalle tre parole alla scala del motore.
CONFIDENZA = {'alta': 0.9, 'media': 0.65, 'bassa': 0.35}
# Da qui in su una proposta e' «sicura» (bollino verde): solo lettura AI con
# confidenza alta, coerente con formato e pixel. Tutto il resto e' «da verificare».
SOGLIA_SICURA = 0.85


@dataclass(frozen=True)
class Riga:
    """Una riga del catalogo, per quanto serve allo smistamento. `ordine` e'
    la posizione nel protocollo (0, 1, 2...: l'ordine del passo 3 e del
    protocollo stampabile); `colore` vincola le righe filmato «— B-mode» e
    «— color Doppler» (None: nessun vincolo)."""

    id: int
    codice: str
    nome: str
    finestra: str
    tipo_media: str
    ordine: int
    libera: bool = False
    obbligatoria: bool = False
    deve_essere_visibile: str = ''
    tracciato: str = BIDIMENSIONALE
    colore: str | None = None


@dataclass
class FileEsame:
    """Un file caricato. `genere`: pdf, immagine, video, dicom, altro.
    `anteprima`: i byte JPEG della miniatura (None se non c'e').
    `percorso` e `modificato_il` (ms) servono all'ordine di acquisizione."""

    id: int
    nome: str
    genere: str
    anteprima: bytes | None = None
    percorso: str = ''
    modificato_il: int | None = None
    colore: str = ''
    frazione_colore: float | None = None


@dataclass
class Lettura:
    """Cio' che la lettura AI dice di una miniatura. `codice` None vuol dire
    «sconosciuto»: il modello non ha riconosciuto la riga."""

    codice: str | None
    seconda: str | None = None
    confidenza: str = 'bassa'
    tracciato: str = ''
    color_doppler: bool | None = None
    motivo: str = ''


@dataclass
class DaLeggere:
    """Un file da mandare alla lettura AI con le sole righe possibili per
    formato e pixel (codici)."""

    file_id: int
    anteprima: bytes
    genere: str
    candidati: list = field(default_factory=list)
    colore: str = ''


@dataclass
class Proposta:
    """Dove il motore propone di mettere un file."""

    file_id: int
    riga_id: int | None = None
    referto: bool = False
    confidenza: float | None = None
    sicura: bool = False
    fonte: str = ''
    motivo: str = ''
    seconda_id: int | None = None
    tracciato: str = ''
    colore: str = ''


@dataclass
class Risultato:
    proposte: list
    messaggio: str = ''
    lettura_ai: bool = False
    telemetria: dict = field(default_factory=dict)
    letture: dict = field(default_factory=dict)


class LetturaNonDisponibile(Exception):
    """La lettura AI non si puo' fare (chiave assente, libreria mancante,
    permesso negato...). Il messaggio e' per chi carica: lo smistamento si
    ferma a formato e pixel e il resto si fa a mano."""
