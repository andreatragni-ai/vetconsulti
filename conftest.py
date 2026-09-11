"""Fixture globali di pytest.

- I test che caricano allegati non devono sporcare media/ del progetto:
  ogni test scrive in una cartella temporanea.
- `mondo`, `caso_inviato`, `caso_in_carico`: il minimo per provare il flusso
  di refertazione (listino, clinica approvata, richiedente, due refertatori
  ECG, uno staff, un estraneo).
- `pdf_finto`: WeasyPrint sostituito da un PDF finto, per i test che non
  guardano il PDF. `weasyprint_vero`: salta con un messaggio chiaro se le
  librerie di sistema non si trovano (sul Mac serve
  DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib).
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest

PDF_FINTO = b'%PDF-1.4 finto per i test\n%%EOF\n'


@pytest.fixture(autouse=True)
def _media_temporanea(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / 'media'


@pytest.fixture(autouse=True)
def _password_veloci(settings):
    """PBKDF2 costa ~0,2 s a utente: nei test non protegge niente e con le
    fixture a cinque utenti la suite passava da 20 s a oltre un minuto."""
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture
def pdf_finto():
    with mock.patch('referti.pdf.genera_pdf', return_value=PDF_FINTO) as finto:
        yield finto


@pytest.fixture
def weasyprint_vero():
    try:
        from weasyprint import HTML
        HTML(string='<p>prova</p>').write_pdf()
    except Exception as e:  # OSError: libgobject/pango non trovate
        pytest.skip('WeasyPrint non trova le librerie di sistema (%s): lancia pytest con '
                    'DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib, vedi README "Avvio in locale".'
                    % str(e).splitlines()[0][:80])


@pytest.fixture
def mondo(db):
    from django.contrib.auth.models import User

    from accounts.models import Clinica, CompetenzaRefertatore, DatiFatturazione, Refertatore, Richiedente
    from core.tipi import TipoEsame
    from listino.models import VoceListino

    for tipo, prezzo in ((TipoEsame.ECG, '40.00'), (TipoEsame.ECO, '70.00'), (TipoEsame.HOLTER, '90.00')):
        VoceListino.objects.create(tipo_esame=tipo, descrizione=tipo, prezzo=Decimal(prezzo),
                                   valido_dal=date(2020, 1, 1))
    clinica = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    DatiFatturazione.objects.create(
        clinica=clinica, intestatario='Clinica Rossi srl', partita_iva='00743110157', indirizzo_sede='Via Roma 1',
        cap='20100', comune='Milano', provincia='MI', codice_sdi='0000000', pec_fatturazione='rossi@pec.it',
        predefinita=True)
    richiedente = Richiedente.objects.create(
        user=User.objects.create_user('vet', 'vet@x.it', 'pw', first_name='Mario', last_name='Rossi'),
        clinica=clinica)

    def refertatore(username, nome, ore=None):
        r = Refertatore.objects.create(
            user=User.objects.create_user(username, f'{username}@x.it', 'pw', first_name=nome, last_name='Test'),
            titolo='Dott.')
        CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=TipoEsame.ECG, referente=True,
                                             tempo_risposta_ore=ore)
        return r

    return SimpleNamespace(
        clinica=clinica, richiedente=richiedente,
        ref=refertatore('ref', 'Anna', ore=24), ref2=refertatore('ref2', 'Bruno'),
        staff=User.objects.create_user('staff', 'staff@x.it', 'pw', is_staff=True),
        estraneo=User.objects.create_user('estraneo', 'e@x.it', 'pw'),
    )


@pytest.fixture
def caso_inviato(mondo):
    """Un ECG INVIATO dal richiedente del mondo al refertatore `ref`."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from consulti.models import Allegato, CategoriaAllegato, Paziente, Richiesta
    from core.tipi import TipoEsame

    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=mondo.richiedente, clinica=mondo.clinica,
                                 refertatore=mondo.ref, quesito='Aritmia?')
    Paziente.objects.create(richiesta=r, nome='Fido')
    Allegato.da_upload(r, SimpleUploadedFile('ecg.pdf', b'%PDF-1.4 tracciato', 'application/pdf'),
                       CategoriaAllegato.ECG_PDF, mondo.richiedente.user)
    r.invia(mondo.richiedente.user)
    return r


@pytest.fixture
def caso_in_carico(caso_inviato, mondo):
    caso_inviato.prendi_in_carico(mondo.ref, mondo.ref.user)
    return caso_inviato
