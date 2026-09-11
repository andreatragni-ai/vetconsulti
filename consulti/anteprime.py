"""
Le miniature degli allegati (Allegato.anteprima).

## Chi le fa

Di solito il **browser**, mentre carica: per un'immagine la riduce, per un
filmato che sa decodificare (MP4/MOV in H.264) prende un fotogramma verso
meta' durata con <video> + <canvas> (static/consulti/js/anteprime.js) e la
manda insieme al file. Qui la si **normalizza** sempre: la si riapre con
Pillow, la si riduce a 800 px sul lato lungo e la si risalva in JPEG. Un
file che Pillow non apre non diventa un'anteprima (e i metadati, EXIF
compresi, non passano).

Se il browser non l'ha mandata (niente JavaScript, formato che il browser
non decodifica) la fa il **server**: Pillow per le immagini, subito;
ffmpeg per i filmati (AVI, WMV...), se installato, a meta' durata. Senza
ffmpeg un filmato resta senza anteprima: lo smistamento non puo' leggerlo
e il collega lo mette a mano nella sua riga.

## Chi le vede

Le stesse persone che vedono il file: core.views_media.anteprima_allegato
usa puo_vedere_allegato. Mai statiche.
"""

import io
import logging
import os
import re
import shutil
import subprocess
import tempfile

from django.core.files.base import ContentFile

logger = logging.getLogger('consulti')

LATO_MAX = 800
QUALITA_JPEG = 82
# Una miniatura del browser pesa 30-150 KB: oltre questo non e' una miniatura.
MAX_BYTE_ANTEPRIMA = 3 * 1024 * 1024


class AnteprimaNonValida(Exception):
    pass


def jpeg_ridotto(sorgente, lato_max=LATO_MAX):
    """I byte di un JPEG ridotto da un file immagine (percorso o file-like).
    Solleva AnteprimaNonValida se Pillow non lo apre."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(sorgente) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert('RGB')
            im.thumbnail((lato_max, lato_max))
            uscita = io.BytesIO()
            im.save(uscita, 'JPEG', quality=QUALITA_JPEG, optimize=True)
            return uscita.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise AnteprimaNonValida(str(e)) from e


def salva(allegato, dati_jpeg):
    """Salva i byte JPEG come anteprima (sostituendo quella di prima)."""
    if allegato.anteprima:
        allegato.anteprima.delete(save=False)
    allegato.anteprima.save('anteprima.jpg', ContentFile(dati_jpeg), save=False)
    allegato.save(update_fields=['anteprima'])


def da_upload(allegato, file_anteprima):
    """L'anteprima mandata dal browser: normalizzata, o ignorata se non e'
    un'immagine (il file vero e' comunque caricato). Ritorna True se salvata."""
    if file_anteprima is None:
        return False
    if getattr(file_anteprima, 'size', 0) > MAX_BYTE_ANTEPRIMA:
        logger.warning('Anteprima troppo grande per l\'allegato %s: ignorata.', allegato.pk)
        return False
    try:
        salva(allegato, jpeg_ridotto(file_anteprima))
    except AnteprimaNonValida as e:
        logger.warning('Anteprima non valida per l\'allegato %s: %s', allegato.pk, e)
        return False
    return True


def _durata_secondi(binario, percorso):
    """La durata del filmato letta dall'intestazione che ffmpeg stampa."""
    try:
        esito = subprocess.run([binario, '-hide_banner', '-i', percorso], capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    trovato = re.search(rb'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', esito.stderr or b'')
    if not trovato:
        return None
    ore, minuti, secondi = trovato.groups()
    return int(ore) * 3600 + int(minuti) * 60 + float(secondi)


def da_filmato(allegato):
    """Fotogramma a meta' durata con ffmpeg. None se ffmpeg manca o fallisce."""
    from django.conf import settings
    from eco.transcodifica import ffmpeg_disponibile
    if not ffmpeg_disponibile():
        return None
    binario = getattr(settings, 'FFMPEG_BIN', 'ffmpeg')
    with tempfile.TemporaryDirectory() as tmp:
        sorgente = os.path.join(tmp, 'sorgente')
        with allegato.file.open('rb') as fin, open(sorgente, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
        durata = _durata_secondi(binario, sorgente)
        uscita = os.path.join(tmp, 'fotogramma.jpg')
        comando = [binario, '-y', '-hide_banner', '-loglevel', 'error']
        if durata:
            comando += ['-ss', f'{durata / 2:.2f}']
        comando += ['-i', sorgente, '-frames:v', '1', uscita]
        try:
            subprocess.run(comando, check=True, capture_output=True, timeout=120)
            return jpeg_ridotto(uscita)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, AnteprimaNonValida) as e:
            logger.warning('Fotogramma non estratto per l\'allegato %s: %s', allegato.pk, e)
            return None


def assicura(allegato):
    """Se l'allegato non ha l'anteprima prova a farla qui (Pillow o ffmpeg).
    Ritorna True se alla fine c'e'."""
    if allegato.anteprima:
        return True
    if not allegato.file:
        return False
    from .caricamento import genere_file
    genere = genere_file(allegato.nome_originale or allegato.file.name, allegato.mime)
    dati = None
    if genere == 'immagine':
        try:
            with allegato.file.open('rb') as f:
                dati = jpeg_ridotto(f)
        except (AnteprimaNonValida, OSError) as e:
            logger.info('Anteprima non fatta per l\'immagine %s: %s', allegato.pk, e)
    elif genere == 'video':
        dati = da_filmato(allegato)
    if dati is None:
        return False
    salva(allegato, dati)
    return True
