"""
Il caricamento dei file nel passo «Carica gli esami» della richiesta guidata.

## Chi carica non sceglie la categoria

Il vecchio modulo chiedeva «categoria + file»: una tendina di sigle che il
collega non ha motivo di conoscere, e per l'eco nessun modo di dire a quale
proiezione corrisponde un'immagine (quindi un'eco non si poteva inviare).
Qui ogni zona di caricamento ha uno `slot` (cosa ci va: il tracciato, il
referto dell'ecografo, una proiezione del catalogo) e la categoria si
deduce da slot + tipo di file: un PDF nello slot ECG e' ECG_PDF, una foto
e' ECG_IMMAGINE; in una riga di proiezione un filmato e' ECO_CLIP e
un'immagine ECO_STATICA, e nasce anche la ProiezioneCaricata che la lega al
catalogo. Un file che non c'entra (un .docx come tracciato) si rifiuta con
una frase che dice cosa serve.

## Una riga = un file

Ogni zona riceve un file solo e per cambiarlo si usa «Sostituisci»; fa
eccezione il tracciato ECG (si aggiungono pagine o derivazioni). I filmati
liberi eco (righe `libera` del catalogo) vogliono in piu' la nota «cosa
mostra / cosa chiedi», obbligatoria. Una riga di proiezione
accetta cio' che il catalogo si aspetta (`tipo_media`): filmato, immagine o
entrambi; un DICOM prende la categoria della riga. Le clip hanno un limite
di peso (ECO_CLIP_MAX_BYTE): la durata (una decina di secondi) senza ffmpeg
non si misura, quindi si scrive nelle istruzioni e si frena sul peso.

## Due strade, una regola

Lo stesso `allega()` serve la POST semplice (`views.carica_allegato`) e la
fine del caricamento a pezzi (`views.upload_concludi`): cambia solo da dove
arriva il file, non cosa diventa.

## Sostituire e rimuovere

«Sostituisci» carica il nuovo file e poi rimuove il vecchio, nella stessa
transazione: la riga non resta mai vuota a meta'. Rimuovere un allegato
toglie anche la sua ProiezioneCaricata. Entrambe le cose lasciano l'audit.

## La cartella intera (eco)

La zona unica in cima al passo 3 dell'eco (`SLOT_CARTELLA`) riceve tutti i
file dell'esame. La categoria viene dal tipo di file (filmato ECO_CLIP,
immagine ECO_STATICA, DICOM ECO_CLIP finche' non trova la sua riga); un PDF
entra come ALTRO e diventa il referto dell'ecografo solo quando chi carica
conferma lo smistamento. Nessuna ProiezioneCaricata: ogni file nasce «da
smistare» (eco/smistamento/tavolo.py) e lo smistamento automatico propone
dove va. Lo stesso file (stessa impronta) caricato due volte non si duplica.

## Anteprime

Ogni zona accetta, insieme al file, la miniatura fatta dal browser
(`anteprima`); se manca e il file e' un'immagine la fa il server
(consulti/anteprime.py).

## Transcodifica

Una clip eco appena caricata passa a `eco.transcodifica` dopo il commit, in
un thread a parte (puo' durare minuti). Senza ffmpeg la transcodifica
logga un avviso e l'allegato resta com'e': il collega vede l'originale.
"""

import hashlib
import logging
import mimetypes
import os
import threading

from django.conf import settings
from django.db import transaction

from core.tipi import TipoEsame
from .models import Allegato, CategoriaAllegato

logger = logging.getLogger('consulti')

SLOT_ECG = 'ecg'
SLOT_HOLTER_REFERTO = 'holter_referto'
SLOT_HOLTER_FILE = 'holter_file'
SLOT_ECO_REFERTO = 'eco_referto'
SLOT_PROIEZIONE = 'proiezione'
SLOT_CARTELLA = 'cartella'

