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
