"""Test dello smistamento automatico dei file dell'eco (eco/smistamento/):
colore dai pixel, righe attese dal nome, i cinque gradi del motore, la
lettura AI con un client finto (bene, «sconosciuto», errori), e
l'esecuzione su una richiesta vera (proposte, mai ProiezioneCaricata).
Nessun test chiama l'API: conftest spegne la lettura AI."""

import io
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from eco.smistamento import colore, motore, righe
from eco.smistamento.dati import (BMODE, COLOR, INCERTO, FileEsame, Lettura, LetturaNonDisponibile, Riga)
from eco.smistamento.lettore import LettoreClaude, interpreta

IMG = Path(__file__).parent / 'catalogo' / 'img'


# ── Immagini sintetiche ──────────────────────────────────────────────────────

def _fotogramma(colorato=False, virato=False, misure=False, seme=1):
    """800x600 come un ecografo: settore a ventaglio di grigi con rumore,
    scritte bianche in alto, tracciato ECG verde in basso. `colorato`: riquadro
    color Doppler (rosso-giallo e blu) e barra della scala colore; `virato`:
    mappa di grigi seppia; `misure`: due linee di misura gialle."""
    rnd = random.Random(seme)
    im = Image.new('RGB', (800, 600), (0, 0, 0))
    d = ImageDraw.Draw(im)
    d.pieslice((100, -300, 700, 500), 55, 125, fill=(40, 40, 40))
    for _ in range(9000):
        x, y = rnd.randint(150, 650), rnd.randint(20, 480)
        g = rnd.randint(30, 200)
        if im.getpixel((x, y)) != (0, 0, 0):
            im.putpixel((x, y), (int(g * 1.1), int(g * .8), int(g * .55)) if virato else (g, g, g))
    d.text((10, 5), 'ROSSI FIDO  ID 12345   P4-1c 3.5MHz', fill=(255, 255, 255))
    d.line([(20, 560), (200, 560), (215, 520), (230, 590), (245, 560), (780, 560)], fill=(0, 220, 0), width=2)
    if colorato:
        d.ellipse((330, 200, 420, 300), fill=(230, 40, 20))
        d.ellipse((360, 230, 400, 270), fill=(255, 220, 30))
        d.ellipse((420, 240, 480, 320), fill=(30, 80, 240))
        for i in range(120):   # barra della scala colore
            t = i / 119
            d.line([(740, 80 + i), (755, 80 + i)], fill=(int(255 * (1 - t)), 30, int(255 * t)))
    if misure:
        d.line([(300, 250), (480, 330)], fill=(255, 230, 0), width=1)
        d.line([(320, 150), (330, 400)], fill=(0, 220, 255), width=1)
    uscita = io.BytesIO()
    im.save(uscita, 'JPEG', quality=85)
    return uscita.getvalue()


# ── Grado 2: colore dai pixel ────────────────────────────────────────────────

def test_color_doppler_sintetico_riconosciuto():
    esito, frazione = colore.classifica(_fotogramma(colorato=True))
    assert esito == COLOR and frazione > colore.SOGLIA_COLOR


def test_bmode_sintetico_con_ecg_verde_e_scritte():
    assert colore.classifica(_fotogramma())[0] == BMODE


def test_linee_di_misura_colorate_non_fanno_color():
    assert colore.classifica(_fotogramma(misure=True))[0] in (BMODE, INCERTO)


def test_mappa_di_grigi_virata_non_e_color():
    """Una tinta sola (seppia) senza blu: mai «color», al piu' incerto."""
    assert colore.classifica(_fotogramma(virato=True))[0] != COLOR


@pytest.mark.parametrize('nome', ['dx1_eco.jpg', 'dx2_eco.jpg', 'dx2_eco2.jpg', 'dx3_eco.jpg', 'sx1_eco.jpg',
                                  'sx2_eco.jpg', 'rif_sub_eco.jpg', 'dx5_eco.jpg', 'sx4_eco2.jpg'])