SLOT_PER_TIPO = {
    TipoEsame.ECG: (SLOT_ECG,),
    TipoEsame.HOLTER: (SLOT_HOLTER_REFERTO, SLOT_HOLTER_FILE),
    TipoEsame.ECO: (SLOT_ECO_REFERTO, SLOT_PROIEZIONE, SLOT_CARTELLA),
}

# Categorie che ogni slot mostra: servono al passo 3 per sapere quali file
# stanno in quale zona (e quali restano "altri file").
CATEGORIE_PER_SLOT = {
    SLOT_ECG: (CategoriaAllegato.ECG_PDF, CategoriaAllegato.ECG_IMMAGINE),
    SLOT_HOLTER_REFERTO: (CategoriaAllegato.HOLTER_REFERTO,),
    SLOT_HOLTER_FILE: (CategoriaAllegato.HOLTER_FILE,),
    SLOT_ECO_REFERTO: (CategoriaAllegato.ECO_REFERTO_PDF,),
}

# Zone con un file solo (per cambiarlo si sostituisce). Il tracciato ECG no:
# si possono aggiungere altre pagine o derivazioni.
SLOT_UNICI = (SLOT_HOLTER_REFERTO, SLOT_HOLTER_FILE, SLOT_ECO_REFERTO)

ESTENSIONI_IMMAGINE = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tif', '.tiff', '.heic', '.heif'}
ESTENSIONI_VIDEO = {'.mp4', '.m4v', '.mov', '.avi', '.webm', '.mkv', '.wmv', '.mpg', '.mpeg', '.ogv'}
ESTENSIONI_DICOM = {'.dcm', '.dicom'}

# Cosa accetta il selettore file di ogni zona (attributo accept): e' solo un
# aiuto, la regola vera e' categoria_per().
ACCETTA = {
    SLOT_ECG: '.pdf,image/*',
    SLOT_HOLTER_REFERTO: '.pdf,application/pdf',
    SLOT_HOLTER_FILE: '',
    SLOT_ECO_REFERTO: '.pdf,application/pdf',
    SLOT_PROIEZIONE: 'video/*,image/*,.dcm,.avi,.mov,.mkv,.wmv',
    SLOT_CARTELLA: '.pdf,application/pdf,video/*,image/*,.dcm,.avi,.mov,.mkv,.wmv',
}
ACCETTA_CLIP = 'video/*,.mp4,.mov,.avi,.mkv,.wmv,.dcm'
ACCETTA_STATICA = 'image/*,.dcm'


def accetta_per(proiezione):
    """L'attributo accept del selettore file di una riga di proiezione."""
    from eco.models import TipoMedia
    if proiezione.tipo_media == TipoMedia.CLIP:
        return ACCETTA_CLIP
    if proiezione.tipo_media == TipoMedia.STATICA:
        return ACCETTA_STATICA
    return ACCETTA[SLOT_PROIEZIONE]


class CaricamentoNonValido(Exception):
    """Il messaggio e' pensato per l'utente."""


class GiaCaricato(CaricamentoNonValido):
    """Lo stesso file (stessa impronta) e' gia' nella richiesta: dalla
    cartella non si duplica. Non e' un errore per chi carica."""


def genere_file(nome, mime=''):
    """'pdf', 'immagine', 'video', 'dicom' o 'altro'. Prima l'estensione
    (i browser dichiarano MIME diversi per lo stesso file), poi il MIME."""
    ext = os.path.splitext(nome or '')[1].lower()
    mime = (mime or mimetypes.guess_type(nome or '')[0] or '').lower()
    if ext == '.pdf' or mime == 'application/pdf':
        return 'pdf'
    if ext in ESTENSIONI_DICOM or mime == 'application/dicom':
        return 'dicom'
    if ext in ESTENSIONI_VIDEO or mime.startswith('video/'):
        return 'video'
    if ext in ESTENSIONI_IMMAGINE or mime.startswith('image/'):
        return 'immagine'
    return 'altro'


def _mb(byte):
    return f'{byte / (1024 * 1024):.0f}'


