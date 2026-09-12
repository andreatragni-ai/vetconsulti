"""
Test della dettatura vocale ibrida: il microfono e' del browser (non si puo'
simulare, e infatti qui non c'e' nessun test che lo tocchi — per quello vale
il controllo visivo), «Ripulisci» e' una chiamata all'AI e si prova con un
client finto.

Cosa si verifica: che la ripulitura ripulisca, che quando fallisce il campo
resti com'era e lo dica, che nessuno salvi niente (e' per questo che
«Annulla ripulitura» puo' esistere), i permessi, il tetto di lunghezza, il
freno sulla frequenza, e che i pulsanti compaiano nei campi giusti.
"""

import json
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache
from django.urls import reverse

from consulti import dettatura
from consulti.models import Richiesta, StatoRichiesta
from core.tipi import TipoEsame

URL = '/consulti/ripulisci/'

DETTATO = ('soffio sistolico tre sesti emme emme vi di stadio be due serve terapia')
RIPULITO = 'Soffio sistolico 3/6, MMVD stadio B2. Serve terapia.'


@pytest.fixture(autouse=True)
def _freno_pulito():
    """Il freno sulla frequenza sta nella cache: fra un test e l'altro si
    azzera, altrimenti il ventunesimo test erediterebbe il tetto."""
    cache.clear()
    yield
    cache.clear()


# ── Il client finto dell'API ─────────────────────────────────────────────────

class ClientFinto:
    def __init__(self, risposta=None, eccezione=None):
        self.risposta = risposta
        self.eccezione = eccezione
        self.parametri = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crea))

    def _crea(self, **parametri):
        self.parametri.append(parametri)
        if self.eccezione:
            raise self.eccezione
        return self.risposta


def _risposta(testo, correzioni=(), stop='end_turn'):
    return SimpleNamespace(
        content=[SimpleNamespace(type='thinking', thinking=''),
                 SimpleNamespace(type='text',
                                 text=json.dumps({'testo': testo, 'correzioni': list(correzioni)}))],
        usage=SimpleNamespace(input_tokens=900, output_tokens=60),
        stop_reason=stop, model='claude-sonnet-5')


# ── Il servizio ──────────────────────────────────────────────────────────────

def test_ripulisce_e_manda_solo_il_testo_con_glossario_e_schema():
    client = ClientFinto(_risposta(RIPULITO, ['emme emme vi di -> MMVD', 'tre sesti -> 3/6']))
    pulito, correzioni, telemetria = dettatura.ripulisci(DETTATO, client=client)
    assert pulito == RIPULITO
    assert correzioni[0] == 'emme emme vi di -> MMVD'
    assert telemetria['modello'] == 'claude-sonnet-5'
    parametri = client.parametri[0]
    # All'API va SOLO testo: nessun blocco immagine, nessun allegato.
    contenuto = parametri['messages'][0]['content']
    assert isinstance(contenuto, str) and DETTATO in contenuto
    sistema = parametri['system'][0]['text']
    assert 'MMVD' in sistema and 'emme emme vi di -> MMVD' in sistema     # glossario e sigle dal file dati
    assert 'Non aggiungere' in sistema                                    # il prompt dal file
    assert parametri['output_config']['format']['type'] == 'json_schema'


def test_il_prompt_non_e_inline_ma_viene_dal_file():
    from pathlib import Path
    from django.conf import settings
    percorso = Path(settings.BASE_DIR) / 'prompts' / 'it' / 'ripulitura_dettatura.md'
    assert percorso.exists()
    assert '{{GLOSSARIO}}' in percorso.read_text(encoding='utf-8')
    assert '{{GLOSSARIO}}' not in dettatura.prompt_sistema()


def test_testo_vuoto_non_chiama_l_api():
    client = ClientFinto(_risposta('qualcosa'))
    assert dettatura.ripulisci('   ', client=client) == ('', [], {})
    assert client.parametri == []


