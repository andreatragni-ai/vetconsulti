"""Test del caricamento della cartella intera dell'eco e del tavolo di
smistamento (consulti/views_smistamento.py, eco/smistamento/tavolo.py e
esecuzione.py). La lettura AI e' sempre finta. Le miniature hanno i loro
test in tests_anteprime.py, il protocollo stampabile in eco/tests_protocollo.py."""

import hashlib
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from consulti import caricamento, regole
from consulti.models import Allegato, CategoriaAllegato, StatoRichiesta
from consulti.tests_percorso import (MP4, PDF, _a_pezzi, _carica, _file, _t, bozza_eco, catalogo,  # noqa: F401
                                     esperto_eco, loggato)
from eco.models import ProiezioneCaricata, PropostaSmistamento, Smistamento, StatoSmistamento
from eco.smistamento import esecuzione, tavolo
from eco.smistamento.dati import Lettura, LetturaNonDisponibile


def _jpeg(larghezza=1200, altezza=900, colore=(90, 90, 90)):
    uscita = io.BytesIO()
    Image.new('RGB', (larghezza, altezza), colore).save(uscita, 'JPEG')
    return uscita.getvalue()


def _cartella(client, richiesta, nome, contenuto, anteprima=None, percorso=None, modificato_il=None):
    dati = {'slot': 'cartella', 'file': SimpleUploadedFile(nome, contenuto),
            'percorso': percorso or f'Esame Fido/{nome}'}
    if modificato_il:
        dati['modificato_il'] = str(modificato_il)
    if anteprima is not None:
        dati['anteprima'] = SimpleUploadedFile('anteprima.jpg', anteprima, content_type='image/jpeg')
    return client.post(reverse('consulti:carica_allegato', args=[richiesta.pk]), dati, HTTP_ACCEPT='application/json')


def _allegato(richiesta, nome):
    return richiesta.allegati.get(nome_originale=nome)


@pytest.fixture
def esame_caricato(loggato, bozza_eco):
    """Il referto, tre filmati e un'immagine dalla cartella, tutti con miniatura."""
    assert _cartella(loggato, bozza_eco, 'referto.pdf', PDF).status_code == 200
    for nome in ('IMG_0001.mp4', 'IMG_0002.mp4', 'IMG_0003.mp4'):
        assert _cartella(loggato, bozza_eco, nome, MP4 + nome.encode(), anteprima=_jpeg()).status_code == 200
    assert _cartella(loggato, bozza_eco, 'IMG_0004.jpg', _jpeg(colore=(80, 80, 81))).status_code == 200
    return bozza_eco


class LettoreFinto:
    """Legge «per nome del file»: {nome: Lettura}."""

    def __init__(self, per_nome=None, errore=None):
        self.per_nome = per_nome or {}
        self.errore = errore

    def leggi(self, da_leggere, righe):
        if self.errore:
            raise self.errore
        nomi = dict(Allegato.objects.filter(pk__in=[d.file_id for d in da_leggere]).values_list('pk', 'nome_originale'))
        return ({d.file_id: self.per_nome[nomi[d.file_id]] for d in da_leggere if nomi[d.file_id] in self.per_nome},
                {'token_input': 1234, 'token_output': 56, 'costo_usd': 0.01, 'errori': []})


@pytest.fixture
def ai_finta(monkeypatch):
    def installa(per_nome=None, errore=None):
        lettore = LettoreFinto(per_nome, errore)
        monkeypatch.setattr('eco.smistamento.lettore.da_settings', lambda: lettore)
        return lettore
    return installa