def test_fotogrammi_bmode_veri_del_catalogo(nome):
    """Le immagini ecografiche vere del catalogo sono tutte B-mode (il
    catalogo non ha fotogrammi color Doppler veri: il color e' provato sulle
    immagini sintetiche)."""
    assert colore.classifica((IMG / nome).read_bytes())[0] == BMODE


@pytest.mark.parametrize('nome', ['rif_lad_misura.jpg', 'rif_pvpa_mmode.jpg', 'dx7_resp.jpg'])
def test_immagini_vere_con_annotazioni_colorate_non_sono_color(nome):
    assert colore.classifica((IMG / nome).read_bytes())[0] != COLOR


# ── Righe: tracciato e colore dal nome ───────────────────────────────────────

def test_tracciato_e_colore_di_tutte_le_righe_del_catalogo():
    catalogo = json.loads((Path(__file__).parent / 'catalogo' / 'catalogo_eco.json').read_text())['righe']
    attesi = {
        'DX1_B': ('2D', 'bmode'), 'DX1_C': ('2D', 'color'), 'DX2_B': ('2D', 'bmode'), 'DX2_C': ('2D', 'color'),
        'DX3_B': ('2D', 'bmode'), 'DX3_C': ('2D', 'color'), 'DX7_MMODE': ('M', None), 'DX_LAD': ('2D', None),
        'DX5_LAAO': ('2D', None), 'DX6_AP_PW': ('PW', None), 'DX6_AP_CW': ('CW', None), 'D2_PVPA': ('M', None),
        'SUB_B': ('2D', 'bmode'), 'SUB_C': ('2D', 'color'), 'SUB_LVOT_PW': ('PW', None),
        'SUB_LVOT_CW': ('CW', None), 'SX1_B': ('2D', 'bmode'), 'SX1_C': ('2D', 'color'), 'SX2_B': ('2D', 'bmode'),
        'SX2_C': ('2D', 'color'), 'SX4_AP_PW': ('PW', None), 'SX4_AP_CW': ('CW', None), 'D1_MIT_PW': ('PW', None),
        'D1_MIT_CW': ('CW', None), 'D1_TDI': ('TDI', None), 'LIBERO_1': ('2D', None), 'LIBERO_2': ('2D', None),
    }
    trovati = {r['codice']: (righe.tracciato_di(r['nome']), righe.colore_di(r['nome'], r['tipo_media']))
               for r in catalogo}
    assert trovati == attesi


# ── Motore: un catalogo piccolo ──────────────────────────────────────────────

def _righe():
    dati = [('DX1_B', 'Asse lungo 4 camere — B-mode', 'CLIP'), ('DX1_C', 'Asse lungo 4 camere — color Doppler', 'CLIP'),
            ('DX2_B', 'Asse lungo 5 camere — B-mode', 'CLIP'), ('DX2_C', 'Asse lungo 5 camere — color Doppler', 'CLIP'),
            ('DX3_B', 'Asse corto — B-mode', 'CLIP'),
            ('MMODE', 'M-mode del ventricolo sinistro', 'STATICA'), ('LAAO', 'LA/Ao', 'STATICA'),
            ('AP_PW', 'Arteria polmonare — Doppler pulsato', 'STATICA'),
            ('AP_CW', 'Arteria polmonare — Doppler continuo', 'STATICA'),
            ('LIBERO_1', 'Filmato libero 1', 'CLIP')]
    return [Riga(id=i + 1, codice=c, nome=n, finestra='Parasternale destra', tipo_media=t, ordine=i,
                 libera=c.startswith('LIBERO'), obbligatoria=not c.startswith('LIBERO'),
                 tracciato=righe.tracciato_di(n), colore=righe.colore_di(n, t)) for i, (c, n, t) in enumerate(dati)]


def _id(codice):
    return next(r.id for r in _righe() if r.codice == codice)