def test_una_risposta_che_riscrive_il_testo_viene_scartata():
    """La cintura di sicurezza: se l'AI restituisce un testo che ha perso
    (o raddoppiato) le parole, non e' una ripulitura ed e' il campo a vincere."""
    client = ClientFinto(_risposta('Soffio.'))
    with pytest.raises(dettatura.RipulituraNonDisponibile) as e:
        dettatura.ripulisci(DETTATO, client=client)
    assert 'intatto' in str(e.value)


def test_risposta_illeggibile_o_rifiuto():
    with pytest.raises(dettatura.RipulituraNonDisponibile):
        dettatura.ripulisci(DETTATO, client=ClientFinto(SimpleNamespace(
            content=[SimpleNamespace(type='text', text='non e\' json')],
            usage=None, stop_reason='end_turn', model='claude-sonnet-5')))
    with pytest.raises(dettatura.RipulituraNonDisponibile):
        dettatura.ripulisci(DETTATO, client=ClientFinto(_risposta(RIPULITO, stop='refusal')))


def test_senza_chiave_non_e_disponibile(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    with pytest.raises(dettatura.RipulituraNonDisponibile) as e:
        dettatura.ripulisci(DETTATO)
    assert 'come l\'hai dettato' in str(e.value)


def test_tetto_di_lunghezza():
    with pytest.raises(dettatura.TestoTroppoLungo):
        dettatura.controlla_lunghezza('a' * (dettatura.LIMITE_CARATTERI + 1))


# ── L'endpoint ───────────────────────────────────────────────────────────────

def _post(client, testo=DETTATO, caso=None):
    corpo = {'testo': testo}
    if caso:
        corpo['caso'] = caso
    return client.post(URL, data=json.dumps(corpo), content_type='application/json')


@pytest.fixture
def bozza(db, mondo, client, crea_bozza):
    client.force_login(mondo.richiedente.user)
    return crea_bozza(client, TipoEsame.ECG, mondo.ref)


def test_il_richiedente_ripulisce_il_suo_quesito(client, bozza, mondo):
    with mock.patch('consulti.dettatura.ripulisci', return_value=(RIPULITO, ['tre sesti -> 3/6'], {})):
        risposta = _post(client, caso=bozza.pk)
    assert risposta.status_code == 200
    assert risposta.json()['testo'] == RIPULITO
    assert risposta.json()['correzioni'] == ['tre sesti -> 3/6']


def test_la_ripulitura_non_salva_niente_quindi_si_puo_annullare(client, bozza):
    """L'endpoint restituisce e basta: il testo di prima resta nel browser
    per «Annulla ripulitura», e sulla richiesta non cambia nulla finche' non
    si salva il form."""
    prima = Richiesta.objects.get(pk=bozza.pk).quesito
    with mock.patch('consulti.dettatura.ripulisci', return_value=(RIPULITO, [], {})):
        _post(client, caso=bozza.pk)
    assert Richiesta.objects.get(pk=bozza.pk).quesito == prima


def test_se_l_ai_fallisce_il_campo_resta_com_era_e_lo_dice(client, bozza):
    errore = dettatura.RipulituraNonDisponibile('La ripulitura non e\' andata a buon fine: '
                                                'il testo resta come l\'hai dettato.')
    with mock.patch('consulti.dettatura.ripulisci', side_effect=errore):
        risposta = _post(client, caso=bozza.pk)
    assert risposta.status_code == 503
    assert 'resta come l\'hai dettato' in risposta.json()['errore']
    assert 'testo' not in risposta.json()


def test_al_passo_due_senza_bozza_il_richiedente_puo_ripulire(client, mondo):
    """La bozza nasce premendo «Avanti»: al primo giro del passo 2 non c'e'
    ancora un caso, ma chi detta e' un richiedente e il testo e' suo."""
    client.force_login(mondo.richiedente.user)
    with mock.patch('consulti.dettatura.ripulisci', return_value=(RIPULITO, [], {})):
        assert _post(client).status_code == 200


def test_un_estraneo_non_ripulisce(client, bozza, mondo):
    client.force_login(mondo.estraneo)
    with mock.patch('consulti.dettatura.ripulisci', return_value=(RIPULITO, [], {})) as finto:
        assert _post(client, caso=bozza.pk).status_code == 404      # il caso non e' suo: 404, non 403
        assert _post(client).status_code == 403                     # e senza caso non ha titolo
    assert finto.call_count == 0


def test_il_refertatore_assegnato_ripulisce_il_referto(client, caso_in_carico, mondo):
    client.force_login(mondo.ref.user)
    with mock.patch('consulti.dettatura.ripulisci', return_value=(RIPULITO, [], {})):
        assert _post(client, caso=caso_in_carico.pk).status_code == 200
    client.force_login(mondo.ref2.user)                             # un altro refertatore: non e' suo
    assert _post(client, caso=caso_in_carico.pk).status_code == 404


def test_il_richiedente_non_ripulisce_su_un_caso_gia_inviato(client, caso_inviato, mondo):
    """Dopo l'invio il richiedente non ha piu' campi da dettare: l'endpoint
    si chiude con lui come si chiude il passo 2."""
    client.force_login(mondo.richiedente.user)
    assert _post(client, caso=caso_inviato.pk).status_code == 404
    assert caso_inviato.stato == StatoRichiesta.INVIATA


def test_serve_l_accesso(client, bozza):
    client.logout()
    assert _post(client, caso=bozza.pk).status_code in (302, 403)


def test_tetto_di_lunghezza_dall_endpoint(client, bozza):
    with mock.patch('consulti.dettatura.ripulisci') as finto:
        risposta = _post(client, testo='a' * (dettatura.LIMITE_CARATTERI + 1), caso=bozza.pk)
    assert risposta.status_code == 413
    assert 'troppo lungo' in risposta.json()['errore']
    assert finto.call_count == 0


def test_freno_sulla_frequenza(client, bozza):
    with mock.patch('consulti.dettatura.ripulisci', return_value=(RIPULITO, [], {})):
        for _ in range(dettatura.QUANTE_RIPULITURE):
            assert _post(client, caso=bozza.pk).status_code == 200
        risposta = _post(client, caso=bozza.pk)
    assert risposta.status_code == 429
    assert 'aspetta' in risposta.json()['errore']


def test_spento_da_settings(client, bozza, settings):
    settings.CONSULTI_DETTATURA_AI = False
    assert _post(client, caso=bozza.pk).status_code == 503


# ── I pulsanti nei campi giusti ──────────────────────────────────────────────

def _campi_con_dettatura(risposta):
    import re
    return set(re.findall(r'data-campo="([^"]+)"', risposta.content.decode()))


def test_i_pulsanti_sono_nei_tre_campi_del_passo_due(client, bozza):
    risposta = client.get(reverse('consulti:passo_esame', args=[bozza.pk]))
    assert _campi_con_dettatura(risposta) == {'id_quesito', 'id_anamnesi', 'id_terapia'}
    testo = risposta.content.decode()
    assert 'data-microfono' in testo and 'data-ripulisci' in testo and 'data-annulla' in testo
    assert 'consulti/js/dettatura.js' in testo


def test_i_pulsanti_sono_nelle_tre_caselle_del_referto(client, caso_in_carico, mondo):
    client.force_login(mondo.ref.user)
    risposta = client.get(reverse('referti:refertazione', args=[caso_in_carico.pk]))
    campi = _campi_con_dettatura(risposta)
    assert {'id_descrizione', 'id_conclusioni', 'id_raccomandazioni'} <= campi
    assert 'motivo-declina' in campi          # anche il motivo del declino
    assert 'consulti/js/dettatura.js' in risposta.content.decode()


def test_senza_chiave_ai_resta_il_microfono_ma_non_ripulisci(client, bozza, settings):
    settings.CONSULTI_DETTATURA_AI = False
    testo = client.get(reverse('consulti:passo_esame', args=[bozza.pk])).content.decode()
    assert 'data-microfono' in testo
    assert 'data-ripulisci' not in testo