def _avvia(client, richiesta, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        risposta = client.post(reverse('consulti:smistamento_avvia', args=[richiesta.pk]),
                               HTTP_ACCEPT='application/json')
    assert risposta.status_code == 200
    return Smistamento.objects.get(pk=risposta.json()['smistamento'])


# ── Zona unica: la cartella ──────────────────────────────────────────────────

def test_cartella_n_file_nascono_da_smistare_senza_proiezioni(loggato, bozza_eco):
    assert _cartella(loggato, bozza_eco, 'referto.pdf', PDF).status_code == 200
    assert _cartella(loggato, bozza_eco, 'IMG_0001.mp4', MP4, anteprima=_jpeg(1600, 1200),
                     modificato_il=1757600000000).status_code == 200
    assert _cartella(loggato, bozza_eco, 'IMG_0002.jpg', _jpeg()).status_code == 200
    risposta = _a_pezzi(loggato, bozza_eco, 'IMG_0003.mov', MP4 * 20, 'cartella', percorso='Esame Fido/IMG_0003.mov')
    assert risposta.status_code == 200, risposta.content
    # File di sistema e formati inutili: il browser li scarta, e il server comunque li rifiuta.
    for nome in ('.DS_Store', 'Thumbs.db', 'note.docx'):
        r = _cartella(loggato, bozza_eco, nome, b'x')
        assert r.status_code == 400 and 'non e\' un file dell\'esame' in r.json()['errore']
    categorie = dict(bozza_eco.allegati.values_list('nome_originale', 'categoria'))
    assert categorie == {'referto.pdf': CategoriaAllegato.ALTRO, 'IMG_0001.mp4': CategoriaAllegato.ECO_CLIP,
                         'IMG_0002.jpg': CategoriaAllegato.ECO_STATICA, 'IMG_0003.mov': CategoriaAllegato.ECO_CLIP}
    assert not ProiezioneCaricata.objects.exists()
    proposte = {p.allegato.nome_originale: p for p in PropostaSmistamento.objects.select_related('allegato')}
    assert all(p.da_smistare for p in proposte.values()) and len(proposte) == 4
    assert proposte['IMG_0001.mp4'].percorso_originale == 'Esame Fido/IMG_0001.mp4'
    assert proposte['IMG_0001.mp4'].modificato_il == 1757600000000
    # Anteprime: quella del browser normalizzata a 800 px, quella dell'immagine fatta dal server.
    with Image.open(_allegato(bozza_eco, 'IMG_0001.mp4').anteprima.path) as im:
        assert im.size == (800, 600) and im.format == 'JPEG'
    assert _allegato(bozza_eco, 'IMG_0002.jpg').anteprima
    assert not _allegato(bozza_eco, 'IMG_0003.mov').anteprima       # a pezzi senza miniatura: nessuna
    # La regola di invio non vede nulla: il referto e le righe sono ancora da confermare.
    assert 'il referto dell\'ecografo' in regole.perche_non_puoi_inviare(bozza_eco)


def test_cartella_lo_stesso_file_non_si_duplica(loggato, bozza_eco):
    assert _cartella(loggato, bozza_eco, 'IMG_0001.mp4', MP4).status_code == 200
    r = _cartella(loggato, bozza_eco, 'copia.mp4', MP4)
    assert r.status_code == 409 and r.json()['gia_presente']
    contenuto = MP4 * 20
    assert _a_pezzi(loggato, bozza_eco, 'grande.mp4', contenuto, 'cartella').status_code == 200
    stato = loggato.get(reverse('consulti:upload_stato', args=[bozza_eco.pk]),
                        {'impronta': hashlib.sha256(contenuto).hexdigest(), 'slot': 'cartella', 'nome': 'g2.mp4',
                         'dimensione': len(contenuto)})
    assert stato.status_code == 409 and stato.json()['gia_presente']
    assert bozza_eco.allegati.count() == 2


def test_cartella_solo_per_l_eco(loggato, mondo, crea_bozza):
    ecg = crea_bozza(loggato, 'ECG', mondo.ref)
    r = _cartella(loggato, ecg, 'IMG_0001.mp4', MP4)
    assert r.status_code == 400 and 'non c\'entra' in r.json()['errore']
    assert loggato.post(reverse('consulti:smistamento_avvia', args=[ecg.pk])).status_code == 404


def test_smistamento_senza_ai_si_ferma_al_formato(loggato, esame_caricato, django_capture_on_commit_callbacks):
    s = _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    assert s.stato == StatoSmistamento.FATTO and 'spenta' in s.messaggio and not s.lettura_ai
    referto = PropostaSmistamento.objects.get(allegato__nome_originale='referto.pdf')
    assert referto.referto and referto.sicura
    assert PropostaSmistamento.objects.filter(proiezione__isnull=False).count() == 0
    assert not ProiezioneCaricata.objects.exists()
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[esame_caricato.pk])))
    assert 'Confermo lo smistamento' in pagina and 'Da smistare' in pagina and 'spenta' in pagina
    assert esame_caricato.audit.filter(azione='SMISTAMENTO_AVVIATO').exists()


