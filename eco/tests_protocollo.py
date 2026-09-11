"""Test del protocollo stampabile delle proiezioni eco (eco/views.py):
pagina per gli autenticati nell'ordine di acquisizione, CSS di stampa, PDF."""

import html

import pytest
from django.urls import reverse


def _t(risposta):
    return html.unescape(risposta.content.decode())


@pytest.fixture
def catalogo_vero(db):
    from io import StringIO
    from django.core.management import call_command
    call_command('carica_catalogo_eco', stdout=StringIO())


def test_protocollo_per_gli_autenticati_nell_ordine_di_acquisizione(client, mondo, catalogo_vero):
    url = reverse('eco:protocollo')
    assert client.get(url).status_code == 302
    client.force_login(mondo.estraneo)
    pagina = _t(client.get(url))
    assert 'Protocollo delle proiezioni eco' in pagina and 'acquisisci nell\'ordine del protocollo' in pagina.lower()
    assert '25 proiezioni obbligatorie' in pagina and 'window.print()' in pagina
    assert pagina.index('Asse lungo 4 camere — B-mode') < pagina.index('Asse lungo 4 camere — color Doppler') \
        < pagina.index('Sottoxifoidea — B-mode') < pagina.index('Anello mitralico — TDI con misure') \
        < pagina.index('Filmato libero 1')
    assert '@media print' in pagina and 'break-before: page' in pagina
    assert pagina.count('class="protocollo-riga"') == 27


def test_protocollo_pdf(client, mondo, catalogo_vero, weasyprint_vero):
    client.force_login(mondo.estraneo)
    r = client.get(reverse('eco:protocollo_pdf'))
    assert r.status_code == 200 and r['Content-Type'] == 'application/pdf'
    assert r.content[:5] == b'%PDF-' and 'protocollo_proiezioni_eco.pdf' in r['Content-Disposition']
    from eco.views import contesto_protocollo
    ctx = contesto_protocollo(per_pdf=True)
    assert ctx['gruppi'][0]['righe'][0]['src'].startswith('data:image/jpeg;base64,')