def categoria_per(slot, nome, mime='', proiezione=None):
    """La categoria dell'allegato per un file caricato in quello slot, o
    CaricamentoNonValido con la frase che dice cosa serve. Per le proiezioni
    conta anche cosa si aspetta la riga (`tipo_media`): un filmato in una
    riga «immagine» si rifiuta. Un DICOM prende la categoria della riga."""
    genere = genere_file(nome, mime)
    nome_breve = os.path.basename(nome or '') or 'il file'
    if slot == SLOT_ECG:
        if genere == 'pdf':
            return CategoriaAllegato.ECG_PDF
        if genere == 'immagine':
            return CategoriaAllegato.ECG_IMMAGINE
        raise CaricamentoNonValido(
            f'Il tracciato va caricato come PDF o come foto (JPG, PNG): «{nome_breve}» non e\' ne\' l\'uno '
            f'ne\' l\'altro.')
    if slot == SLOT_HOLTER_REFERTO:
        if genere == 'pdf':
            return CategoriaAllegato.HOLTER_REFERTO
        raise CaricamentoNonValido(
            f'Il referto del software Holter va caricato in PDF: «{nome_breve}» non lo e\'. '
            f'Il file dell\'apparecchio va nella zona qui sotto.')
    if slot == SLOT_HOLTER_FILE:
        return CategoriaAllegato.HOLTER_FILE
    if slot == SLOT_ECO_REFERTO:
        if genere == 'pdf':
            return CategoriaAllegato.ECO_REFERTO_PDF
        raise CaricamentoNonValido(
            f'Il referto dell\'ecografo va caricato in PDF: «{nome_breve}» non lo e\'. '
            f'Filmati e immagini vanno nelle righe delle proiezioni.')
    if slot == SLOT_CARTELLA:
        if genere == 'pdf':
            return CategoriaAllegato.ALTRO
        if genere in ('video', 'dicom'):
            return CategoriaAllegato.ECO_CLIP
        if genere == 'immagine':
            return CategoriaAllegato.ECO_STATICA
        raise CaricamentoNonValido(
            f'«{nome_breve}» non e\' un file dell\'esame: servono il referto in PDF, i filmati e le immagini.')
    if slot == SLOT_PROIEZIONE:
        from eco.models import TipoMedia
        media = proiezione.tipo_media if proiezione is not None else TipoMedia.ENTRAMBI
        vuole_clip = media in (TipoMedia.CLIP, TipoMedia.ENTRAMBI)
        vuole_statica = media in (TipoMedia.STATICA, TipoMedia.ENTRAMBI)
        if genere == 'video' and vuole_clip:
            return CategoriaAllegato.ECO_CLIP
        if genere == 'immagine' and vuole_statica:
            return CategoriaAllegato.ECO_STATICA
        if genere == 'dicom':
            return CategoriaAllegato.ECO_CLIP if vuole_clip else CategoriaAllegato.ECO_STATICA
        if genere == 'immagine':
            raise CaricamentoNonValido(
                f'In questa riga va un filmato (MP4, AVI, MOV o DICOM): «{nome_breve}» e\' un\'immagine.')
        if genere == 'video':
            raise CaricamentoNonValido(
                f'In questa riga va un\'immagine (JPG, PNG o DICOM): «{nome_breve}» e\' un filmato.')
        raise CaricamentoNonValido(
            f'Per una proiezione carica un filmato (MP4, AVI, MOV, DICOM) o un\'immagine (JPG, PNG): '
            f'«{nome_breve}» non e\' ne\' l\'uno ne\' l\'altro.')
    raise CaricamentoNonValido('Zona di caricamento sconosciuta: ricarica la pagina e riprova.')