def test_smistamento_con_ai_propone_e_non_scrive(loggato, esame_caricato, catalogo, ai_finta,
                                                django_capture_on_commit_callbacks):
    ai_finta({'IMG_0001.mp4': Lettura('PDC', confidenza='alta', tracciato='2D', motivo='quattro camere da destra'),
              'IMG_0002.mp4': Lettura('AP4', confidenza='media', tracciato='2D', motivo='apicale'),
              'IMG_0003.mp4': Lettura(None, motivo='fuori fuoco'),
              'IMG_0004.jpg': Lettura('PDS', confidenza='alta', tracciato='2D', motivo='base del cuore')})
    s = _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    assert s.stato == StatoSmistamento.FATTO and s.lettura_ai and s.telemetria['token_input'] == 1234
    dove = {p.allegato.nome_originale: (p.proiezione.codice if p.proiezione else None, p.sicura, p.fonte)
            for p in PropostaSmistamento.objects.select_related('allegato', 'proiezione')}
    assert dove['IMG_0001.mp4'] == ('PDC', True, 'AI')
    assert dove['IMG_0002.mp4'] == ('AP4', False, 'AI')
    assert dove['IMG_0003.mp4'] == (None, False, '')
    assert dove['IMG_0004.jpg'] == ('PDS', True, 'AI')
    # Nulla e' confermato: nessuna ProiezioneCaricata, e la regola di invio lo dice.
    assert not ProiezioneCaricata.objects.exists()
    # Il referto dell'ecografo e' ancora da smistare: quello blocca ancora.
    assert regole.perche_non_puoi_inviare(esame_caricato) == 'Manca il referto dell\'ecografo (PDF).'
    # Lo stato, a lavoro finito, fa ricaricare la pagina.
    r = loggato.get(reverse('consulti:smistamento_stato', args=[esame_caricato.pk]))
    assert r.status_code == 200 and r['HX-Refresh'] == 'true'
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[esame_caricato.pk])))
    assert 'Sicuro' in pagina and 'Da verificare' in pagina and 'quattro camere da destra' in pagina
    assert 'fuori fuoco' in pagina
    # Conferma: le proposte diventano ProiezioneCaricata e il PDF il referto.
    r = loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    assert r.status_code == 302
    assert sorted(ProiezioneCaricata.objects.values_list('proiezione__codice', flat=True)) == ['AP4', 'PDC', 'PDS']
    assert _allegato(esame_caricato, 'referto.pdf').categoria == CategoriaAllegato.ECO_REFERTO_PDF
    assert regole.perche_non_puoi_inviare(esame_caricato) is None
    assert tavolo.modifiche_da_confermare(esame_caricato) == 0
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[esame_caricato.pk])))
    assert 'Confermo lo smistamento' not in pagina and 'Confermato' in pagina
    assert loggato.post(reverse('consulti:invia', args=[esame_caricato.pk])).status_code == 302
    esame_caricato.refresh_from_db()
    assert esame_caricato.stato == StatoRichiesta.INVIATA


