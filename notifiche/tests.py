import pytest
from django.contrib.auth.models import User
from django.core import mail

from accounts.models import Clinica, Refertatore, Richiedente
from consulti.models import Paziente, Richiesta
from core.tipi import TipoEsame
from notifiche.models import InvioEmail
from notifiche.servizi import avvisa_caso_arrivato, avvisa_referto_pronto


@pytest.mark.django_db
def test_avvisi_registrati(settings):
    settings.CONSULTI_BASE_URL = 'https://consulti.test'
    c = Clinica.objects.create(denominazione='C')
    ric = Richiedente.objects.create(user=User.objects.create_user('v', 'v@x.it', 'pw'), clinica=c)
    ref = Refertatore.objects.create(user=User.objects.create_user('r', 'r@x.it', 'pw'))
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=ric, clinica=c, refertatore=ref)
    Paziente.objects.create(richiesta=r, nome='Fido')
    assert avvisa_caso_arrivato(r)
    assert avvisa_referto_pronto(r)
    assert len(mail.outbox) == 2
    # Il refertatore arriva alla sua pagina di refertazione, il richiedente al caso.
    assert f'https://consulti.test/referti/caso/{r.pk}/' in mail.outbox[0].body
    assert f'https://consulti.test/consulti/{r.pk}/' in mail.outbox[1].body
    assert InvioEmail.objects.filter(esito='OK').count() == 2


@pytest.mark.django_db
def test_senza_refertatore_non_si_invia():
    c = Clinica.objects.create(denominazione='C')
    ric = Richiedente.objects.create(user=User.objects.create_user('v', 'v@x.it', 'pw'), clinica=c)
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=ric, clinica=c)
    assert avvisa_caso_arrivato(r) is False


def test_referto_pronto_senza_pdf_rimanda_al_portale(caso_in_carico):
    """Se il PDF non c'e' (WeasyPrint giu' alla firma) l'email parte lo stesso."""
    assert avvisa_referto_pronto(caso_in_carico, None)
    email = mail.outbox[-1]
    assert not email.attachments and 'dal portale' in email.body
    assert InvioEmail.objects.get(tipo='REFERTO_PRONTO').allegati == ''


def test_email_non_partita_resta_registrata(caso_inviato, settings):
    from notifiche.servizi import avvisa_caso_declinato
    settings.EMAIL_BACKEND = 'nessun.backend.Inesistente'
    caso_inviato.declina('Non referto gatti.')
    assert avvisa_caso_declinato(caso_inviato) is False
    invio = InvioEmail.objects.get(tipo='CASO_DECLINATO')
    assert invio.esito == 'ERRORE' and invio.errore


# ── Le due email dell'iscrizione (12/09/2026) ──────────────────────────────

@pytest.mark.django_db
def test_iscrizione_avvisa_il_gestore(settings):
    """Chi approva lo scopre per email, non guardando la pagina di gestione."""
    from notifiche.servizi import avvisa_gestore_iscrizione
    settings.EMAIL_GESTORE = 'andre@vetway.it'
    settings.CONSULTI_BASE_URL = 'https://consulti.test'
    c = Clinica.objects.create(denominazione='Clinica Blu')          # non approvata
    ric = Richiedente.objects.create(
        user=User.objects.create_user('v', 'v@x.it', 'pw', first_name='Luca', last_name='Verdi'),
        clinica=c, telefono='02 123')
    assert avvisa_gestore_iscrizione(ric)
    email = mail.outbox[-1]
    assert email.to == ['andre@vetway.it']
    assert 'DA APPROVARE' in email.subject and 'Luca Verdi' in email.subject
    assert 'Clinica Blu' in email.body and 'NUOVA, da approvare' in email.body
    assert 'Dati di fatturazione: mancanti' in email.body
    assert 'https://consulti.test/gestione/richiedenti/' in email.body
    assert InvioEmail.objects.get(tipo='ISCRIZIONE').esito == 'OK'


@pytest.mark.django_db
def test_iscrizione_in_clinica_approvata_non_chiede_nulla(settings):
    """Un collega invitato in una clinica gia' approvata: l'avviso parte
    comunque (c'e' una persona nuova) ma dice che non serve fare niente."""
    from notifiche.servizi import avvisa_gestore_iscrizione
    settings.EMAIL_GESTORE = 'andre@vetway.it'
    c = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    capo = User.objects.create_user('capo', 'capo@x.it', 'pw', first_name='Gina', last_name='Bianchi')
    ric = Richiedente.objects.create(
        user=User.objects.create_user('v', 'v@x.it', 'pw', first_name='Luca', last_name='Verdi'), clinica=c)
    assert avvisa_gestore_iscrizione(ric, invitante=capo)
    email = mail.outbox[-1]
    assert 'DA APPROVARE' not in email.subject
    assert 'Invitato da: Gina Bianchi' in email.body
    assert 'Non devi fare nulla' in email.body


@pytest.mark.django_db
def test_approvazione_avvisa_il_richiedente(settings):
    from notifiche.servizi import avvisa_richiedente_approvato
    settings.CONSULTI_BASE_URL = 'https://consulti.test'
    c = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    ric = Richiedente.objects.create(
        user=User.objects.create_user('v', 'v@x.it', 'pw', first_name='Luca', last_name='Verdi'), clinica=c)
    assert avvisa_richiedente_approvato(ric)
    email = mail.outbox[-1]
    assert email.to == ['v@x.it'] and 'profilo e\' attivo' in email.subject
    # Senza dati di fatturazione l'email lo dice, e manda alla nuova richiesta.
    assert 'dati per la fatturazione elettronica' in email.body
    assert 'https://consulti.test/consulti/nuova/' in email.body
    assert InvioEmail.objects.get(tipo='APPROVAZIONE').esito == 'OK'
