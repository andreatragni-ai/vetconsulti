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


# ── Catalogo: comando carica_catalogo_eco ────────────────────────────────────

@pytest.mark.django_db
def test_carica_catalogo_eco_dal_repo_e_idempotente():
    """Il catalogo di Andre in eco/catalogo/: 27 righe (25 obbligatorie, 2
    filmati liberi), 62 immagini di riferimento collegate. Rilanciato non
    duplica nulla e sostituisce le immagini."""
    import json
    from io import StringIO
    from django.core.management import call_command
    from eco.management.commands.carica_catalogo_eco import CATALOGO_PREDEFINITO
    from eco.models import ImmagineRiferimento, ProiezioneCatalogo

    righe = json.loads(CATALOGO_PREDEFINITO.read_text(encoding='utf-8'))['righe']
    collegamenti = sum(len(r.get('immagini_riferimento') or []) for r in righe)
    ProiezioneCatalogo.objects.create(codice='VECCHIA', nome='Voce della bozza', obbligatoria=True)
    out = StringIO()
    call_command('carica_catalogo_eco', stdout=out)
    assert ProiezioneCatalogo.objects.filter(attiva=True).count() == len(righe) == 27
    assert ProiezioneCatalogo.objects.filter(attiva=True, obbligatoria=True).count() == 25
    assert list(ProiezioneCatalogo.objects.filter(libera=True).values_list('codice', flat=True)) == [
        'LIBERO_1', 'LIBERO_2']
    assert ImmagineRiferimento.objects.count() == collegamenti == 62
    # La voce che nel file non c'e' piu' si disattiva, non si cancella.
    assert not ProiezioneCatalogo.objects.get(codice='VECCHIA').attiva
    assert 'Disattivate' in out.getvalue() and 'VECCHIA' in out.getvalue()
    dx1 = ProiezioneCatalogo.objects.get(codice='DX1_B')
    assert [i.didascalia for i in dx1.immagini.all()] == ['Immagine ecografica', 'Posizione della sonda', 'Schema']
    assert dx1.istruzioni and dx1.deve_essere_visibile and dx1.serve_per
    assert not ProiezioneCatalogo.objects.get(codice='SUB_B').immagini.exists()
    call_command('carica_catalogo_eco', stdout=StringIO())
    assert ProiezioneCatalogo.objects.count() == 28 and ImmagineRiferimento.objects.count() == 62


@pytest.mark.django_db
def test_carica_catalogo_eco_rifiuta_un_file_sbagliato(tmp_path):
    import json
    from django.core.management import CommandError, call_command
    from eco.models import ProiezioneCatalogo
    file = tmp_path / 'catalogo.json'
    file.write_text(json.dumps({'righe': [
        {'codice': 'A', 'nome': 'A', 'finestra': 'NESSUNA', 'tipo_media': 'CLIP'},
        {'codice': 'B', 'nome': 'B', 'finestra': 'ALTRO', 'tipo_media': 'CLIP', 'libera': True, 'obbligatoria': True},
        {'codice': 'C', 'nome': 'C', 'finestra': 'ALTRO', 'tipo_media': 'CLIP', 'immagini_riferimento': ['no.jpg']},
    ]}))
    with pytest.raises(CommandError) as errore:
        call_command('carica_catalogo_eco', str(file))
    messaggio = str(errore.value)
    assert 'finestra sconosciuta' in messaggio and 'non puo\' essere obbligatorio' in messaggio
    assert 'no.jpg non trovata' in messaggio
    assert not ProiezioneCatalogo.objects.exists()
