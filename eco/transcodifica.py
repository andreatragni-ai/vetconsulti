"""
Transcodifica delle clip eco in MP4 H.264 leggero.

Le clip escono dall'ecografo in formati e pesi disparati (AVI non compressi
da centinaia di MB, DICOM multiframe). Il refertatore le deve aprire nel
browser: serve un MP4 H.264 a bitrate contenuto.

ffmpeg puo' non esserci (sul Mac di sviluppo non c'e'): in quel caso si
logga un avviso e l'allegato resta CARICATO, che vuol dire «originale
disponibile, versione leggera no». Non e' un errore: il consulto va avanti
lo stesso con il file originale.
"""

import logging
import os
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File

from consulti.models import StatoAllegato

logger = logging.getLogger('eco')


def ffmpeg_disponibile():
    binario = getattr(settings, 'FFMPEG_BIN', 'ffmpeg')
    return shutil.which(binario) is not None or os.path.isfile(binario)


def transcodifica(allegato):
    """Sostituisce il file dell'allegato con un MP4 leggero. Ritorna True se
    l'ha fatto, False se ffmpeg manca o ha fallito (stato invariato)."""
    binario = getattr(settings, 'FFMPEG_BIN', 'ffmpeg')
    if not ffmpeg_disponibile():
        logger.warning('ffmpeg non trovato (%s): allegato %s lasciato CARICATO.', binario, allegato.pk)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        sorgente = os.path.join(tmp, 'sorgente')
        with allegato.file.open('rb') as fin, open(sorgente, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
        destinazione = os.path.join(tmp, 'clip.mp4')
        comando = [
            binario, '-y', '-i', sorgente,
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '26',
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',  # H.264 vuole lati pari
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-an',
            destinazione,
        ]
        try:
            subprocess.run(comando, check=True, capture_output=True, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning('Transcodifica fallita per allegato %s: %s', allegato.pk, e)
            return False

        nome = os.path.splitext(os.path.basename(allegato.file.name))[0] + '.mp4'
        with open(destinazione, 'rb') as f:
            allegato.file.save(nome, File(f), save=False)
        allegato.dimensione = os.path.getsize(destinazione)
        allegato.mime = 'video/mp4'
        allegato.stato = StatoAllegato.TRANSCODIFICATO
        allegato.save(update_fields=['file', 'dimensione', 'mime', 'stato'])
        allegato.richiesta.registra('ALLEGATO_TRANSCODIFICATO', None, allegato=allegato.pk)
        return True