class LettoreFinto:
    """Risponde con le letture date per nome del file; conta le chiamate."""

    def __init__(self, per_nome=None, errore=None):
        self.per_nome = per_nome or {}
        self.errore = errore
        self.chiamate = []

    def leggi(self, da_leggere, righe_):
        self.chiamate.append(da_leggere)
        if self.errore:
            raise self.errore
        letture = {}
        for d in da_leggere:
            lettura = self.per_nome.get(self.nomi[d.file_id])
            if lettura is not None:
                letture[d.file_id] = lettura
        return letture, {'token_input': 100, 'errori': []}


def _file(id_, nome, genere, colore_='', anteprima=b'jpeg'):
    return FileEsame(id=id_, nome=nome, genere=genere, anteprima=anteprima, percorso=nome, colore=colore_)


def _smista(files, letture=None, errore=None, **opzioni):
    lettore = LettoreFinto(letture, errore)
    lettore.nomi = {f.id: f.nome for f in files}
    return motore.smista(files, _righe(), lettore, **opzioni), lettore


def _dove(risultato):
    per_id = {r.id: r.codice for r in _righe()}
    return {p.file_id: ('referto' if p.referto else per_id.get(p.riga_id)) for p in risultato.proposte}


def _p(risultato, file_id):
    return next(p for p in risultato.proposte if p.file_id == file_id)


def test_formato_pdf_referto_e_candidati_per_filmato_e_immagine():
    files = [_file(1, 'referto.pdf', 'pdf', anteprima=None), _file(2, 'clip.mp4', 'video', BMODE),
             _file(3, 'img.jpg', 'immagine')]
    risultato, lettore = _smista(files)
    assert _dove(risultato)[1] == 'referto' and _p(risultato, 1).sicura
    candidati = {d.file_id: d.candidati for d in lettore.chiamate[0]}
    assert candidati[2] == ['DX1_B', 'DX2_B', 'DX3_B']              # filmato B-mode: solo righe filmato B-mode
    assert candidati[3] == ['MMODE', 'LAAO', 'AP_PW', 'AP_CW']       # immagine: solo righe immagine
    assert 1 not in candidati                                        # il PDF non va all'AI
    assert all('LIBERO_1' not in c for c in candidati.values())      # i liberi non si riempiono da soli


def test_due_pdf_il_primo_e_il_referto_da_verificare():
    files = [_file(2, 'b.pdf', 'pdf', anteprima=None), _file(1, 'a.pdf', 'pdf', anteprima=None)]
    risultato, _ = _smista(files)
    dove = _dove(risultato)
    assert dove == {1: 'referto', 2: None}
    assert not next(p for p in risultato.proposte if p.file_id == 1).sicura
    assert 'Piu\' di un PDF' in next(p for p in risultato.proposte if p.file_id == 2).motivo


def test_colore_dai_pixel_vincola_le_righe_color():
    files = [FileEsame(id=1, nome='c.mp4', genere='video', anteprima=_fotogramma(colorato=True), percorso='c.mp4')]
    risultato, lettore = _smista(files)
    assert risultato.proposte[0].colore == COLOR
    assert lettore.chiamate[0][0].candidati == ['DX1_C', 'DX2_C']


def test_lettura_ai_alta_e_coerente_diventa_sicura():
    files = [_file(1, '1.mp4', 'video', BMODE), _file(2, '2.jpg', 'immagine')]
    risultato, _ = _smista(files, {'1.mp4': Lettura('DX2_B', confidenza='alta', tracciato='2D', motivo='efflusso'),
                                   '2.jpg': Lettura('AP_PW', confidenza='alta', tracciato='PW')})
    assert _dove(risultato) == {1: 'DX2_B', 2: 'AP_PW'}
    assert all(p.sicura and p.fonte == 'AI' for p in risultato.proposte)
    assert risultato.lettura_ai


