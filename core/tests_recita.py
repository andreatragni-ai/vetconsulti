"""`recita_consulto` e' un collaudo intero in un comando: due colleghi finti
che passano dalle pagine. Qui lo si fa girare sul database di prova, nelle
due varianti, e si guarda che il caso sia arrivato in fondo con tutto
quello che deve lasciare dietro di se' (versione firmata, prestazione,
email, archivio pazienti). Se una pagina del percorso si rompe, si rompe
prima qui che in mano a un collega."""

from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command

from consulti.models import PazienteArchivio, Richiesta, StatoRichiesta
from notifiche.models import InvioEmail
from registro.models import Prestazione


@pytest.fixture
def mondo_demo(db, settings):
    settings.DEBUG = True
    call_command('seed_demo', stdout=StringIO())
    settings.DEBUG = False


def _recita(*argomenti):
    uscita = StringIO()
    call_command('recita_consulto', *argomenti, stdout=uscita)
    testo = uscita.getvalue()
    caso = Richiesta.objects.get(motivo_esame='RECITA — consulto eco simulato')
    return caso, testo


def test_la_recita_arriva_al_referto_firmato(mondo_demo, pdf_finto):
    mail.outbox.clear()
    caso, testo = _recita()
    assert caso.stato == StatoRichiesta.REFERTATA
    assert caso.referto.versioni.count() == 1 and caso.referto.firmato
    assert Prestazione.objects.filter(richiesta=caso).count() == 1
    # Referto PDF, tre clip di base (video), una facoltativa, un filmato libero.
    assert caso.allegati.count() == 6
    assert caso.proiezioni.count() == 5
    assert caso.allegati.filter(categoria='ECO_CLIP').count() == 4
    # Il racconto dice cosa ha letto l'esperto.
    assert 'Esame completo: 3 proiezioni su 3' in testo and 'REFERTATO' in testo
    assert 'si apre nel browser' in testo
    # Due email: caso arrivato e referto pronto, registrate.
    tipi = list(InvioEmail.objects.filter(richiesta=caso).order_by('pk').values_list('tipo', flat=True))
    assert tipi == ['CASO_ARRIVATO', 'REFERTO_PRONTO']
    # L'invio ha messo Luna in archivio.
    assert PazienteArchivio.objects.filter(nome='Luna', cognome_proprietario='Recita').exists()


def test_la_recita_con_riserva_passa_dalle_integrazioni(mondo_demo, pdf_finto):
    caso, testo = _recita('--con-riserva')
    assert caso.stato == StatoRichiesta.REFERTATA and caso.con_riserva
    assert caso.integrazioni.count() == 1 and caso.integrazione_aperta() is None
    azioni = list(caso.audit.order_by('quando').values_list('azione', flat=True))
    assert azioni.index('INTEGRAZIONE_CHIESTA') < azioni.index('INTEGRAZIONE_EVASA') < azioni.index('REFERTATA')
    tipi = list(InvioEmail.objects.filter(richiesta=caso).order_by('pk').values_list('tipo', flat=True))
    assert tipi == ['CASO_ARRIVATO', 'INTEGRAZIONE', 'INTEGRAZIONE_OK', 'REFERTO_PRONTO']
    assert 'CON RISERVA' in testo and 'Ho caricato le integrazioni' in testo


def test_la_seconda_recita_prende_luna_dall_archivio(mondo_demo, pdf_finto):
    _recita()
    Richiesta.objects.filter(motivo_esame='RECITA — consulto eco simulato').update(motivo_esame='prima')
    caso, testo = _recita()
    assert 'propone dall\'archivio' in testo
    assert 'Altri casi di Luna» c\'e\'' in testo
    assert PazienteArchivio.objects.filter(nome='Luna', cognome_proprietario='Recita').count() == 1


def test_senza_un_refertatore_eco_la_recita_si_ferma_subito(mondo_demo):
    from django.core.management.base import CommandError
    with pytest.raises(CommandError, match='non e\' referente'):
        call_command('recita_consulto', '--refertatore', 'rferrari', stdout=StringIO())
    assert not Richiesta.objects.filter(motivo_esame='RECITA — consulto eco simulato').exists()
