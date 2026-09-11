"""Test del passo 1 della richiesta (il paziente) nati dal collaudo
dell'11/09/2026: razza da un elenco che cambia con la specie, data di
nascita scritta a mano (gg/mm/aaaa), maiuscole automatiche su nome del
paziente e cognome del proprietario."""

import html
import json
import re

import pytest
from django.urls import reverse

from consulti import percorso, razze
from consulti.models import Specie


def _t(risposta):
    return html.unescape(risposta.content.decode())


@pytest.fixture
def loggato(client, mondo):
    client.force_login(mondo.richiedente.user)
    return client


# ── Razza: un elenco per specie ──────────────────────────────────────────────

def test_elenchi_copiati_da_vetcardio_meticcio_in_testa():
    assert set(razze.RAZZE) == set(Specie.values) == {'CANE', 'GATTO'}
    assert len(razze.CANE) == 207 and len(razze.GATTO) == 58
    assert razze.CANE[0] == razze.GATTO[0] == 'meticcio'
    assert len(set(razze.CANE)) == 207 and len(set(razze.GATTO)) == 58


def test_filtro_per_specie():
    # Stesso testo, specie diversa: elenchi diversi.
    assert razze.filtra('GATTO', 'pers') == ['Persiano']
    assert razze.filtra('CANE', 'pers') == ['Levriero Persiano']
    assert razze.filtra('GATTO', 'maine') == ['Maine Coon'] and razze.filtra('CANE', 'maine') == []
    assert razze.filtra('CANE', 'boxer') == ['Boxer'] and razze.filtra('GATTO', 'boxer') == []
    # Senza testo tutto l'elenco della specie, meticcio primo; senza specie niente.
    assert razze.filtra('CANE', '') == razze.CANE and razze.filtra('GATTO', '  ')[0] == 'meticcio'
    assert razze.filtra('', 'boxer') == [] and razze.filtra(None, '') == []


def test_filtro_prima_chi_inizia_poi_chi_contiene_senza_accenti_e_maiuscole():
    bo = razze.filtra('CANE', 'BO')
    assert bo[:3] == ['Bobtail', 'Bolognese', 'Border Collie']
    assert bo.index('Boxer') < bo.index('Barbone')          # «Barbone» contiene «bo», non inizia
    assert razze.filtra('CANE', 'frise') == ['Bichon Frisé']  # accenti ignorati
    assert razze.filtra('GATTO', 'meti') == ['meticcio']


def test_normalizza_prende_la_grafia_dell_elenco_della_specie():
    assert razze.normalizza('GATTO', '  maine   coon ') == 'Maine Coon'
    assert razze.normalizza('CANE', 'maine coon') == 'maine coon'      # fuori elenco: com'e'
    assert razze.normalizza('CANE', 'BICHON FRISE') == 'Bichon Frisé'
    assert razze.in_elenco('CANE', 'meticcio') and not razze.in_elenco('CANE', 'Persiano')


def test_la_pagina_porta_gli_elenchi_e_il_combobox(loggato):
    pagina = loggato.get(reverse('consulti:nuova')).content.decode()
    dati = json.loads(re.search(r'<script id="razze-per-specie" type="application/json">(.*?)</script>',
                                pagina, re.S).group(1))
    assert dati == {'CANE': razze.CANE, 'GATTO': razze.GATTO}
    campo = re.search(r'<input[^>]*name="razza"[^>]*>', pagina).group(0)
    for attributo in ('role="combobox"', 'aria-autocomplete="list"', 'aria-controls="razza-elenco"',
                      'data-elenco-filtrato="razze-per-specie"', 'data-chiave-da="specie"', 'autocomplete="off"'):
        assert attributo in campo, attributo
    assert 'id="razza-elenco" role="listbox"' in pagina and 'id="razza-avviso" hidden' in pagina
    assert 'consulti/js/elenco_filtrato.js' in pagina


@pytest.mark.parametrize('specie, scritta, salvata', [
    ('GATTO', 'maine coon', 'Maine Coon'),
    ('CANE', 'MeTiCcIo', 'meticcio'),
    ('CANE', 'Incrocio pastore x husky', 'Incrocio pastore x husky'),   # fuori elenco: si accetta
    ('CANE', '', ''),
])
def test_la_razza_si_salva_come_nell_elenco_o_come_scritta(loggato, mondo, crea_bozza, specie, scritta, salvata):
    r = crea_bozza(loggato, 'ECG', mondo.ref, paziente={'nome': 'Fido', 'specie': specie, 'razza': scritta})
    assert r.paziente.razza == salvata


def test_in_sessione_prima_della_bozza_la_razza_e_gia_normalizzata(loggato):
    loggato.post(reverse('consulti:nuova'), {'nome': 'Micia', 'specie': 'GATTO', 'sesso': 'F',
                                             'razza': 'sacro di birmania'})
    assert loggato.session[percorso.SESSIONE_PAZIENTE]['razza'] == 'Sacro di Birmania'
