"""L'identita' del caso (F2, punto F): negli elenchi, nella pagina del
refertatore e nell'oggetto delle email il caso si chiama come il paziente
con l'esame («Fido · Elettrocardiogramma»); il codice resta accanto, piccolo."""

import html

from django.core import mail
from django.urls import reverse

from consulti.models import Richiesta


def _t(risposta):
    return html.unescape(risposta.content.decode())


def test_elenchi_col_paziente_come_colonna_principale(caso_inviato, client, mondo):
    client.force_login(mondo.richiedente.user)
    elenco = _t(client.get(reverse('consulti:mie_richieste')))
    assert '<strong>Fido</strong>' in elenco and caso_inviato.codice in elenco and '<th>Codice</th>' not in elenco
    assert elenco.index('<th>Paziente</th>') < elenco.index('<th>Esame</th>')
    client.force_login(mondo.ref.user)
    ricevuti = _t(client.get(reverse('consulti:casi_ricevuti')))
    assert '<strong>Fido</strong>' in ricevuti and caso_inviato.codice in ricevuti and '<th>Codice</th>' not in ricevuti


def test_pagina_del_refertatore_col_paziente_e_senza_motivo_vuoto(caso_inviato, client, mondo):
    client.force_login(mondo.ref.user)
    url = reverse('referti:refertazione', args=[caso_inviato.pk])
    pagina = _t(client.get(url))
    assert '<title>Fido · Elettrocardiogramma — refertazione' in pagina and caso_inviato.codice in pagina
    assert 'Motivo dell' not in pagina
    Richiesta.objects.filter(pk=caso_inviato.pk).update(motivo_esame='DEMO — ECG di collaudo')
    assert 'DEMO — ECG di collaudo' in _t(client.get(url))


def test_email_con_il_nome_del_paziente(caso_inviato):
    from notifiche.servizi import avvisa_caso_arrivato, avvisa_caso_declinato
    avvisa_caso_arrivato(caso_inviato)
    caso_inviato.declina('no')
    avvisa_caso_declinato(caso_inviato)
    oggetti = [m.subject for m in mail.outbox]
    assert len(oggetti) == 2
    assert all(f'Fido · Elettrocardiogramma ({caso_inviato.codice})' in o for o in oggetti), oggetti


def test_pie_di_pagina_senza_la_tecnologia(client, mondo):
    """«Django + PostgreSQL» al collega non dice nulla: il pie' di pagina ha
    solo il prodotto, la privacy e i termini."""
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:mie_richieste')))
    assert 'Django + PostgreSQL' not in pagina and 'Powered by <strong>VetWay Consulti</strong>' in pagina
    assert reverse('core:privacy') in pagina and reverse('core:termini') in pagina