def test_smistamento_ai_non_disponibile_o_rotto(loggato, esame_caricato, ai_finta,
                                                django_capture_on_commit_callbacks):
    ai_finta(errore=LetturaNonDisponibile('La lettura automatica non e\' disponibile (chiave rifiutata).'))
    s = _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    assert s.stato == StatoSmistamento.FATTO and 'chiave rifiutata' in s.messaggio
    assert PropostaSmistamento.objects.get(allegato__nome_originale='referto.pdf').referto
    ai_finta(errore=RuntimeError('guasto'))
    s = _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    assert s.stato == StatoSmistamento.ERRORE and 'metti tu i file' in s.messaggio
    # Le proposte di prima restano.
    assert PropostaSmistamento.objects.get(allegato__nome_originale='referto.pdf').referto


def test_smistamento_rifatto_non_tocca_scelte_a_mano_e_confermate(loggato, esame_caricato, catalogo, ai_finta,
                                                                  django_capture_on_commit_callbacks):
    ai_finta({'IMG_0001.mp4': Lettura('PDC', confidenza='alta', tracciato='2D'),
              'IMG_0002.mp4': Lettura('AP4', confidenza='alta', tracciato='2D')})
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    tavolo.sposta(esame_caricato, _allegato(esame_caricato, 'IMG_0003.mp4'), f'proiezione:{catalogo["pd_facoltativa"].pk}')
    ai_finta({'IMG_0001.mp4': Lettura('AP4', confidenza='alta', tracciato='2D'),
              'IMG_0002.mp4': Lettura('PDC', confidenza='alta', tracciato='2D'),
              'IMG_0003.mp4': Lettura('PDC', confidenza='alta', tracciato='2D')})
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    dove = dict(PropostaSmistamento.objects.filter(proiezione__isnull=False)
                .values_list('allegato__nome_originale', 'proiezione__codice'))
    assert dove == {'IMG_0001.mp4': 'AP4', 'IMG_0002.mp4': 'PDC', 'IMG_0003.mp4': 'PDF'}


# ── Tavolo: sposta, scambia, conferma ────────────────────────────────────────

def _sposta(client, richiesta, allegato, destinazione, json=True):
    return client.post(reverse('consulti:smistamento_sposta', args=[richiesta.pk]),
                       {'allegato': allegato.pk, 'destinazione': destinazione},
                       **({'HTTP_ACCEPT': 'application/json'} if json else {}))


def test_sposta_scambia_e_rispetta_il_tipo_di_file(loggato, esame_caricato, catalogo):
    c1, c2 = _allegato(esame_caricato, 'IMG_0001.mp4'), _allegato(esame_caricato, 'IMG_0002.mp4')
    img, pdf = _allegato(esame_caricato, 'IMG_0004.jpg'), _allegato(esame_caricato, 'referto.pdf')
    ap4, pdc, pds = catalogo['ap_clip'], catalogo['pd_clip'], catalogo['pd_statica']
    assert _sposta(loggato, esame_caricato, c1, f'proiezione:{ap4.pk}').json()['ancora'] == f'proiezione_{ap4.pk}'
    assert _sposta(loggato, esame_caricato, c2, f'proiezione:{pdc.pk}').status_code == 200
    # Scambio: c1 va dove era c2, c2 dove era c1.
    _sposta(loggato, esame_caricato, c1, f'proiezione:{pdc.pk}')
    dove = dict(PropostaSmistamento.objects.filter(proiezione__isnull=False)
                .values_list('allegato__nome_originale', 'proiezione__codice'))
    assert dove == {'IMG_0001.mp4': 'PDC', 'IMG_0002.mp4': 'AP4'}
    assert PropostaSmistamento.objects.get(allegato=c2).motivo.startswith('Scambiato con')
    # Un'immagine non va in una riga filmato, un filmato non e' il referto.
    r = _sposta(loggato, esame_caricato, img, f'proiezione:{ap4.pk}')
    assert r.status_code == 400 and 'va un filmato' in r.json()['errore']
    r = _sposta(loggato, esame_caricato, c1, 'referto')
    assert r.status_code == 400 and 'e\' un PDF' in r.json()['errore']
    assert _sposta(loggato, esame_caricato, pdf, 'referto').status_code == 200
    # Scambio impossibile: l'immagine prende la riga di un filmato? No; il
    # filmato che occupa una riga immagine non esiste. Un file che non puo'
    # tornare dov'era l'altro finisce da smistare.
    _sposta(loggato, esame_caricato, img, f'proiezione:{pds.pk}')
    _sposta(loggato, esame_caricato, img, 'nessuna')
    assert PropostaSmistamento.objects.get(allegato=img).da_smistare
    # Senza JavaScript: POST normale e ritorno alla riga.
    r = _sposta(loggato, esame_caricato, img, f'proiezione:{pds.pk}', json=False)
    assert r.status_code == 302 and r['Location'].endswith(f'#proiezione_{pds.pk}')
    assert not ProiezioneCaricata.objects.exists()


