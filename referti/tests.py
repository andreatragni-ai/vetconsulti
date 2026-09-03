from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Clinica, CompetenzaRefertatore, DatiFatturazione, Refertatore, Richiedente
from consulti.models import Allegato, CategoriaAllegato, Paziente, Richiesta, StatoRichiesta
from core.tipi import TipoEsame
from listino.models import VoceListino
from referti.models import Referto, RefertoGiaFirmato
from registro.models import Prestazione


@pytest.fixture
def in_carico(db):
    VoceListino.objects.create(tipo_esame=TipoEsame.ECG, descrizione='ECG', prezzo=Decimal('40.00'),
                               valido_dal=date(2020, 1, 1))
    c = Clinica.objects.create(denominazione='Clinica', approvata=True)
    DatiFatturazione.objects.create(clinica=c, intestatario='X', partita_iva='00743110157', indirizzo_sede='v',
                                    cap='00100', comune='Roma', provincia='RM', pec_fatturazione='x@pec.it',
                                    predefinita=True)
    ric = Richiedente.objects.create(user=User.objects.create_user('vet', 'vet@x.it', 'pw'), clinica=c)
    ref = Refertatore.objects.create(user=User.objects.create_user('ref', 'ref@x.it', 'pw'))
    CompetenzaRefertatore.objects.create(refertatore=ref, tipo_esame=TipoEsame.ECG, referente=True)
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=ric, clinica=c, refertatore=ref)
    Paziente.objects.create(richiesta=r, nome='Fido')
    Allegato.da_upload(r, SimpleUploadedFile('e.pdf', b'pdf'), CategoriaAllegato.ECG_PDF)
    r.invia()
    r.prendi_in_carico(ref)
    return r


def test_firma_chiude_richiesta_e_registra(in_carico):
    referto = Referto.objects.create(richiesta=in_carico, conclusioni='Ritmo sinusale.',
                                     classificazione={'rischio_anestesia': 'basso'})
    with mock.patch('referti.pdf.genera_pdf', return_value=b'%PDF-1.4 finto'):
        referto.firma(in_carico.refertatore.user)
    in_carico.refresh_from_db()
    assert in_carico.stato == StatoRichiesta.REFERTATA
    assert referto.firmato and referto.pdf
    assert Prestazione.objects.filter(richiesta=in_carico).count() == 1
    assert list(in_carico.audit.values_list('azione', flat=True))[-3:] == \
        ['REFERTATA', 'REFERTO_FIRMATO', 'PRESTAZIONE_REGISTRATA']
    with pytest.raises(RefertoGiaFirmato):
        referto.firma(in_carico.refertatore.user)


def test_solo_il_refertatore_assegnato_firma(in_carico):
    referto = Referto.objects.create(richiesta=in_carico, conclusioni='x')
    with pytest.raises(PermissionError):
        referto.firma(in_carico.richiedente.user)


def test_html_del_referto_si_renderizza(in_carico):
    from referti.pdf import html_referto
    referto = Referto.objects.create(richiesta=in_carico, conclusioni='Ritmo sinusale.')
    html = html_referto(referto)
    assert in_carico.codice in html and 'Clinica' in html and 'BOZZA' in html


@pytest.mark.django_db
def test_html_referto_libero_professionista_intestato_a_lui():
    from accounts.models import TipoRichiedente
    from referti.pdf import html_referto
    lp = Richiedente.objects.create(user=User.objects.create_user('lp', 'lp@x.it', 'pw', first_name='Luca',
                                                                  last_name='Verdi'),
                                    tipo=TipoRichiedente.LIBERO_PROFESSIONISTA, approvato=True)
    DatiFatturazione.objects.create(richiedente=lp, intestatario='Luca Verdi', partita_iva='00743110157',
                                    indirizzo_sede='Via Verdi 2', cap='20100', comune='Milano', provincia='MI',
                                    pec_fatturazione='x@pec.it', predefinita=True)
    ref = Refertatore.objects.create(user=User.objects.create_user('ref', 'ref@x.it', 'pw'))
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=lp, refertatore=ref)
    Paziente.objects.create(richiesta=r, nome='Micio')
    html = html_referto(Referto.objects.create(richiesta=r, conclusioni='ok'))
    assert 'Luca Verdi' in html and 'libero professionista' in html and 'Via Verdi 2' in html
    assert 'P.IVA 00743110157' in html
