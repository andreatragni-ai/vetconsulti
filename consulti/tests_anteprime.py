"""Test delle miniature degli allegati (Allegato.anteprima): quella del
browser normalizzata, quella fatta dal server per le immagini, la view
protetta con gli stessi permessi del file, la pulizia alla rimozione."""

import io
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from consulti import anteprime
from consulti.models import Allegato, CategoriaAllegato
from consulti.tests_percorso import MP4, _carica, bozza_eco, catalogo, esperto_eco, loggato  # noqa: F401


def _jpeg(larghezza=1200, altezza=900):
    uscita = io.BytesIO()
    Image.new('RGB', (larghezza, altezza), (90, 90, 90)).save(uscita, 'JPEG')
    return uscita.getvalue()


def _su_riga(client, richiesta, proiezione, nome, contenuto, anteprima=None):
    extra = {'proiezione': proiezione.pk}
    if anteprima is not None:
        extra['anteprima'] = SimpleUploadedFile('anteprima.jpg', anteprima, content_type='image/jpeg')
    return _carica(client, richiesta, 'proiezione', SimpleUploadedFile(nome, contenuto), **extra)


def test_anteprima_del_browser_normalizzata_e_quella_del_server(loggato, bozza_eco, catalogo):
    assert _su_riga(loggato, bozza_eco, catalogo['pd_clip'], 'clip.mp4', MP4, anteprima=_jpeg(1600, 1200)) \
        .status_code == 200
    assert _su_riga(loggato, bozza_eco, catalogo['pd_statica'], 'laao.jpg', _jpeg()).status_code == 200
    assert _su_riga(loggato, bozza_eco, catalogo['ap_clip'], 'senza.mp4', MP4 + b'x').status_code == 200
    clip, immagine, senza = (bozza_eco.allegati.get(nome_originale=n) for n in ('clip.mp4', 'laao.jpg', 'senza.mp4'))
    with Image.open(clip.anteprima.path) as im:
        assert im.size == (800, 600) and im.format == 'JPEG'
    with Image.open(immagine.anteprima.path) as im:
        assert max(im.size) == 800
    assert not senza.anteprima and senza.url_anteprima is None


def test_anteprima_rovinata_non_ferma_il_caricamento(loggato, bozza_eco, catalogo):
    assert _su_riga(loggato, bozza_eco, catalogo['pd_clip'], 'clip.mp4', MP4, anteprima=b'non un jpeg') \
        .status_code == 200
    assert not bozza_eco.allegati.get().anteprima


def test_anteprima_troppo_grande_ignorata(loggato, bozza_eco, catalogo, monkeypatch):
    monkeypatch.setattr(anteprime, 'MAX_BYTE_ANTEPRIMA', 100)
    _su_riga(loggato, bozza_eco, catalogo['pd_clip'], 'clip.mp4', MP4, anteprima=_jpeg())
    assert not bozza_eco.allegati.get().anteprima


def test_anteprima_solo_a_chi_vede_il_file(client, loggato, bozza_eco, catalogo, mondo, esperto_eco):
    _su_riga(loggato, bozza_eco, catalogo['pd_statica'], 'laao.jpg', _jpeg())
    allegato = bozza_eco.allegati.get()
    url = allegato.url_anteprima
    assert url == reverse('anteprima_allegato', args=[allegato.pk])
    r = loggato.get(url)
    assert r.status_code == 200 and '/anteprime/' in r['X-Accel-Redirect'] and 'private' in r['Cache-Control']
    with allegato.anteprima.open('rb') as f:
        assert f.read(3) == b'\xff\xd8\xff'
    # Una bozza e' di chi la scrive: il refertatore no; lo staff si'; gli altri 404.
    for utente, atteso in ((mondo.estraneo, 404), (esperto_eco.user, 404), (mondo.staff, 200)):
        client.force_login(utente)
        assert client.get(url).status_code == atteso, utente
    client.logout()
    assert client.get(url).status_code == 302
    senza = Allegato.objects.create(richiesta=bozza_eco, categoria=CategoriaAllegato.ECO_CLIP, file='x.mp4')
    client.force_login(mondo.staff)
    assert client.get(reverse('anteprima_allegato', args=[senza.pk])).status_code == 404


def test_rimuovere_il_file_toglie_anche_l_anteprima(loggato, bozza_eco, catalogo):
    _su_riga(loggato, bozza_eco, catalogo['pd_statica'], 'laao.jpg', _jpeg())
    allegato = bozza_eco.allegati.get()
    percorso = allegato.anteprima.path
    loggato.post(reverse('consulti:elimina_allegato', args=[bozza_eco.pk, allegato.pk]))
    assert not os.path.exists(percorso)


@pytest.mark.django_db
def test_assicura_senza_ffmpeg_non_fa_nulla_per_i_filmati(settings, bozza_eco):
    settings.FFMPEG_BIN = '/nessun/posto/ffmpeg'
    a = Allegato.da_upload(bozza_eco, SimpleUploadedFile('c.avi', b'RIFF finto', 'video/avi'),
                           CategoriaAllegato.ECO_CLIP)
    assert anteprime.assicura(a) is False and not a.anteprima