def test_lettura_media_o_tracciato_incoerente_resta_da_verificare():
    files = [_file(1, '1.jpg', 'immagine'), _file(2, '2.jpg', 'immagine')]
    risultato, _ = _smista(files, {'1.jpg': Lettura('AP_PW', confidenza='media', tracciato='PW'),
                                   '2.jpg': Lettura('AP_CW', confidenza='alta', tracciato='PW')})
    assert _dove(risultato) == {1: 'AP_PW', 2: 'AP_CW'}
    assert not any(p.sicura for p in risultato.proposte)
    assert 'la riga vuole Doppler continuo' in _p(risultato, 2).motivo


def test_sconosciuto_resta_da_smistare_con_il_motivo():
    files = [_file(1, '1.jpg', 'immagine')]
    risultato, _ = _smista(files, {'1.jpg': Lettura(None, confidenza='bassa', motivo='immagine sfocata')})
    p = risultato.proposte[0]
    assert p.riga_id is None and 'non l\'ha riconosciuto: immagine sfocata' in p.motivo


def test_codice_fuori_dai_candidati_non_si_usa():
    """Un'immagine proposta dall'AI in una riga filmato: si ignora."""
    files = [_file(1, '1.jpg', 'immagine')]
    risultato, _ = _smista(files, {'1.jpg': Lettura('DX1_B', confidenza='alta')})
    assert risultato.proposte[0].riga_id is None


def test_ai_non_disponibile_si_ferma_a_formato_e_pixel():
    files = [_file(1, 'r.pdf', 'pdf', anteprima=None), _file(2, '1.mp4', 'video', BMODE)]
    risultato, _ = _smista(files, errore=LetturaNonDisponibile('Lettura automatica non configurata.'))
    assert _dove(risultato) == {1: 'referto', 2: None}
    assert risultato.messaggio == 'Lettura automatica non configurata.' and not risultato.lettura_ai
    assert 'Non letto automaticamente' in _p(risultato, 2).motivo


def test_senza_lettore_e_senza_anteprima():
    files = [_file(1, 'vecchio.avi', 'video', anteprima=None), _file(2, '2.jpg', 'immagine')]
    risultato = motore.smista(files, _righe(), None)
    assert 'spenta' in risultato.messaggio
    avi = next(p for p in risultato.proposte if p.file_id == 1)
    assert 'Il browser non ha potuto leggere questo filmato (AVI)' in avi.motivo


def test_assegnazione_deterministica_vince_la_confidenza_poi_l_ordine():
    files = [_file(1, 'IMG_2.jpg', 'immagine'), _file(2, 'IMG_10.jpg', 'immagine'), _file(3, 'IMG_3.jpg', 'immagine')]
    letture = {'IMG_2.jpg': Lettura('LAAO', confidenza='media', seconda='MMODE'),
               'IMG_10.jpg': Lettura('LAAO', confidenza='alta'),
               'IMG_3.jpg': Lettura('LAAO', confidenza='media')}
    risultato, _ = _smista(files, letture)
    dove = _dove(risultato)
    assert dove[2] == 'LAAO'                    # confidenza alta
    assert dove[1] == 'MMODE' and dove[3] is None  # IMG_2 prima di IMG_3: prende la sua seconda scelta
    assert 'andata a un file piu\' probabile' in next(p for p in risultato.proposte if p.file_id == 3).motivo
    # Stesso risultato qualunque sia l'ordine in cui arrivano i file.
    for _ in range(5):
        mescolati = files[:]
        random.shuffle(mescolati)
        assert _dove(_smista(mescolati, letture)[0]) == dove


