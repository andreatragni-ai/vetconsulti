"""
Le tre email del portale. Tutte best-effort: non sollevano mai, loggano su
InvioEmail. I testi stanno in templates/notifiche/*.txt, i link sono
assoluti da CONSULTI_BASE_URL perche' spesso non c'e' una request (cron).
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

from .models import EsitoInvio, InvioEmail, TipoInvio

logger = logging.getLogger('notifiche')


def _link_richiesta(richiesta):
    return settings.CONSULTI_BASE_URL.rstrip('/') + reverse('consulti:dettaglio', args=[richiesta.pk])


def _invia(tipo, destinatario, oggetto, template, contesto, richiesta=None):
    if not destinatario:
        InvioEmail.objects.create(destinatario='', oggetto=oggetto, tipo=tipo, richiesta=richiesta,
                                  esito=EsitoInvio.ERRORE, errore='Nessun indirizzo email.')
        return False
    contesto = {'base_url': settings.CONSULTI_BASE_URL, 'richiesta': richiesta,
                'link': _link_richiesta(richiesta) if richiesta else settings.CONSULTI_BASE_URL, **contesto}
    corpo = render_to_string(template, contesto)
    try:
        EmailMessage(subject=oggetto, body=corpo, to=[destinatario],
                     reply_to=[settings.EMAIL_REPLY_TO]).send(fail_silently=False)
    except Exception as e:
        logger.exception('Email %s a %s non inviata', tipo, destinatario)
        InvioEmail.objects.create(destinatario=destinatario, oggetto=oggetto, tipo=tipo, richiesta=richiesta,
                                  esito=EsitoInvio.ERRORE, errore=str(e)[:2000])
        return False
    InvioEmail.objects.create(destinatario=destinatario, oggetto=oggetto, tipo=tipo, richiesta=richiesta,
                              esito=EsitoInvio.OK)
    return True


def avvisa_caso_arrivato(richiesta):
    ref = richiesta.refertatore
    if ref is None:
        return False
    return _invia(TipoInvio.CASO_ARRIVATO, ref.user.email,
                  f'[VetWay Consulti] Nuovo caso {richiesta.codice} — {richiesta.get_tipo_esame_display()}',
                  'notifiche/caso_arrivato.txt', {'refertatore': ref}, richiesta)


def avvisa_referto_pronto(richiesta):
    return _invia(TipoInvio.REFERTO_PRONTO, richiesta.richiedente.user.email,
                  f'[VetWay Consulti] Referto pronto per {richiesta.codice}',
                  'notifiche/referto_pronto.txt', {'richiedente': richiesta.richiedente}, richiesta)


def sollecita_refertatore(richiesta):
    ref = richiesta.refertatore
    if ref is None:
        return False
    return _invia(TipoInvio.SOLLECITO, ref.user.email,
                  f'[VetWay Consulti] Sollecito: caso {richiesta.codice} in attesa',
                  'notifiche/sollecito.txt', {'refertatore': ref}, richiesta)
