from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import (Clinica, CompetenzaRefertatore, DatiFatturazione, Refertatore, Richiedente,
                             SoggettoEmittente, TipoRichiedente)
from consulti.models import Allegato, CategoriaAllegato, Paziente, Richiesta
from core.tipi import TipoEsame
from listino.models import VoceListino
from registro.models import Prestazione, PrestazioneImmutabile, StatoFatturazione
from registro.servizi import registra_prestazione


@pytest.fixture
def richiesta_in_carico(db):
    VoceListino.objects.create(tipo_esame=TipoEsame.ECG, descrizione='ECG', prezzo=Decimal('40.00'),
                               valido_dal=date(2020, 1, 1))
    c = Clinica.objects.create(denominazione='Clinica', approvata=True)
    DatiFatturazione.objects.create(clinica=c, intestatario='X', partita_iva='00743110157', indirizzo_sede='v',
                                    cap='00100', comune='Roma', provincia='RM', pec_fatturazione='x@pec.it',
                                    predefinita=True)
    ru = User.objects.create_user('vet', 'vet@x.it', 'pw')
    ric = Richiedente.objects.create(user=ru, clinica=c)
    fu = User.objects.create_user('ref', 'ref@x.it', 'pw')
    ref = Refertatore.objects.create(user=fu, soggetto_emittente=SoggettoEmittente.SOCIETA)
    CompetenzaRefertatore.objects.create(refertatore=ref, tipo_esame=TipoEsame.ECG, referente=True)
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=ric, clinica=c, refertatore=ref)
    Paziente.objects.create(richiesta=r, nome='Fido')
    Allegato.da_upload(r, SimpleUploadedFile('e.pdf', b'pdf'), CategoriaAllegato.ECG_PDF)
    r.invia()
    r.prendi_in_carico(ref)
    return r


def test_registrazione_idempotente(richiesta_in_carico):
    p1 = registra_prestazione(richiesta_in_carico)
    p2 = registra_prestazione(richiesta_in_carico)
    assert p1.pk == p2.pk
    assert Prestazione.objects.count() == 1
    assert p1.totale == Decimal('48.80')
    assert p1.soggetto_emittente == SoggettoEmittente.SOCIETA
    assert StatoFatturazione.objects.get(prestazione=p1).stato == 'DA_FATTURARE'
    assert richiesta_in_carico.audit.filter(azione='PRESTAZIONE_REGISTRATA').count() == 1


def test_prestazione_immutabile(richiesta_in_carico):
    p = registra_prestazione(richiesta_in_carico)
    p.totale = Decimal('1.00')
    with pytest.raises(PrestazioneImmutabile):
        p.save()
    p.refresh_from_db()
    assert p.totale == Decimal('48.80')
    # Un save senza cambiare i campi del fatto e' ammesso.
    p.save()


def test_soggetto_emittente_copiato_non_seguito(richiesta_in_carico):
    p = registra_prestazione(richiesta_in_carico)
    ref = richiesta_in_carico.refertatore
    ref.soggetto_emittente = SoggettoEmittente.REFERTATORE
    ref.save()
    p.refresh_from_db()
    assert p.soggetto_emittente == SoggettoEmittente.SOCIETA


def test_esporta_csv(richiesta_in_carico, tmp_path):
    from django.core.management import call_command
    registra_prestazione(richiesta_in_carico)
    p = Prestazione.objects.get()
    destinazione = tmp_path / 'out.csv'
    call_command('esporta_prestazioni', mese=p.data.strftime('%Y-%m'), su=str(destinazione))
    righe = destinazione.read_text().splitlines()
    assert len(righe) == 2 and richiesta_in_carico.codice in righe[1]


@pytest.mark.django_db
def test_prestazione_libero_professionista_intestata_a_lui(tmp_path):
    from django.core.management import call_command
    VoceListino.objects.create(tipo_esame=TipoEsame.ECG, descrizione='ECG', prezzo=Decimal('40.00'),
                               valido_dal=date(2020, 1, 1))
    lp = Richiedente.objects.create(user=User.objects.create_user('lp', 'lp@x.it', 'pw', first_name='Luca',
                                                                  last_name='Verdi'),
                                    tipo=TipoRichiedente.LIBERO_PROFESSIONISTA, approvato=True)
    DatiFatturazione.objects.create(richiedente=lp, intestatario='Luca Verdi', partita_iva='00743110157',
                                    indirizzo_sede='v', cap='00100', comune='Roma', provincia='RM',
                                    pec_fatturazione='x@pec.it', predefinita=True)
    ref = Refertatore.objects.create(user=User.objects.create_user('ref', 'ref@x.it', 'pw'))
    CompetenzaRefertatore.objects.create(refertatore=ref, tipo_esame=TipoEsame.ECG, referente=True)
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=lp, refertatore=ref)
    Paziente.objects.create(richiesta=r, nome='Micio')
    Allegato.da_upload(r, SimpleUploadedFile('e.pdf', b'pdf'), CategoriaAllegato.ECG_PDF)
    r.invia()
    r.prendi_in_carico(ref)
    p = registra_prestazione(r)
    assert p.clinica is None and p.intestatario() == lp
    destinazione = tmp_path / 'out.csv'
    call_command('esporta_prestazioni', mese=p.data.strftime('%Y-%m'), su=str(destinazione))
    righe = destinazione.read_text().splitlines()
    assert 'intestatario;tipo_richiedente' in righe[0]
    assert 'Luca Verdi;LIBERO_PROFESSIONISTA' in righe[1]
