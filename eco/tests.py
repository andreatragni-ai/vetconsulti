import pytest
from django.contrib.auth.models import User

from accounts.models import Clinica, Richiedente
from consulti.models import Allegato, CategoriaAllegato, Richiesta, StatoAllegato
from core.tipi import TipoEsame
from django.core.files.uploadedfile import SimpleUploadedFile
from eco import transcodifica


@pytest.mark.django_db
def test_senza_ffmpeg_non_fallisce(settings):
    settings.FFMPEG_BIN = '/nessun/posto/ffmpeg'
    u = User.objects.create_user('v', 'v@x.it', 'pw')
    c = Clinica.objects.create(denominazione='C')
    r = Richiedente.objects.create(user=u, clinica=c)
    ric = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=r, clinica=c)
    a = Allegato.da_upload(ric, SimpleUploadedFile('clip.avi', b'x' * 100, 'video/avi'),
                           CategoriaAllegato.ECO_CLIP, u)
    from unittest import mock
    with mock.patch.object(transcodifica.logger, 'warning') as avviso:
        assert transcodifica.transcodifica(a) is False
    assert 'ffmpeg non trovato' in avviso.call_args[0][0]
    a.refresh_from_db()
    assert a.stato == StatoAllegato.CARICATO
