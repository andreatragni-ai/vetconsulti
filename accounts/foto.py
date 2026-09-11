"""
La foto dell'esperto ridotta al salvataggio (Refertatore.save): un JPEG di
al piu' LATO px sul lato lungo, raddrizzato secondo l'EXIF (le foto del
telefono arrivano spesso ruotate). Se Pillow non riesce ad aprirla (non
dovrebbe: l'ImageField l'ha gia' verificata) resta il file com'era.
"""

import io
import logging
import os

from django.core.files.base import ContentFile

logger = logging.getLogger('accounts')

LATO = 480


def riduci(file_caricato, lato=LATO):
    from PIL import Image, ImageOps
    try:
        file_caricato.seek(0)
        immagine = ImageOps.exif_transpose(Image.open(file_caricato))
        immagine = immagine.convert('RGB')
        immagine.thumbnail((lato, lato))
        uscita = io.BytesIO()
        immagine.save(uscita, format='JPEG', quality=85, optimize=True)
    except Exception:
        logger.warning('Foto %s non ridotta: resta l\'originale.', getattr(file_caricato, 'name', ''), exc_info=True)
        file_caricato.seek(0)
        return file_caricato
    base = os.path.splitext(os.path.basename(file_caricato.name or 'foto'))[0] or 'foto'
    return ContentFile(uscita.getvalue(), name=f'{base}.jpg')
