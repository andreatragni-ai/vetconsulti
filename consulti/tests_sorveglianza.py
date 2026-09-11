"""Test di sorveglia_consulti: sollecito al refertatore a meta' del tempo di
risposta dichiarato (una volta sola per invio), --prova che non tocca nulla,
rilascio delle prese in carico scadute con l'avviso al refertatore.
Fixture in conftest.py: mondo, caso_inviato, caso_in_carico."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from consulti.models import Richiesta, StatoRichiesta
from notifiche.models import InvioEmail, TipoInvio


# ── sorveglia_consulti: sollecito a meta' tempo e rilascio ──────────────────

def _indietro(richiesta, ore, campo='inviata_il'):
    Richiesta.objects.filter(pk=richiesta.pk).update(**{campo: timezone.now() - timedelta(hours=ore)})
    richiesta.refresh_from_db()


def _sorveglia(*argomenti):
    out = StringIO()
    call_command('sorveglia_consulti', *argomenti, stdout=out)
    return out.getvalue()


def test_sollecito_a_meta_tempo_una_volta_sola(caso_inviato, mondo):
    _indietro(caso_inviato, 11)                      # 24 h dichiarate: meta' = 12 h
    assert 'Nessun caso da sollecitare' in _sorveglia()
    _indietro(caso_inviato, 13)
    out = _sorveglia()
    assert caso_inviato.codice in out
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ['ref@x.it']
    assert 'Promemoria' in mail.outbox[0].subject and '24 ore' in mail.outbox[0].body
    assert caso_inviato.audit.filter(azione='SOLLECITO').count() == 1
    _sorveglia()
    _sorveglia()
    assert len(mail.outbox) == 1                      # idempotente
    assert caso_inviato.audit.filter(azione='SOLLECITO').count() == 1


def test_sollecito_prova_non_invia_nulla(caso_inviato):
    _indietro(caso_inviato, 13)
    out = _sorveglia('--prova')
    assert '[prova]' in out and caso_inviato.codice in out
    assert not mail.outbox and not caso_inviato.audit.filter(azione='SOLLECITO').exists()


def test_sollecito_riparte_dopo_la_riassegnazione(caso_inviato, mondo):
    _indietro(caso_inviato, 13)
    _sorveglia()
    caso_inviato.declina('no')
    caso_inviato.riassegna(mondo.ref2)               # 48 h non dichiarate: meta' = 24 h
    _sorveglia()
    assert len(mail.outbox) == 1                      # il nuovo esperto ha appena ricevuto il caso
    with mock.patch('django.utils.timezone.now', return_value=timezone.now() + timedelta(hours=25)):
        _sorveglia()
    assert [m.to for m in mail.outbox] == [['ref@x.it'], ['ref2@x.it']]


def test_rilascio_delle_prese_in_carico_scadute(caso_in_carico, settings):
    settings.CONSULTI_ORE_PRESA_IN_CARICO = 24
    _indietro(caso_in_carico, 30, 'presa_in_carico_il')
    assert '[prova]' in _sorveglia('--prova')
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.PRESA_IN_CARICO and not mail.outbox
    out = _sorveglia()
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.INVIATA and 'rilasciata' in out
    assert caso_in_carico.audit.filter(azione='RILASCIATA').exists()
    assert InvioEmail.objects.filter(tipo=TipoInvio.RILASCIO, destinatario='ref@x.it').count() == 1
    # Nello stesso giro il caso appena rilasciato non riceve anche il sollecito.
    assert not InvioEmail.objects.filter(tipo=TipoInvio.SOLLECITO).exists()