def _verifica(richiesta, slot, proiezione_id, sostituisci_id, nota=''):
    """Controlla slot, proiezione, posto libero nella riga e allegato da
    sostituire prima di toccare lo storage. Ritorna (proiezione, vecchio)."""
    if slot not in SLOT_PER_TIPO.get(richiesta.tipo_esame, ()):
        raise CaricamentoNonValido(
            f'Questa zona non c\'entra con {richiesta.get_tipo_esame_display().lower()}: '
            f'ricarica la pagina e riprova.')
    proiezione = None
    if slot == SLOT_PROIEZIONE:
        from eco.models import ProiezioneCatalogo
        proiezione = ProiezioneCatalogo.objects.filter(pk=proiezione_id or None, attiva=True).first()
        if proiezione is None:
            raise CaricamentoNonValido('Proiezione non trovata nel catalogo: ricarica la pagina e riprova.')
    vecchio = None
    if sostituisci_id:
        vecchio = richiesta.allegati.filter(pk=sostituisci_id).first()
        if vecchio is None:
            raise CaricamentoNonValido('Il file da sostituire non c\'e\' piu\': ricarica la pagina.')
        return proiezione, vecchio
    # Una riga = un file (il tracciato ECG quanti se ne vuole): per cambiarlo
    # si usa «Sostituisci».
    if proiezione is not None:
        if richiesta.proiezioni.filter(proiezione=proiezione).exists():
            raise CaricamentoNonValido(
                f'«{proiezione.nome}» ha gia\' il suo file: per cambiarlo usa «Sostituisci».')
        if proiezione.libera and not (nota or '').strip():
            raise CaricamentoNonValido('Scrivi in breve cosa mostra il filmato o cosa chiedi al collega.')
    elif slot in SLOT_UNICI and richiesta.allegati.filter(categoria__in=CATEGORIE_PER_SLOT[slot]).exists():
        raise CaricamentoNonValido('Qui c\'e\' gia\' un file: per cambiarlo usa «Sostituisci».')
    return proiezione, vecchio


def _verifica_dimensione(categoria, dimensione):
    if categoria == CategoriaAllegato.ECO_CLIP and dimensione and dimensione > settings.ECO_CLIP_MAX_BYTE:
        raise CaricamentoNonValido(
            f'Il filmato pesa {_mb(dimensione)} MB: il limite per una clip e\' {_mb(settings.ECO_CLIP_MAX_BYTE)} MB. '
            f'Esporta dall\'ecografo un filmato piu\' breve (una decina di secondi basta) o in MP4.')


def _verifica_doppione(richiesta, slot, impronta, nome):
    if slot == SLOT_CARTELLA and impronta and richiesta.allegati.filter(sha256=impronta).exists():
        raise GiaCaricato(f'«{os.path.basename(nome or "")}» c\'e\' gia\'.')


def _impronta(file_obj):
    digest = hashlib.sha256()
    for blocco in file_obj.chunks():
        digest.update(blocco)
    file_obj.seek(0)
    return digest.hexdigest()


def controlla(richiesta, slot, nome, mime='', *, proiezione_id=None, sostituisci_id=None, dimensione=None,
              nota='', impronta=None):
    """Tutti i controlli di `allega` senza scrivere nulla: il caricamento a
    pezzi lo chiama prima di mandare il primo byte. Ritorna la categoria."""
    proiezione, _vecchio = _verifica(richiesta, slot, proiezione_id, sostituisci_id, nota)
    categoria = categoria_per(slot, nome, mime, proiezione)
    _verifica_dimensione(categoria, dimensione)
    _verifica_doppione(richiesta, slot, impronta, nome)
    return categoria