def test_filmato_libero_si_conferma_anche_senza_nota(loggato, esame_caricato, catalogo):
    """Un filmato libero non e' obbligatorio, e nemmeno la sua nota (12/09):
    pretenderla bloccava la conferma e rendeva obbligatorio il facoltativo."""
    libero = catalogo['libero']
    _sposta(loggato, esame_caricato, _allegato(esame_caricato, 'IMG_0003.mp4'), f'proiezione:{libero.pk}')
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    pc = ProiezioneCaricata.objects.get(proiezione=libero)
    assert pc.nota == ''
    # La nota resta possibile, e si salva.
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]),
                 {f'nota_{libero.pk}': 'versamento pericardico?'})
    pc.refresh_from_db()
    assert pc.nota == 'versamento pericardico?'


def test_conferma_riallinea_dopo_uno_spostamento(loggato, esame_caricato, catalogo):
    c1 = _allegato(esame_caricato, 'IMG_0001.mp4')
    _sposta(loggato, esame_caricato, c1, f'proiezione:{catalogo["ap_clip"].pk}')
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    assert ProiezioneCaricata.objects.get().allegato == c1
    _sposta(loggato, esame_caricato, c1, f'proiezione:{catalogo["pd_clip"].pk}')
    assert tavolo.modifiche_da_confermare(esame_caricato) == 1
    assert ProiezioneCaricata.objects.get().proiezione == catalogo['ap_clip']   # finche' non si conferma
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    assert list(ProiezioneCaricata.objects.values_list('proiezione__codice', flat=True)) == ['PDC']
    assert esame_caricato.audit.filter(azione='SMISTAMENTO_CONFERMATO').count() == 2


def test_righe_vuote_avvisano_ma_non_bloccano(loggato, esame_caricato, catalogo):
    """Dal 24/09/2026 le proiezioni mancanti non fermano piu' l'invio: il
    passo 3 lascia andare avanti e lo dice, e l'invio pretende la spunta."""
    _sposta(loggato, esame_caricato, _allegato(esame_caricato, 'referto.pdf'), 'referto')
    _sposta(loggato, esame_caricato, _allegato(esame_caricato, 'IMG_0001.mp4'), f'proiezione:{catalogo["ap_clip"].pk}')
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[esame_caricato.pk])))
    assert 'disabled aria-describedby="perche-fermo"' not in pagina
    assert 'la refertazione potrebbe non essere possibile' in pagina

    # Senza spunta non parte...
    loggato.post(reverse('consulti:invia', args=[esame_caricato.pk]))
    esame_caricato.refresh_from_db()
    assert esame_caricato.stato == StatoRichiesta.BOZZA
    # ...con la spunta si', e resta scritto che era incompleta.
    loggato.post(reverse('consulti:invia', args=[esame_caricato.pk]), {'presa_atto': 'si'})
    esame_caricato.refresh_from_db()
    assert esame_caricato.stato == StatoRichiesta.INVIATA and esame_caricato.inviata_incompleta
    evento = esame_caricato.audit.filter(azione='INVIATA').last()
    assert evento.dettaglio['incompleta'] and 'LA/Ao' in ' '.join(evento.dettaglio['mancanti'])