def test_ordine_di_acquisizione_riempie_il_buco_fra_due_riconosciuti():
    """Sei filmati nell'ordine del protocollo; il secondo (color, incerto per
    l'AI) sta fra DX1_B e DX2_B: l'unica riga color in mezzo e' DX1_C."""
    files = [_file(i, f'IMG_{i:04d}.mp4', 'video', c) for i, c in
             ((1, BMODE), (2, COLOR), (3, BMODE), (4, COLOR), (5, BMODE))]
    files.append(_file(6, 'IMG_0006.jpg', 'immagine'))
    letture = {'IMG_0001.mp4': Lettura('DX1_B', confidenza='alta', tracciato='2D'),
               'IMG_0002.mp4': Lettura(None),
               'IMG_0003.mp4': Lettura('DX2_B', confidenza='media', tracciato='2D'),
               'IMG_0004.mp4': Lettura('DX2_C', confidenza='alta', tracciato='2D'),
               'IMG_0005.mp4': Lettura('DX3_B', confidenza='alta', tracciato='2D'),
               'IMG_0006.jpg': Lettura('MMODE', confidenza='alta', tracciato='M')}
    risultato, _ = _smista(files, letture)
    assert _dove(risultato)[2] == 'DX1_C'
    buco = next(p for p in risultato.proposte if p.file_id == 2)
    assert buco.fonte == 'ORDINE' and not buco.sicura and 'ordine di acquisizione' in buco.motivo
    assert risultato.telemetria['segue_protocollo']
    # La lettura media in sequenza pesa un po' di piu', ma non diventa sicura.
    medio = next(p for p in risultato.proposte if p.file_id == 3)
    assert medio.confidenza == 0.75 and not medio.sicura


def test_righe_occupate_e_referto_gia_presente():
    files = [_file(1, 'r.pdf', 'pdf', anteprima=None), _file(2, '1.jpg', 'immagine')]
    risultato, lettore = _smista(files, {'1.jpg': Lettura('LAAO', confidenza='alta')},
                                 righe_occupate=frozenset({_id('LAAO')}), referto_libero=False)
    assert _dove(risultato) == {1: None, 2: None}
    assert 'LAAO' not in lettore.chiamate[0][0].candidati


def test_chiave_naturale():
    nomi = ['IMG_10.jpg', 'IMG_2.jpg', 'img_1.JPG', 'cartella/IMG_3.mp4']
    assert sorted(nomi, key=motore.chiave_naturale) == ['cartella/IMG_3.mp4', 'img_1.JPG', 'IMG_2.jpg', 'IMG_10.jpg']


# ── Lettore AI con un client finto ───────────────────────────────────────────

class ClientFinto:
    def __init__(self, risposte=None, eccezione=None):
        self.risposte = list(risposte or [])
        self.eccezione = eccezione
        self.parametri = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crea))

    def _crea(self, **parametri):
        self.parametri.append(parametri)
        if self.eccezione:
            raise self.eccezione
        return self.risposte.pop(0)


def _risposta(voci, stop='end_turn'):
    return SimpleNamespace(
        content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=json.dumps({'miniature': voci}))],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=500,
                              cache_read_input_tokens=0),
        stop_reason=stop, model='claude-opus-5')


def _da_leggere(n):
    from eco.smistamento.dati import DaLeggere
    return [DaLeggere(file_id=i, anteprima=_fotogramma(seme=i), genere='immagine', candidati=['LAAO', 'AP_PW'])
            for i in range(1, n + 1)]