def allega(richiesta, file_obj, nome, slot, utente, *, proiezione_id=None, sostituisci_id=None,
           mime='', impronta=None, nota='', anteprima=None, percorso='', modificato_il=None, **dettaglio_audit):
    """Crea l'allegato dello slot (e la ProiezioneCaricata, se lo slot e' una
    proiezione), sostituendo un allegato esistente se richiesto. Solleva
    CaricamentoNonValido prima di scrivere qualsiasi cosa. `nota` e' il
    «cosa mostra / cosa chiedi» del filmato libero; sostituendo senza nota
    nuova resta quella di prima. `anteprima`: la miniatura del browser
    (facoltativa). `percorso` e `modificato_il` (ms): da dove viene il file
    nella cartella caricata, per l'ordine di acquisizione dello smistamento."""
    proiezione, vecchio = _verifica(richiesta, slot, proiezione_id, sostituisci_id, nota)
    categoria = categoria_per(slot, nome, mime, proiezione)
    _verifica_dimensione(categoria, getattr(file_obj, 'size', None))
    if slot == SLOT_CARTELLA:
        if impronta is None:
            impronta = _impronta(file_obj)
        _verifica_doppione(richiesta, slot, impronta, nome)
    nota = (nota or '').strip()[:200]
    if not nota and vecchio is not None and proiezione is not None:
        nota = vecchio.proiezioni.filter(proiezione=proiezione).values_list('nota', flat=True).first() or ''
    with transaction.atomic():
        if proiezione is not None:
            dettaglio_audit['proiezione'] = proiezione.nome
        allegato = Allegato.da_upload(richiesta, file_obj, categoria, utente, nome=nome, mime=mime,
                                      impronta=impronta, **dettaglio_audit)
        if proiezione is not None:
            from eco.models import ProiezioneCaricata
            ProiezioneCaricata.objects.create(richiesta=richiesta, proiezione=proiezione, allegato=allegato,
                                              nota=nota)
        if vecchio is not None:
            rimuovi(vecchio, utente, sostituito_da=allegato.id)
        if slot == SLOT_CARTELLA:
            from eco.smistamento.tavolo import registra_da_cartella
            registra_da_cartella(allegato, percorso or nome, modificato_il)
        _anteprima(allegato, anteprima)
        if categoria == CategoriaAllegato.ECO_CLIP:
            transaction.on_commit(lambda: pianifica_transcodifica(allegato.pk))
    return allegato


def _anteprima(allegato, file_anteprima):
    """La miniatura del browser se c'e' e va bene; per un'immagine, se no,
    quella fatta qui. Un'anteprima che non riesce non ferma il caricamento."""
    from . import anteprime
    if anteprime.da_upload(allegato, file_anteprima):
        return
    if genere_file(allegato.nome_originale, allegato.mime) == 'immagine':
        anteprime.assicura(allegato)


def rimuovi(allegato, utente, **dettaglio_audit):
    """Toglie l'allegato, la sua ProiezioneCaricata e il file; lascia l'audit."""
    richiesta = allegato.richiesta
    nome, pk = allegato.nome_originale, allegato.pk
    allegato.proiezioni.all().delete()
    if allegato.anteprima:
        allegato.anteprima.delete(save=False)
    if allegato.file:
        allegato.file.delete(save=False)
    allegato.delete()
    richiesta.registra('ALLEGATO_ELIMINATO', utente, allegato=pk, nome=nome, **dettaglio_audit)
    return nome


def pianifica_transcodifica(allegato_id):
    """La transcodifica di una clip, dopo il commit. Senza ffmpeg si chiama
    direttamente (logga l'avviso e torna subito); con ffmpeg gira in un
    thread, perche' una clip grande impiega minuti e la pagina non aspetta."""
    from eco import transcodifica

    def lavoro():
        from django.db import connection
        try:
            allegato = Allegato.objects.select_related('richiesta').filter(pk=allegato_id).first()
            if allegato is not None:
                transcodifica.transcodifica(allegato)
                # Il browser non ha saputo fare la miniatura (AVI, WMV...): la fa ffmpeg.
                from . import anteprime
                anteprime.assicura(allegato)
        except Exception:
            logger.exception('Transcodifica dell\'allegato %s non riuscita.', allegato_id)
        finally:
            connection.close()

    if not transcodifica.ffmpeg_disponibile():
        allegato = Allegato.objects.filter(pk=allegato_id).first()
        if allegato is not None:
            transcodifica.transcodifica(allegato)
        return None
    filo = threading.Thread(target=lavoro, name=f'transcodifica-{allegato_id}', daemon=True)
    filo.start()
    return filo