def test_caricamento_riga_per_riga_resta_ed_e_gia_confermato(loggato, esame_caricato, catalogo):
    c1 = _allegato(esame_caricato, 'IMG_0001.mp4')
    _sposta(loggato, esame_caricato, c1, f'proiezione:{catalogo["ap_clip"].pk}')
    # Un file lasciato sulla riga prende il posto (e la proposta di prima torna da smistare).
    assert _carica(loggato, esame_caricato, 'proiezione', _file('diretto.mp4', MP4 + b'd'),
                   proiezione=catalogo['ap_clip'].pk).status_code == 200
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[esame_caricato.pk])))
    diretto = PropostaSmistamento.objects.get(allegato__nome_originale='diretto.mp4')
    assert diretto.proiezione == catalogo['ap_clip'] and diretto.fonte == 'RIGA'
    assert PropostaSmistamento.objects.get(allegato=c1).da_smistare
    assert 'Confermato' in pagina


def test_tavolo_solo_per_chi_ha_aperto_la_richiesta(client, esame_caricato, mondo, esperto_eco):
    allegato = _allegato(esame_caricato, 'IMG_0001.mp4')
    for utente in (mondo.estraneo, esperto_eco.user, mondo.staff):
        client.force_login(utente)
        assert client.post(reverse('consulti:smistamento_avvia', args=[esame_caricato.pk])).status_code == 404
        assert client.get(reverse('consulti:smistamento_stato', args=[esame_caricato.pk])).status_code == 404
        assert _sposta(client, esame_caricato, allegato, 'nessuna').status_code == 404
        assert client.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk])).status_code == 404


def test_pagina_con_zona_cartella_e_protocollo_linkato(loggato, bozza_eco):
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[bozza_eco.pk])))
    assert 'Trascina qui la cartella dell\'esame, oppure scegli i file' in pagina
    assert 'webkitdirectory' in pagina and reverse('eco:protocollo') in pagina
    esame = _t(loggato.get(reverse('consulti:passo_esame', args=[bozza_eco.pk])))
    assert reverse('eco:protocollo') in esame


def test_smistamento_in_corso_si_mostra_e_non_si_raddoppia(loggato, esame_caricato, settings):
    settings.CONSULTI_SMISTAMENTO_IN_THREAD = True
    from unittest import mock
    with mock.patch('eco.smistamento.esecuzione.pianifica'):
        s1 = esecuzione.avvia(esame_caricato, None)
        s2 = esecuzione.avvia(esame_caricato, None)
    assert s1.pk == s2.pk
    r = loggato.get(reverse('consulti:smistamento_stato', args=[esame_caricato.pk]))
    assert 'Sto smistando 5 file' in _t(r) and 'hx-trigger="every 2s"' in _t(r)
    assert 'Sto smistando' in _t(loggato.get(reverse('consulti:passo_carica', args=[esame_caricato.pk])))


def test_categoria_per_la_cartella():
    assert caricamento.categoria_per('cartella', 'a.PDF') == CategoriaAllegato.ALTRO
    assert caricamento.categoria_per('cartella', 'a.avi') == CategoriaAllegato.ECO_CLIP
    assert caricamento.categoria_per('cartella', 'a.dcm') == CategoriaAllegato.ECO_CLIP
    assert caricamento.categoria_per('cartella', 'a.jpeg') == CategoriaAllegato.ECO_STATICA