def test_lettore_manda_immagini_schema_e_fallback_e_legge_la_risposta():
    client = ClientFinto([_risposta([
        {'numero': 1, 'tracciato': 'doppler pulsato', 'color_doppler': False, 'codice': 'AP_PW',
         'seconda_scelta': 'nessuna', 'confidenza': 'alta', 'motivo': 'PW sulla polmonare'},
        {'numero': 2, 'tracciato': 'bidimensionale', 'color_doppler': False, 'codice': 'DX1_B',
         'seconda_scelta': 'LAAO', 'confidenza': 'alta', 'motivo': 'fuori candidati'}])])
    lettore = LettoreClaude('claude-opus-5', client=client, prezzi={'claude-opus-5': (5.0, 25.0)}, taglio_alto=0.1)
    letture, telemetria = lettore.leggi(_da_leggere(2), _righe()[:9])
    assert letture[1].codice == 'AP_PW' and letture[1].tracciato == 'PW' and letture[1].confidenza == 'alta'
    assert letture[2].codice is None and letture[2].seconda == 'LAAO'   # DX1_B non era fra le righe possibili
    p = client.parametri[0]
    assert p['model'] == 'claude-opus-5' and p['fallbacks'] == 'default'
    assert p['output_config']['format']['type'] == 'json_schema'
    assert 'sconosciuto' in p['output_config']['format']['schema']['properties']['miniature']['items'][
        'properties']['codice']['enum']
    immagini = [b for b in p['messages'][0]['content'] if b['type'] == 'image']
    assert len(immagini) == 2
    import base64
    tagliata = Image.open(io.BytesIO(base64.b64decode(immagini[0]['source']['data'])))
    assert tagliata.size == (800, 540)                                    # via il 10 % in alto
    assert 'sconosciuto' in p['system'][0]['text'] and 'PW, CW, TDI' in p['system'][0]['text']
    assert telemetria['token_input'] == 1000 and telemetria['richieste'] == 1
    assert telemetria['costo_usd'] == pytest.approx((1000 * 5 + 200 * 25 + 500 * 5 * 1.25) / 1e6, abs=1e-4)


def test_lettore_a_gruppi_e_rifiuto_di_un_gruppo():
    client = ClientFinto([
        _risposta([{'numero': n, 'tracciato': 'bidimensionale', 'color_doppler': False, 'codice': 'LAAO',
                    'seconda_scelta': 'nessuna', 'confidenza': 'media', 'motivo': ''} for n in (1, 2)]),
        _risposta([], stop='refusal')])
    lettore = LettoreClaude('claude-opus-5', client=client, per_richiesta=2, paralleli=1)
    letture, telemetria = lettore.leggi(_da_leggere(3), _righe()[:9])
    assert set(letture) == {1, 2} and len(client.parametri) == 2
    assert telemetria['errori'] == ['rifiuto']


def test_lettore_senza_chiave_non_disponibile(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    with pytest.raises(LetturaNonDisponibile, match='non e\' configurata'):
        LettoreClaude('claude-opus-5').leggi(_da_leggere(1), _righe()[:9])


def test_lettore_chiave_rifiutata_non_disponibile_e_timeout_per_gruppo():
    import anthropic
    import httpx2
    richiesta = httpx2.Request('POST', 'https://api.anthropic.com/v1/messages')
    rifiutata = anthropic.AuthenticationError('no', response=httpx2.Response(401, request=richiesta), body=None)
    with pytest.raises(LetturaNonDisponibile, match='chiave rifiutata'):
        LettoreClaude('claude-opus-5', client=ClientFinto(eccezione=rifiutata)).leggi(_da_leggere(1), _righe()[:9])
    scaduto = anthropic.APITimeoutError(request=richiesta)
    letture, telemetria = LettoreClaude('claude-opus-5', client=ClientFinto(eccezione=scaduto)).leggi(
        _da_leggere(1), _righe()[:9])
    assert letture == {} and telemetria['errori'] == ['tempo scaduto']


def test_interpreta_scarta_numeri_fuori_gruppo():
    gruppo = _da_leggere(1)
    letture = interpreta(json.dumps({'miniature': [{'numero': 5, 'codice': 'LAAO'}, {'numero': 1, 'codice': 'LAAO',
                                                                                      'confidenza': 'boh'}]}), gruppo)
    assert list(letture) == [1] and letture[1].confidenza == 'bassa'


def test_modello_senza_fallback_non_lo_chiede():
    client = ClientFinto([_risposta([])])
    LettoreClaude('claude-sonnet-5', client=client).leggi(_da_leggere(1), _righe()[:9])
    assert 'fallbacks' not in client.parametri[0] and 'betas' not in client.parametri[0]
