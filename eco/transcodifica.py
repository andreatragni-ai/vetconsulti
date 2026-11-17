"""
Transcodifica delle clip eco in MP4 H.264 leggero, e misura di cosa e'
arrivato.

Le clip escono dall'ecografo in formati e pesi disparati: il Mindray M9 di
Andre esporta **AVI con codec MP43** (prova del 17/11/2026 su tre clip
vere), che nessun browser apre — Chrome risponde «no» secco a
`video/x-msvideo`. Di Esaote e degli altri non sappiamo ancora niente:
`sonda` scrive nel log e sull'allegato il codec di ogni clip che arriva,
cosi' fra qualche caso lo sapremo invece di indovinarlo.

Il refertatore le deve aprire nel browser: serve un MP4 H.264 a bitrate
contenuto. Sulle clip del Mindray ffmpeg 6.1.1 ci mette tre secondi l'una e
le fa pesare cinque volte meno, senza perdere un fotogramma.

ffmpeg puo' non esserci (sul Mac di sviluppo non c'e'): in quel caso si
logga un avviso e l'allegato resta CARICATO, che vuol dire «originale
disponibile, versione leggera no». Non e' un errore: il consulto va avanti
lo stesso con il file originale.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File

from consulti.models import StatoAllegato

logger = logging.getLogger('eco')


def _binario():
    return getattr(settings, 'FFMPEG_BIN', 'ffmpeg')


def ffmpeg_disponibile():
    binario = _binario()
    return shutil.which(binario) is not None or os.path.isfile(binario)


def ffprobe_disponibile():
    """ffprobe sta nello stesso pacchetto di ffmpeg: si cerca accanto al
    binario configurato, cosi' FFMPEG_BIN=/usr/local/bin/ffmpeg trova
    /usr/local/bin/ffprobe senza una seconda impostazione."""
    binario = _binario()
    accanto = os.path.join(os.path.dirname(binario), 'ffprobe') if os.path.dirname(binario) else 'ffprobe'
    return shutil.which(accanto) or (os.path.isfile(accanto) and accanto) or None


def sonda(percorso):
    """Cosa c'e' dentro un filmato: {'codec', 'durata_s', 'larghezza',
    'altezza', 'fps'}. None se ffprobe non c'e' o non capisce il file — in
    sviluppo (sul Mac non c'e') e' il caso normale, e chi chiama tira
    dritto."""
    ffprobe = ffprobe_disponibile()
    if not ffprobe:
        return None
    comando = [ffprobe, '-v', 'error', '-select_streams', 'v:0',
               '-show_entries', 'stream=codec_name,width,height,avg_frame_rate:format=duration',
               '-of', 'json', str(percorso)]
    try:
        uscita = subprocess.run(comando, check=True, capture_output=True, timeout=60).stdout
        dati = json.loads(uscita or b'{}')
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as e:
        logger.warning('ffprobe non ha letto %s: %s', percorso, e)
        return None
    flussi = dati.get('streams') or [{}]
    flusso = flussi[0]
    durata = (dati.get('format') or {}).get('duration')
    fps = 0.0
    frazione = flusso.get('avg_frame_rate') or '0/0'
    try:
        num, _, den = frazione.partition('/')
        fps = round(float(num) / float(den), 1) if float(den or 0) else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0.0
    return {'codec': flusso.get('codec_name') or '', 'larghezza': flusso.get('width'),
            'altezza': flusso.get('height'), 'fps': fps,
            'durata_s': round(float(durata), 2) if durata else None}


def misura(allegato):
    """Scrive su `allegato` durata e codec del file com'e' arrivato, prima
    che la transcodifica lo sostituisca. Ritorna cio' che ha trovato."""
    with tempfile.TemporaryDirectory() as tmp:
        copia = os.path.join(tmp, 'sorgente')
        with allegato.file.open('rb') as fin, open(copia, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
        dati = sonda(copia)
    if not dati:
        return None
    logger.info('clip %s: codec=%s %sx%s %s fps, %s s',
                allegato.pk, dati['codec'], dati['larghezza'], dati['altezza'], dati['fps'], dati['durata_s'])
    allegato.codec = (dati['codec'] or '')[:30]
    allegato.durata_s = dati['durata_s']
    allegato.save(update_fields=['codec', 'durata_s'])
    return dati


def transcodifica(allegato):
    """Sostituisce il file dell'allegato con un MP4 leggero. Ritorna True se
    l'ha fatto, False se ffmpeg manca o ha fallito (stato invariato)."""
    binario = _binario()
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
            logger.warning('Transcodifica fallita per allegato %s (codec %s): %s',
                           allegato.pk, allegato.codec or '?', e)
            # Resta l'originale, che il visore offre da scaricare invece di
            # provare a suonarlo (Allegato.genere lo chiama «altro»). L'evento
            # serve a saperlo senza leggere i log: il giorno che arriva un
            # ecografo con un formato che ffmpeg non apre, si vede qui.
            allegato.richiesta.registra('ALLEGATO_NON_CONVERTITO', None, allegato=allegato.pk,
                                        nome=allegato.nome_originale, codec=allegato.codec or '')
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
