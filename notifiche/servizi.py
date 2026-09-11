"""
Le email del portale: partono quando la palla cambia mano.

- al refertatore: caso arrivato (anche dopo una riassegnazione), sollecito
  a meta' del tempo di risposta, presa in carico rilasciata per inattivita';
- al richiedente: referto pronto (con il PDF allegato), referto rettificato
  (con il PDF nuovo), caso declinato e caso non refertabile (deve agire).

Nessuna email per la presa in carico: il richiedente la vede sul caso.

Tutte best-effort: non sollevano mai, lasciano una riga in InvioEmail. I
testi stanno in templates/notifiche/*.txt, i link sono assoluti da
CONSULTI_BASE_URL perche' spesso non c'e' una request (cron).
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse

from .models import EsitoInvio, InvioEmail, TipoInvio

logger = logging.getLogger('notifiche')


def _assoluto(percorso):
    return settings.CONSULTI_BASE_URL.rstrip('/') + percorso


def _link_richiesta(richiesta):
    return _assoluto(reverse('consulti:dettaglio', args=[richiesta.pk]))


def _link_refertazione(richiesta):
    return _assoluto(reverse('referti:refertazione', args=[richiesta.pk]))


def _invia(tipo, destinatario, oggetto, template, contesto, richiesta=None, link=None, allegati=()):
    """`allegati`: [(nome, contenuto_bytes, mime)]."""
    nomi = ', '.join(nome for nome, _c, _m in allegati)[:300]
    if not destinatario:
        InvioEmail.objects.create(destinatario='', oggetto=oggetto, tipo=tipo, richiesta=richiesta,
                                  esito=EsitoInvio.ERRORE, errore='Nessun indirizzo email.', allegati=nomi)
        return False
    if link is None:
        link = _link_richiesta(richiesta) if richiesta else settings.CONSULTI_BASE_URL
    contesto = {'base_url': settings.CONSULTI_BASE_URL, 'richiesta': richiesta, 'link': link,
                'con_allegato': bool(allegati), **contesto}
    corpo = render_to_string(template, contesto)
    try:
        messaggio = EmailMessage(subject=oggetto, body=corpo, to=[destinatario],
                                 reply_to=[settings.EMAIL_REPLY_TO])
        for nome, contenuto, mime in allegati:
            messaggio.attach(nome, contenuto, mime)
        messaggio.send(fail_silently=False)
    except Exception as e:
        logger.exception('Email %s a %s non inviata', tipo, destinatario)
        InvioEmail.objects.create(destinatario=destinatario, oggetto=oggetto, tipo=tipo, richiesta=richiesta,
                                  esito=EsitoInvio.ERRORE, errore=str(e)[:2000], allegati=nomi)
        return False
    InvioEmail.objects.create(destinatario=destinatario, oggetto=oggetto, tipo=tipo, richiesta=richiesta,
                              esito=EsitoInvio.OK, allegati=nomi)
    return True


def _pdf_allegato(versione):
    """[(nome, byte, mime)] con il PDF della versione, o [] se non c'e' e non
    si riesce a generarlo: l'email parte lo stesso e rimanda al portale."""
    if versione is None:
        return []
    from referti.pdf import contenuto_pdf, nome_file
    try:
        contenuto = contenuto_pdf(versione)
    except Exception:
        logger.exception('PDF della versione %s non leggibile per l\'email.', versione.pk)
        contenuto = None
    return [(nome_file(versione), contenuto, 'application/pdf')] if contenuto else []


# ── Al refertatore ──────────────────────────────────────────────────────────

def avvisa_caso_arrivato(richiesta):
    ref = richiesta.refertatore
    if ref is None:
        return False
    return _invia(TipoInvio.CASO_ARRIVATO, ref.user.email,
                  f'[VetWay Consulti] Nuovo caso {richiesta.codice} — {richiesta.get_tipo_esame_display()}',
                  'notifiche/caso_arrivato.txt', {'refertatore': ref}, richiesta,
                  link=_link_refertazione(richiesta))


def sollecita_refertatore(richiesta, ore_dichiarate=None):
    """Promemoria a meta' del tempo di risposta dichiarato (sorveglia_consulti)."""
    ref = richiesta.refertatore
    if ref is None:
        return False
    return _invia(TipoInvio.SOLLECITO, ref.user.email,
                  f'[VetWay Consulti] Promemoria: caso {richiesta.codice} in attesa',
                  'notifiche/sollecito.txt', {'refertatore': ref, 'ore_dichiarate': ore_dichiarate},
                  richiesta, link=_link_refertazione(richiesta))


def avvisa_presa_rilasciata(richiesta, ore=None):
    """La presa in carico e' scaduta ed e' stata rilasciata (sorveglia_consulti)."""
    ref = richiesta.refertatore
    if ref is None:
        return False
    return _invia(TipoInvio.RILASCIO, ref.user.email,
                  f'[VetWay Consulti] Caso {richiesta.codice} rimesso a disposizione',
                  'notifiche/rilascio.txt', {'refertatore': ref, 'ore': ore}, richiesta,
                  link=_link_refertazione(richiesta))


# ── Al richiedente ──────────────────────────────────────────────────────────

def avvisa_referto_pronto(richiesta, versione=None):
    return _invia(TipoInvio.REFERTO_PRONTO, richiesta.richiedente.user.email,
                  f'[VetWay Consulti] Referto pronto per {richiesta.codice}',
                  'notifiche/referto_pronto.txt', {'richiedente': richiesta.richiedente, 'versione': versione},
                  richiesta, allegati=_pdf_allegato(versione))


def avvisa_referto_rettificato(richiesta, versione):
    return _invia(TipoInvio.REFERTO_RETTIFICATO, richiesta.richiedente.user.email,
                  f'[VetWay Consulti] Referto {richiesta.codice} rettificato (versione {versione.numero})',
                  'notifiche/referto_rettificato.txt', {'richiedente': richiesta.richiedente, 'versione': versione},
                  richiesta, allegati=_pdf_allegato(versione))


def avvisa_caso_declinato(richiesta, refertatore=None):
    return _invia(TipoInvio.CASO_DECLINATO, richiesta.richiedente.user.email,
                  f'[VetWay Consulti] Caso {richiesta.codice} declinato: scegli un altro esperto',
                  'notifiche/caso_declinato.txt',
                  {'richiedente': richiesta.richiedente, 'refertatore': refertatore or richiesta.refertatore},
                  richiesta)


def avvisa_non_refertabile(richiesta):
    return _invia(TipoInvio.NON_REFERTABILE, richiesta.richiedente.user.email,
                  f'[VetWay Consulti] Caso {richiesta.codice} non refertabile',
                  'notifiche/non_refertabile.txt', {'richiedente': richiesta.richiedente}, richiesta)
