"""
Caricamento a pezzi dei file grandi, con ripresa dopo interruzione.

## Perche' non basta una POST

Un Holter di 24 ore sta fra 50 e 300 MB, e una clip eco non e' da meno. Su
una linea d'ambulatorio una POST singola di quella taglia impiega minuti, e
se cade a meta' ricomincia da capo — non una volta, tutte le volte, perche'
la linea che l'ha fatta cadere e' sempre quella. Chi carica smette di
caricare.

## Come funziona

Il client spezza il file e manda un pezzo per volta, dicendo a quale offset
sta. Il server appende in un file di appoggio e risponde con quanti byte ha.
Se la connessione cade, il client richiede lo stato e riparte da li'.

L'identita' del trasferimento e' l'impronta SHA-256 del file intero, che il
client calcola prima di cominciare: due caricamenti dello stesso file sono lo
stesso trasferimento, e riprenderlo e' gratis. A fine corsa l'impronta si
verifica su cio' che e' arrivato — e' l'unico modo per sapere che il file e'
quello, e non i pezzi giusti nell'ordine sbagliato.

## Cosa NON fa

Non legge il file. I formati Holter proprietari non sono documentati, e un
parser scritto a naso sbaglierebbe in silenzio proprio sui conteggi. Si
conserva e si riscarica; i numeri li mette chi ha guardato il tracciato.

Portato da VetCardio (consulto/upload_chunk.py) con due sole differenze: il
limite viene da UPLOAD_MAX_BYTE e la cartella d'appoggio e'
`caricamenti_parziali/` sotto MEDIA_ROOT.
"""

import hashlib
import re
from pathlib import Path

from django.conf import settings

# Un'impronta e' 64 caratteri esadecimali. Non si costruisce mai un percorso
# con qualcosa che arriva dalla rete senza averlo prima ridotto a questo.
IMPRONTA_VALIDA = re.compile(r'^[0-9a-f]{64}$')

MAX_BYTE_DEFAULT = 300 * 1024 * 1024


class UploadNonValido(Exception):
    """Il messaggio e' pensato per l'utente."""


def max_byte():
    return getattr(settings, 'UPLOAD_MAX_BYTE', MAX_BYTE_DEFAULT)


def _cartella():
    percorso = Path(settings.MEDIA_ROOT) / 'caricamenti_parziali'
    percorso.mkdir(parents=True, exist_ok=True)
    return percorso


def _appoggio(impronta):
    if not IMPRONTA_VALIDA.match(impronta or ''):
        raise UploadNonValido('Identificativo del trasferimento non valido.')
    return _cartella() / f'{impronta}.parziale'


def quanto_ho(impronta):
    """Byte gia' ricevuti per questo trasferimento. 0 se non ne so nulla."""
    percorso = _appoggio(impronta)
    return percorso.stat().st_size if percorso.exists() else 0


def ricevi_pezzo(impronta, offset, dati):
    """Appende un pezzo. Torna i byte totali ricevuti finora.

    L'offset non e' un suggerimento: se non combacia con quanto c'e' gia', il
    pezzo si rifiuta invece di scriverlo dove capita. Un file assemblato con
    un buco in mezzo supererebbe ogni controllo di dimensione e fallirebbe
    solo all'impronta, dopo aver fatto ricaricare tutto.
    """
    percorso = _appoggio(impronta)
    presenti = percorso.stat().st_size if percorso.exists() else 0

    if offset != presenti:
        raise UploadNonValido(
            f'Pezzo fuori sequenza: ne ho {presenti} byte, questo parte da {offset}.')
    if presenti + len(dati) > max_byte():
        raise UploadNonValido(
            f'Il file supera il limite di {max_byte() // (1024 * 1024)} MB.')

    with open(percorso, 'ab') as f:
        f.write(dati)
    return percorso.stat().st_size


def concludi(impronta):
    """Verifica l'impronta e torna il percorso del file completo.

    Se non combacia, il file di appoggio si cancella: tenere in giro un
    trasferimento corrotto vuol dire che al prossimo tentativo `quanto_ho`
    direbbe di riprendere da una base sbagliata.
    """
    percorso = _appoggio(impronta)
    if not percorso.exists():
        raise UploadNonValido('Nessun trasferimento da concludere.')

    digest = hashlib.sha256()
    with open(percorso, 'rb') as f:
        for blocco in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(blocco)

    if digest.hexdigest() != impronta:
        percorso.unlink(missing_ok=True)
        raise UploadNonValido(
            'Il file arrivato non corrisponde a quello di partenza. '
            'Riprova: il caricamento riparte da zero.')
    return percorso


def abbandona(impronta):
    _appoggio(impronta).unlink(missing_ok=True)
