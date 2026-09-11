"""Test della richiesta guidata (F2): i quattro passi, il caricamento per
tipo di esame con la categoria dedotta, le proiezioni eco (una riga = un
file, filmati liberi con nota, finestre acustiche), i permessi, e il
criterio di «fatto» di F2 nel backlog: un richiedente di `seed_demo`
completa dall'interfaccia un ECG, un Holter e un'eco, e parte l'email."""

import hashlib
import html
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from accounts.models import CompetenzaRefertatore, Refertatore, Richiedente
from consulti import caricamento, percorso, regole, upload_chunk
from consulti.models import Allegato, CategoriaAllegato, Paziente, Richiesta, StatoRichiesta
from core.tipi import TipoEsame
from eco.models import Finestra, ImmagineRiferimento, ProiezioneCaricata, ProiezioneCatalogo, TipoMedia
from listino.models import Supplemento, TipoSupplemento

PDF = b'%PDF-1.4 prova\n%%EOF\n'
PNG = b'\x89PNG\r\n\x1a\n finta'
MP4 = b'\x00\x00\x00\x18ftypmp42 finto filmato'


def _t(risposta):
    """Il testo della pagina con le entita' sciolte (l'apostrofo arriva come &#x27;)."""
    return html.unescape(risposta.content.decode())


def _file(nome, contenuto=PDF, mime=''):
    return SimpleUploadedFile(nome, contenuto, content_type=mime)


def _carica(client, richiesta, slot, file, json=True, **extra):
    dati = {'slot': slot, 'file': file, **extra}
    intestazioni = {'HTTP_ACCEPT': 'application/json'} if json else {}
    return client.post(reverse('consulti:carica_allegato', args=[richiesta.pk]), dati, **intestazioni)


def _a_pezzi(client, richiesta, nome, contenuto, slot, **zona):
    """Il caricamento a pezzi come lo fa carica.js: stato (con la zona),
    due pezzi, concludi. Ritorna la risposta di concludi."""
    impronta = hashlib.sha256(contenuto).hexdigest()
    stato = client.get(reverse('consulti:upload_stato', args=[richiesta.pk]),
                       {'impronta': impronta, 'slot': slot, 'nome': nome, 'dimensione': len(contenuto), **zona})
    if stato.status_code != 200:
        return stato
    meta = len(contenuto) // 2
    for offset, pezzo in ((0, contenuto[:meta]), (meta, contenuto[meta:])):
        r = client.post(reverse('consulti:upload_pezzo', args=[richiesta.pk]),
                        {'impronta': impronta, 'offset': str(offset), 'pezzo': SimpleUploadedFile('p', pezzo)})
        assert r.status_code == 200, r.content
    return client.post(reverse('consulti:upload_concludi', args=[richiesta.pk]),
                       {'impronta': impronta, 'nome': nome, 'slot': slot, **zona})


# ── Fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture
def esperto_eco(mondo):
    r = Refertatore.objects.create(
        user=User.objects.create_user('eco', 'eco@x.it', 'pw', first_name='Laura', last_name='Monti'),
        titolo='Dott.ssa', specializzazione='Ecocardiografia')
    CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=TipoEsame.ECO, referente=True,
                                         prezzo_personalizzato=Decimal('85.00'), tempo_risposta_ore=24,
                                         accetta_urgenze=True)
    return r


@pytest.fixture
def catalogo(db):
    """Due finestre con obbligatorie filmato/immagine, una facoltativa, un
    filmato libero. Gli `ordine` sono al contrario apposta: conta la finestra."""
    crea = ProiezioneCatalogo.objects.create
    return {
        'ap_clip': crea(codice='AP4', nome='Apicale 4 camere', finestra=Finestra.PARASTERNALE_SINISTRA,
                        tipo_media=TipoMedia.CLIP, obbligatoria=True, ordine=1),
        'pd_statica': crea(codice='PDS', nome='LA/Ao', finestra=Finestra.PARASTERNALE_DESTRA,
                           tipo_media=TipoMedia.STATICA, obbligatoria=True, ordine=2),
        'pd_clip': crea(codice='PDC', nome='Asse lungo 4 camere', finestra=Finestra.PARASTERNALE_DESTRA,
                        tipo_media=TipoMedia.CLIP, obbligatoria=True, ordine=3),
        'pd_facoltativa': crea(codice='PDF', nome='Arteria polmonare', finestra=Finestra.PARASTERNALE_DESTRA,
                               tipo_media=TipoMedia.CLIP, obbligatoria=False, ordine=4),
        'libero': crea(codice='LIB1', nome='Filmato libero 1', tipo_media=TipoMedia.CLIP, libera=True, ordine=0),
        'libero2': crea(codice='LIB2', nome='Filmato libero 2', tipo_media=TipoMedia.CLIP, libera=True, ordine=1),
    }


@pytest.fixture
def loggato(client, mondo):
    client.force_login(mondo.richiedente.user)
    return client


@pytest.fixture
def bozza_eco(loggato, esperto_eco, catalogo, crea_bozza):
    return crea_bozza(loggato, 'ECO', esperto_eco, paziente={'nome': 'Luna', 'specie': 'GATTO', 'sesso': 'FS'})


@pytest.fixture
def bozza_ecg(loggato, mondo, crea_bozza):
    return crea_bozza(loggato, 'ECG', mondo.ref, paziente={'nome': 'Bruno'})


# ── Criterio di fatto di F2 ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_criterio_di_fatto_f2(client, settings):
    """gbianchi (seed_demo) completa dall'interfaccia un ECG con un PDF, un
    Holter con il referto e un'eco con referto e tutte le proiezioni
    obbligatorie; per ciascuno parte l'email «caso arrivato»."""
    settings.DEBUG = True
    call_command('seed_demo', stdout=StringIO())
    gbianchi = User.objects.get(username='gbianchi')
    rferrari = Refertatore.objects.get(user__username='rferrari')
    lmonti = Refertatore.objects.get(user__username='lmonti')
    client.force_login(gbianchi)
    mail.outbox.clear()

    def passi_1_2(nome, tipo, esperto, **esame):
        client.post(reverse('consulti:nuova'), {'nome': nome, 'specie': 'CANE', 'sesso': 'M', 'eta_anni': '7'})
        risposta = client.post(reverse('consulti:nuova_esame'), {
            'tipo_esame': tipo, 'refertatore': esperto.pk, 'quesito': f'Quesito per {nome}', 'azione': 'avanti',
            **esame})
        richiesta = Richiesta.objects.filter(paziente__nome=nome).get()
        assert risposta.status_code == 302 and risposta.url == reverse('consulti:passo_carica', args=[richiesta.pk])
        return richiesta

    def invia(richiesta):
        riepilogo = _t(client.get(reverse('consulti:passo_riepilogo', args=[richiesta.pk])))
        assert f'Invia a {richiesta.refertatore}' in riepilogo and 'disabled' not in riepilogo.split('Invia a')[0][-80:]
        risposta = client.post(reverse('consulti:invia', args=[richiesta.pk]), follow=True)
        richiesta.refresh_from_db()
        assert richiesta.stato == StatoRichiesta.INVIATA
        pagina = _t(risposta)
        nome = richiesta.refertatore.user.get_full_name()
        assert f'{nome} ricevera\' una email con il caso' in pagina and 'quando il referto e\' pronto' in pagina

    # ECG: un PDF nella zona del tracciato.
    ecg = passi_1_2('Rocky', 'ECG', rferrari)
    assert _carica(client, ecg, 'ecg', _file('tracciato.pdf')).status_code == 200
    invia(ecg)

    # Holter: il referto del software.
    holter = passi_1_2('Birba', 'HOLTER', rferrari)
    assert _carica(client, holter, 'holter_referto', _file('holter.pdf')).status_code == 200
    invia(holter)

    # Eco: referto dell'ecografo e ogni proiezione obbligatoria del catalogo,
    # i filmati a pezzi (come fa carica.js) e le immagini con la POST semplice.
    eco = passi_1_2('Nuvola', 'ECO', lmonti, urgenza='on')
    assert _carica(client, eco, 'eco_referto', _file('referto_eco.pdf')).status_code == 200
    obbligatorie = list(ProiezioneCatalogo.objects.filter(obbligatoria=True, attiva=True))
    assert len(obbligatorie) == 25  # il catalogo di Andre, eco/catalogo/catalogo_eco.json
    for p in obbligatorie:
        if p.tipo_media == TipoMedia.STATICA:
            r = _carica(client, eco, 'proiezione', _file(f'{p.codice}.png', PNG, 'image/png'), proiezione=p.pk)
        else:
            r = _a_pezzi(client, eco, f'{p.codice}.mp4', MP4 * 50, 'proiezione', proiezione=p.pk)
        assert r.status_code == 200, r.content
    assert regole.perche_non_puoi_inviare(eco) is None
    invia(eco)

    arrivati = [m for m in mail.outbox if 'Nuovo caso' in m.subject]
    assert [m.to for m in arrivati] == [['rferrari@esempio.it'], ['rferrari@esempio.it'], ['lmonti@esempio.it']]
    assert 'Rocky · Elettrocardiogramma' in arrivati[0].subject and ecg.codice in arrivati[0].subject
    assert 'Birba · Holter' in arrivati[1].subject
    assert 'URGENTE' in arrivati[2].subject and 'Nuvola · Ecocardiografia' in arrivati[2].subject
    assert set(eco.proiezioni.values_list('proiezione_id', flat=True)) >= {p.id for p in obbligatorie}


# ── Passo 1: paziente ────────────────────────────────────────────────────────

def test_passo_1_nome_specie_sesso_obbligatori(loggato):
    risposta = loggato.post(reverse('consulti:nuova'), {'razza': 'Boxer'})
    assert risposta.status_code == 200
    pagina = _t(risposta)
    assert 'Scrivi il nome del paziente.' in pagina and 'Scegli la specie.' in pagina
    assert 'Scegli il sesso' in pagina
    assert percorso.SESSIONE_PAZIENTE not in loggato.session


def test_passo_1_etichette_umane_e_niente_motivo(loggato):
    pagina = _t(loggato.get(reverse('consulti:nuova')))
    for etichetta in ('Nome del paziente', 'Data di nascita', 'Eta\' in anni', 'Peso (kg)',
                      'Cognome del proprietario', 'Basta il cognome', 'Non conosci la data?'):
        assert etichetta in pagina, etichetta
    assert 'Eta testo' not in pagina and 'Peso kg' not in pagina


def test_passo_1_specie_solo_cane_e_gatto(loggato):
    pagina = _t(loggato.get(reverse('consulti:nuova')))
    assert 'value="CANE"' in pagina and 'value="GATTO"' in pagina
    assert 'value="ALTRO"' not in pagina and 'Quale specie?' not in pagina and 'specie_altro' not in pagina
    risposta = loggato.post(reverse('consulti:nuova'), {'nome': 'Nemo', 'specie': 'ALTRO', 'sesso': 'M'})
    assert risposta.status_code == 200 and 'scegli una delle due specie' in _t(risposta)
    assert percorso.SESSIONE_PAZIENTE not in loggato.session
    assert [valore for valore, _ in Paziente._meta.get_field('specie').choices] == ['CANE', 'GATTO']


def test_passo_1_eta_una_delle_due(loggato, mondo, crea_bozza):
    risposta = loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M',
                                                        'data_nascita': '2020-01-01', 'eta_anni': '6'})
    assert risposta.status_code == 200 and 'Basta una delle due' in _t(risposta)
    r = crea_bozza(loggato, 'ECG', mondo.ref, paziente={
        'nome': 'Coccola', 'specie': 'CANE', 'eta_anni': '8', 'peso_kg': '12,5'})
    assert r.paziente.eta_testo == '8 anni' and r.paziente.peso_kg == Decimal('12.50')
    r2 = crea_bozza(loggato, 'ECG', mondo.ref, paziente={'nome': 'Nemo', 'specie': 'GATTO', 'eta_anni': '1'})
    assert r2.paziente.specie == 'GATTO' and r2.paziente.eta_testo == '1 anno'


def test_passo_1_data_nel_futuro_rifiutata(loggato):
    domani = (date.today() + timedelta(days=1)).isoformat()
    risposta = loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M',
                                                        'data_nascita': domani})
    assert 'nel futuro' in _t(risposta)


def test_la_bozza_nasce_solo_alla_fine_del_passo_2(loggato, mondo):
    loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M'})
    assert not Richiesta.objects.exists()
    assert loggato.session[percorso.SESSIONE_PAZIENTE]['nome'] == 'Fido'
    # Senza passo 1 il passo 2 rimanda al passo 1.
    loggato.get(reverse('consulti:nuova') + '?ricomincia=1')
    risposta = loggato.get(reverse('consulti:nuova_esame'))
    assert risposta.status_code == 302 and risposta.url == reverse('consulti:nuova')


# ── Passo 2: esame ed esperto ────────────────────────────────────────────────

def _passo_2(client, **dati):
    client.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M'})
    return client.post(reverse('consulti:nuova_esame'), {'azione': 'avanti', **dati})


def test_passo_2_quesito_obbligatorio(loggato, mondo):
    risposta = _passo_2(loggato, tipo_esame='ECG', refertatore=mondo.ref.pk, quesito='  ')
    assert risposta.status_code == 200 and 'Scrivi il quesito' in _t(risposta)
    assert not Richiesta.objects.exists()


def test_passo_2_esperto_obbligatorio_e_non_referente_rifiutato(loggato, mondo, esperto_eco):
    risposta = _passo_2(loggato, tipo_esame='ECG', quesito='x')
    assert 'Scegli l\'esperto' in _t(risposta)
    risposta = _passo_2(loggato, tipo_esame='ECG', refertatore=esperto_eco.pk, quesito='x')
    assert 'non referta il tipo di esame scelto' in _t(risposta)
    assert not Richiesta.objects.exists()


def test_passo_2_esperto_assente_si_vede_ma_non_si_sceglie(loggato, mondo):
    mondo.ref2.assente_dal = date.today() - timedelta(days=1)
    mondo.ref2.assente_al = date.today() + timedelta(days=5)
    mondo.ref2.save()
    schede = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'ECG'}))
    assert 'Bruno Test' in schede and 'rientra il' in schede
    assert f'id="esperto-{mondo.ref2.pk}" value="{mondo.ref2.pk}" disabled' in schede
    assert f'id="esperto-{mondo.ref.pk}" value="{mondo.ref.pk}" required' in schede
    risposta = _passo_2(loggato, tipo_esame='ECG', refertatore=mondo.ref2.pk, quesito='x')
    assert risposta.status_code == 200 and 'e\' assente fino al' in _t(risposta)
    assert not Richiesta.objects.exists()


def test_passo_2_schede_esperti_solo_referenti_con_prezzo_e_urgenza(loggato, mondo, esperto_eco):
    Supplemento.objects.create(codice='URGENZA', descrizione='Urgenza', tipo=TipoSupplemento.URGENZA,
                               importo=Decimal('25.00'), valido_dal=date(2020, 1, 1))
    eco = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'ECO'}))
    assert 'Laura Monti' in eco and 'Anna Test' not in eco
    assert '€ 103,70' in eco and 'imponibile € 85,00' in eco and 'Risposta in 24 ore' in eco
    urgente = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'ECO', 'urgenza': '1'}))
    assert '€ 134,20' in urgente and 'supplemento urgenza di € 25,00' in urgente
    nessuno = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'HOLTER'}))
    assert 'non c\'e\' ancora nessun esperto' in nessuno


def test_passo_2_tre_schede_del_tipo_e_testi(loggato, mondo):
    loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M'})
    pagina = _t(loggato.get(reverse('consulti:nuova_esame')))
    for testo in ('Elettrocardiogramma', 'Holter', 'Ecocardiografia', 'Quesito per il collega', 'Anamnesi',
                  'Terapia in corso', 'Urgente'):
        assert testo in pagina, testo
    assert 'Motivo' not in pagina


def test_passo_2_non_cambia_tipo_con_file_gia_caricati(loggato, bozza_ecg, mondo, esperto_eco):
    Allegato.da_upload(bozza_ecg, _file('t.pdf'), CategoriaAllegato.ECG_PDF)
    risposta = loggato.post(reverse('consulti:passo_esame', args=[bozza_ecg.pk]), {
        'tipo_esame': 'ECO', 'refertatore': esperto_eco.pk, 'quesito': 'x', 'azione': 'avanti'})
    assert risposta.status_code == 200 and 'rimuovili dal passo' in _t(risposta)
    bozza_ecg.refresh_from_db()
    assert bozza_ecg.tipo_esame == 'ECG'


# ── Tornare indietro e riprendere ────────────────────────────────────────────

def test_indietro_dal_passo_2_non_perde_nulla(loggato, mondo):
    loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M', 'razza': 'Boxer'})
    risposta = loggato.post(reverse('consulti:nuova_esame'), {
        'tipo_esame': 'ECG', 'refertatore': mondo.ref.pk, 'quesito': 'Mezzo scritto', 'azione': 'indietro'})
    assert risposta.status_code == 302 and risposta.url == reverse('consulti:nuova')
    passo_1 = _t(loggato.get(reverse('consulti:nuova')))
    assert 'value="Boxer"' in passo_1 and 'value="Fido"' in passo_1 and 'Ricomincia da capo' in passo_1
    loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M', 'razza': 'Boxer'})
    passo_2 = _t(loggato.get(reverse('consulti:nuova_esame')))
    assert 'Mezzo scritto' in passo_2 and 'id="tipo-ECG" value="ECG" checked' in passo_2
    assert f'value="{mondo.ref.pk}" checked' in passo_2


def test_indietro_su_una_bozza_salva_e_si_corregge(loggato, bozza_ecg):
    url_2 = reverse('consulti:passo_esame', args=[bozza_ecg.pk])
    risposta = loggato.post(url_2, {'tipo_esame': 'ECG', 'refertatore': bozza_ecg.refertatore_id,
                                    'quesito': 'Quesito corretto', 'azione': 'indietro'})
    assert risposta.url == reverse('consulti:passo_paziente', args=[bozza_ecg.pk])
    bozza_ecg.refresh_from_db()
    assert bozza_ecg.quesito == 'Quesito corretto'
    passo_1 = _t(loggato.get(risposta.url))
    assert 'value="Bruno"' in passo_1
    risposta = loggato.post(risposta.url, {'nome': 'Bruno', 'specie': 'CANE', 'sesso': 'MC', 'eta_anni': '9'})
    assert risposta.url == url_2
    bozza_ecg.paziente.refresh_from_db()
    assert bozza_ecg.paziente.sesso == 'MC' and bozza_ecg.paziente.eta_testo == '9 anni'
    assert 'value="9"' in _t(loggato.get(reverse('consulti:passo_paziente', args=[bozza_ecg.pk])))


def test_una_bozza_si_riprende_dal_primo_passo_incompleto(loggato, mondo):
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=mondo.richiedente, clinica=mondo.clinica)
    Paziente.objects.create(richiesta=r, nome='Fido')
    dettaglio = reverse('consulti:dettaglio', args=[r.pk])
    assert loggato.get(dettaglio).url == reverse('consulti:passo_esame', args=[r.pk])   # niente esperto
    r.refertatore, r.quesito = mondo.ref, 'Aritmia?'
    r.save()
    assert loggato.get(dettaglio).url == reverse('consulti:passo_carica', args=[r.pk])  # niente tracciato
    Allegato.da_upload(r, _file('t.pdf'), CategoriaAllegato.ECG_PDF)
    assert loggato.get(dettaglio).url == reverse('consulti:passo_riepilogo', args=[r.pk])
    # L'elenco porta alla pagina del caso, che rimanda al passo giusto.
    elenco = _t(loggato.get(reverse('consulti:mie_richieste')))
    assert dettaglio in elenco and 'da completare' in elenco


# ── Passo 3: categoria dedotta, proiezioni, sostituzione ─────────────────────

@pytest.mark.parametrize('nome, mime, categoria', [
    ('tracciato.pdf', 'application/pdf', CategoriaAllegato.ECG_PDF),
    ('foto.JPG', 'image/jpeg', CategoriaAllegato.ECG_IMMAGINE),
    ('foto.heic', '', CategoriaAllegato.ECG_IMMAGINE),
])
def test_ecg_categoria_dal_tipo_di_file(loggato, bozza_ecg, nome, mime, categoria):
    assert _carica(loggato, bozza_ecg, 'ecg', _file(nome, PDF, mime)).status_code == 200
    assert bozza_ecg.allegati.get().categoria == categoria


def test_ecg_si_aggiungono_piu_file_e_si_rifiuta_cio_che_non_c_entra(loggato, bozza_ecg):
    _carica(loggato, bozza_ecg, 'ecg', _file('p1.pdf'))
    _carica(loggato, bozza_ecg, 'ecg', _file('p2.png', PNG))
    assert bozza_ecg.allegati.count() == 2
    risposta = _carica(loggato, bozza_ecg, 'ecg', _file('nota.docx', b'x'))
    assert risposta.status_code == 400 and 'PDF o come foto' in risposta.json()['errore']
    # Una zona di un altro tipo di esame non vale.
    risposta = _carica(loggato, bozza_ecg, 'eco_referto', _file('r.pdf'))
    assert risposta.status_code == 400 and bozza_ecg.allegati.count() == 2


def test_senza_javascript_si_torna_alla_zona_con_un_messaggio(loggato, bozza_ecg):
    risposta = _carica(loggato, bozza_ecg, 'ecg', _file('t.pdf'), json=False)
    assert risposta.status_code == 302 and risposta.url.endswith(reverse('consulti:passo_carica',
                                                                         args=[bozza_ecg.pk]) + '#ecg')
    risposta = _carica(loggato, bozza_ecg, 'ecg', _file('t.txt', b'x'), json=False)
    assert risposta.status_code == 302 and bozza_ecg.allegati.count() == 1


def test_holter_referto_solo_pdf_e_file_dell_apparecchio_a_pezzi(loggato, mondo, crea_bozza):
    CompetenzaRefertatore.objects.create(refertatore=mondo.ref, tipo_esame=TipoEsame.HOLTER, referente=True)
    r = crea_bozza(loggato, 'HOLTER', mondo.ref)
    assert _carica(loggato, r, 'holter_referto', _file('referto.png', PNG)).status_code == 400
    assert _carica(loggato, r, 'holter_referto', _file('referto.pdf')).status_code == 200
    # Un posto solo: il secondo referto va con «Sostituisci».
    risposta = _carica(loggato, r, 'holter_referto', _file('altro.pdf'))
    assert risposta.status_code == 400 and 'Sostituisci' in risposta.json()['errore']
    risposta = _a_pezzi(loggato, r, 'registrazione.hlt', b'HOLTER' * 3000, 'holter_file')
    assert risposta.status_code == 200
    assert set(r.allegati.values_list('categoria', flat=True)) == {'HOLTER_REFERTO', 'HOLTER_FILE'}


def test_eco_riga_crea_e_rimuove_la_proiezione_caricata(loggato, bozza_eco, catalogo):
    p = catalogo['pd_clip']
    assert _carica(loggato, bozza_eco, 'proiezione', _file('ax.mp4', MP4, 'video/mp4'),
                   proiezione=p.pk).status_code == 200
    allegato = bozza_eco.allegati.get()
    assert allegato.categoria == CategoriaAllegato.ECO_CLIP
    pc = ProiezioneCaricata.objects.get(richiesta=bozza_eco)
    assert pc.proiezione == p and pc.allegato == allegato
    evento = bozza_eco.audit.filter(azione='ALLEGATO_CARICATO').last()
    assert evento.dettaglio['proiezione'] == p.nome
    risposta = loggato.post(reverse('consulti:elimina_allegato', args=[bozza_eco.pk, allegato.pk]))
    assert risposta.url == reverse('consulti:passo_carica', args=[bozza_eco.pk])
    assert not Allegato.objects.filter(pk=allegato.pk).exists()
    assert not ProiezioneCaricata.objects.filter(richiesta=bozza_eco).exists()


def test_eco_la_riga_accetta_cio_che_si_aspetta(loggato, bozza_eco, catalogo):
    statica, clip = catalogo['pd_statica'], catalogo['pd_clip']
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('x.mp4', MP4), proiezione=statica.pk)
    assert risposta.status_code == 400 and 'va un\'immagine' in risposta.json()['errore']
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('x.png', PNG), proiezione=clip.pk)
    assert risposta.status_code == 400 and 'va un filmato' in risposta.json()['errore']
    # Un DICOM prende la categoria della riga.
    assert _carica(loggato, bozza_eco, 'proiezione', _file('x.dcm', b'DICM'), proiezione=statica.pk).status_code == 200
    assert _carica(loggato, bozza_eco, 'proiezione', _file('y.dcm', b'DICM'), proiezione=clip.pk).status_code == 200
    categorie = dict(ProiezioneCaricata.objects.values_list('proiezione__codice', 'allegato__categoria'))
    assert categorie == {'PDS': 'ECO_STATICA', 'PDC': 'ECO_CLIP'}


def test_eco_una_riga_un_file_e_sostituzione(loggato, bozza_eco, catalogo):
    p = catalogo['pd_clip']
    _carica(loggato, bozza_eco, 'proiezione', _file('prima.mp4', MP4), proiezione=p.pk)
    vecchio = bozza_eco.allegati.get()
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('seconda.mp4', MP4), proiezione=p.pk)
    assert risposta.status_code == 400 and 'Sostituisci' in risposta.json()['errore']
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('nuova.mp4', MP4 * 2), proiezione=p.pk,
                       sostituisci=vecchio.pk)
    assert risposta.status_code == 200
    nuovo = bozza_eco.allegati.get()
    assert nuovo.pk != vecchio.pk and nuovo.nome_originale == 'nuova.mp4'
    assert list(bozza_eco.proiezioni.values_list('proiezione_id', 'allegato_id')) == [(p.id, nuovo.pk)]
    assert bozza_eco.audit.filter(azione='ALLEGATO_ELIMINATO', dettaglio__sostituito_da=nuovo.pk).exists()
    # Anche la sostituzione a pezzi.
    risposta = _a_pezzi(loggato, bozza_eco, 'terza.mp4', MP4 * 40, 'proiezione', proiezione=p.pk,
                        sostituisci=nuovo.pk)
    assert risposta.status_code == 200
    assert bozza_eco.allegati.get().nome_originale == 'terza.mp4' and bozza_eco.proiezioni.count() == 1


def test_eco_filmati_liberi_con_nota_uno_per_riga(loggato, bozza_eco, catalogo):
    libero, libero2 = catalogo['libero'], catalogo['libero2']
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('l1.mp4', MP4), proiezione=libero.pk)
    assert risposta.status_code == 400 and 'cosa mostra' in risposta.json()['errore']
    assert _carica(loggato, bozza_eco, 'proiezione', _file('l1.mp4', MP4), proiezione=libero.pk,
                   nota='jet sospetto sull\'aortica').status_code == 200
    risposta = _a_pezzi(loggato, bozza_eco, 'l2.mp4', MP4 * 10, 'proiezione', proiezione=libero2.pk,
                        nota='versamento?')
    assert risposta.status_code == 200
    # Una riga = un file anche qui: il terzo va con «Sostituisci».
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('l3.mp4', MP4), proiezione=libero.pk, nota='x')
    assert risposta.status_code == 400 and 'Sostituisci' in risposta.json()['errore']
    assert sorted(bozza_eco.proiezioni.values_list('nota', flat=True)) == ['jet sospetto sull\'aortica',
                                                                          'versamento?']
    # Sostituendo senza nota nuova resta quella di prima.
    vecchio = bozza_eco.proiezioni.get(proiezione=libero).allegato
    _carica(loggato, bozza_eco, 'proiezione', _file('l1bis.mp4', MP4), proiezione=libero.pk, sostituisci=vecchio.pk)
    assert bozza_eco.proiezioni.get(proiezione=libero).nota == 'jet sospetto sull\'aortica'
    # I filmati liberi sono facoltativi: non entrano fra gli obbligatori.
    assert not {libero.id, libero2.id} & {e.proiezione_id for e in regole.elementi_obbligatori(bozza_eco)}
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[bozza_eco.pk])))
    # Sul tavolo di smistamento la nota del filmato libero si legge (e si
    # corregge) nella casella accanto al file.
    assert 'Filmati liberi · facoltativi' in pagina and 'value="versamento?"' in pagina


def test_eco_clip_troppo_pesante_rifiutata_con_messaggio(loggato, bozza_eco, catalogo, settings):
    settings.ECO_CLIP_MAX_BYTE = 100
    p = catalogo['pd_clip']
    risposta = _carica(loggato, bozza_eco, 'proiezione', _file('lunga.mp4', MP4 * 20), proiezione=p.pk)
    assert risposta.status_code == 400 and 'limite per una clip' in risposta.json()['errore']
    # A pezzi il rifiuto arriva gia' allo stato, prima di mandare i pezzi.
    stato = loggato.get(reverse('consulti:upload_stato', args=[bozza_eco.pk]), {
        'impronta': 'a' * 64, 'slot': 'proiezione', 'proiezione': p.pk, 'nome': 'lunga.mp4', 'dimensione': 5000})
    assert stato.status_code == 400 and 'massimo 10 secondi' in stato.json()['errore']
    # Un'immagine non ha quel limite.
    assert _carica(loggato, bozza_eco, 'proiezione', _file('ok.png', PNG * 20),
                   proiezione=catalogo['pd_statica'].pk).status_code == 200


def test_la_clip_passa_alla_transcodifica_dopo_il_commit(loggato, bozza_eco, catalogo, settings,
                                                         django_capture_on_commit_callbacks):
    settings.FFMPEG_BIN = '/nessun/posto/ffmpeg'
    from eco import transcodifica
    with mock.patch.object(transcodifica.logger, 'warning') as avviso:
        with django_capture_on_commit_callbacks(execute=True):
            _carica(loggato, bozza_eco, 'proiezione', _file('c.mp4', MP4), proiezione=catalogo['pd_clip'].pk)
    assert 'ffmpeg non trovato' in avviso.call_args[0][0]
    assert bozza_eco.allegati.get().stato == 'CARICATO'


# ── Passo 3: la lista di cio' che manca e «Avanti» ───────────────────────────

def test_avanti_spento_con_la_lista_della_regola_di_invio(loggato, bozza_eco, catalogo):
    url = reverse('consulti:passo_carica', args=[bozza_eco.pk])
    pagina = _t(loggato.get(url))
    elementi = regole.elementi_obbligatori(bozza_eco)
    assert '0 di 4 elementi obbligatori caricati' in pagina
    for e in elementi:
        assert f'href="#{e.chiave}">{e.etichetta}</a>' in pagina
    # La frase accanto ad «Avanti» e' quella che bloccherebbe l'invio.
    frase = regole.frase_mancanti(regole.allegati_mancanti(bozza_eco))
    assert frase == regole.perche_non_puoi_inviare(bozza_eco)
    assert f'<i class="bi bi-info-circle me-1" aria-hidden="true"></i>{frase}' in pagina
    assert 'class="btn-nuova" disabled' in pagina
    assert reverse('consulti:passo_riepilogo', args=[bozza_eco.pk]) not in pagina.split('percorso-barra')[-1]

    _carica(loggato, bozza_eco, 'eco_referto', _file('r.pdf'))
    _carica(loggato, bozza_eco, 'proiezione', _file('a.mp4', MP4), proiezione=catalogo['pd_clip'].pk)
    pagina = _t(loggato.get(url))
    assert '2 di 4 elementi obbligatori caricati' in pagina
    assert 'Mancano: la proiezione «LA/Ao»; la proiezione «Apicale 4 camere».' in pagina

    _carica(loggato, bozza_eco, 'proiezione', _file('b.png', PNG), proiezione=catalogo['pd_statica'].pk)
    _carica(loggato, bozza_eco, 'proiezione', _file('c.mp4', MP4), proiezione=catalogo['ap_clip'].pk)
    pagina = _t(loggato.get(url))
    assert '4 di 4 elementi obbligatori caricati' in pagina and 'disabled aria-describedby' not in pagina
    assert f'href="{reverse("consulti:passo_riepilogo", args=[bozza_eco.pk])}"' in pagina
    assert regole.perche_non_puoi_inviare(bozza_eco) is None


def test_eco_righe_per_finestra_filmati_prima_e_liberi_in_fondo(loggato, bozza_eco, catalogo):
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[bozza_eco.pk])))
    posizioni = [pagina.index(f'id="proiezione_{catalogo[k].pk}"')
                 for k in ('pd_clip', 'pd_statica', 'pd_facoltativa', 'ap_clip', 'libero', 'libero2')]
    assert posizioni == sorted(posizioni)
    assert (pagina.index('Parasternale destra') < pagina.index('Parasternale sinistra, apicale e craniale')
            < pagina.index('Filmati liberi'))
    assert 'Sottoxifoidea' not in pagina  # finestra senza righe: niente gruppo vuoto
    assert '0 di 2' in pagina and 'Altre proiezioni · facoltative (1)' in pagina
    # Segnaposto sobrio finche' la riga non ha immagini di riferimento.
    assert 'riferimento-segnaposto' in pagina
    # La lista delle obbligatorie segue lo stesso ordine delle righe.
    assert [e.proiezione_id for e in regole.elementi_obbligatori(bozza_eco)][1:] == [
        catalogo['pd_clip'].id, catalogo['pd_statica'].id, catalogo['ap_clip'].id]
    # Una finestra con tutte le obbligatorie caricate si presenta chiusa.
    _carica(loggato, bozza_eco, 'proiezione', _file('c.mp4', MP4), proiezione=catalogo['ap_clip'].pk)
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[bozza_eco.pk])))
    assert 'id="finestra-parasternale_sinistra">' in pagina and 'id="finestra-parasternale_destra" open>' in pagina


def test_eco_riga_con_testi_e_immagini_di_riferimento(loggato, bozza_eco, catalogo):
    p = catalogo['pd_clip']
    p.istruzioni, p.deve_essere_visibile = 'Filmato di massimo 10 secondi.', 'Le quattro camere.'
    p.serve_per, p.nota_riferimento = 'Soglia IVS 0,6 cm.', 'APPUNTO SOLO ADMIN'
    p.save()
    for i, didascalia in enumerate(('Immagine ecografica', 'Schema', 'Posizione della sonda'), start=1):
        ImmagineRiferimento(proiezione=p, ordine=i, didascalia=didascalia).immagine.save(
            f'r{i}.png', SimpleUploadedFile(f'r{i}.png', PNG), save=True)
    prima, *altre = list(p.immagini.all())
    pagina = _t(loggato.get(reverse('consulti:passo_carica', args=[bozza_eco.pk])))
    riga = pagina[pagina.index(f'id="proiezione_{p.pk}"'):pagina.index(f'id="proiezione_{catalogo["pd_statica"].pk}"')]
    assert '<strong>Come:</strong> Filmato di massimo 10 secondi.' in riga
    assert '<strong>Deve vedersi:</strong> Le quattro camere.' in riga
    assert '<summary>A cosa serve</summary>' in riga and 'Soglia IVS' in riga
    assert 'APPUNTO SOLO ADMIN' not in pagina
    assert f'class="riferimento" href="{reverse("immagine_riferimento", args=[prima.pk])}"' in riga
    assert riga.count('data-ingrandisci') == 3 and '+2' in riga
    assert 'id="modalRiferimento"' in pagina


def test_immagine_di_riferimento_consegnata_protetta(client, loggato, catalogo):
    riferimento = ImmagineRiferimento(proiezione=catalogo['pd_clip'], ordine=1)
    riferimento.immagine.save('rif.png', SimpleUploadedFile('rif.png', PNG), save=True)
    url = reverse('immagine_riferimento', args=[riferimento.pk])
    risposta = loggato.get(url)
    assert risposta.status_code == 200 and risposta['X-Accel-Redirect'].startswith('/_media_interno/eco_riferimento/')
    assert loggato.get(reverse('immagine_riferimento', args=[9999])).status_code == 404
    loggato.logout()
    assert client.get(url).status_code == 302  # login


# ── Passo 4: riepilogo e invio ──────────────────────────────────────────────

def test_riepilogo_con_prezzo_urgenza_e_modifica(loggato, esperto_eco, catalogo, crea_bozza):
    Supplemento.objects.create(codice='URGENZA', descrizione='Urgenza', tipo=TipoSupplemento.URGENZA,
                               importo=Decimal('25.00'), valido_dal=date(2020, 1, 1))
    r = crea_bozza(loggato, 'ECO', esperto_eco, paziente={'nome': 'Luna', 'specie': 'GATTO', 'sesso': 'FS'},
                   esame={'urgenza': 'on', 'quesito': 'Soffio 3/6: cardiomiopatia?'})
    pagina = _t(loggato.get(reverse('consulti:passo_riepilogo', args=[r.pk])))
    assert '€ 134,20' in pagina and 'imponibile € 85,00 + urgenza € 25,00 + IVA 22% € 24,20' in pagina
    assert 'Soffio 3/6: cardiomiopatia?' in pagina and 'urgente' in pagina
    for passo in ('passo_paziente', 'passo_esame', 'passo_carica'):
        assert reverse(f'consulti:{passo}', args=[r.pk]) in pagina
    # Mancano i file: Invia e' spento, con la frase della regola e il link al passo 3.
    assert 'Non si puo\' ancora inviare' in pagina and 'Invia a Dott.ssa Laura Monti' in pagina
    assert f'href="{reverse("consulti:passo_carica", args=[r.pk])}">Vai a sistemarlo' in pagina
    risposta = loggato.post(reverse('consulti:invia', args=[r.pk]))
    assert risposta.url == reverse('consulti:passo_riepilogo', args=[r.pk])
    r.refresh_from_db()
    assert r.stato == StatoRichiesta.BOZZA


def test_dopo_l_invio_i_passi_non_si_modificano(loggato, bozza_ecg):
    Allegato.da_upload(bozza_ecg, _file('t.pdf'), CategoriaAllegato.ECG_PDF)
    loggato.post(reverse('consulti:invia', args=[bozza_ecg.pk]))
    for passo in ('passo_paziente', 'passo_esame', 'passo_carica', 'passo_riepilogo'):
        risposta = loggato.get(reverse(f'consulti:{passo}', args=[bozza_ecg.pk]))
        assert risposta.status_code == 302 and risposta.url == reverse('consulti:dettaglio', args=[bozza_ecg.pk])
    assert _carica(loggato, bozza_ecg, 'ecg', _file('dopo.pdf')).status_code == 403
    assert bozza_ecg.allegati.count() == 1


# ── Permessi ────────────────────────────────────────────────────────────────

def _passi_e_rotte(r):
    get = [reverse(f'consulti:{p}', args=[r.pk])
           for p in ('passo_paziente', 'passo_esame', 'passo_carica', 'passo_riepilogo')]
    return get


def test_un_altro_richiedente_riceve_404_su_ogni_passo(client, bozza_ecg, mondo):
    altro = Richiedente.objects.create(
        user=User.objects.create_user('altro', 'a@x.it', 'pw'), clinica=mondo.clinica)
    for utente in (altro.user, mondo.estraneo, mondo.staff):
        client.force_login(utente)
        for url in _passi_e_rotte(bozza_ecg):
            assert client.get(url).status_code == 404, (utente, url)
            assert client.post(url, {'nome': 'X'}).status_code == 404, (utente, url)
        assert _carica(client, bozza_ecg, 'ecg', _file('t.pdf')).status_code == 404
        assert client.post(reverse('consulti:invia', args=[bozza_ecg.pk])).status_code == 404
    assert not bozza_ecg.allegati.exists()


def test_il_refertatore_non_puo_modificare_la_bozza(client, bozza_ecg, mondo):
    """Anche il refertatore gia' scelto: la bozza e' ancora di chi la scrive."""
    client.force_login(mondo.ref.user)
    for url in _passi_e_rotte(bozza_ecg):
        assert client.get(url).status_code == 404
    risposta = client.post(reverse('consulti:passo_esame', args=[bozza_ecg.pk]), {
        'tipo_esame': 'ECG', 'refertatore': mondo.ref.pk, 'quesito': 'cambiato', 'azione': 'avanti'})
    assert risposta.status_code == 404
    assert _carica(client, bozza_ecg, 'ecg', _file('t.pdf')).status_code == 404
    bozza_ecg.refresh_from_db()
    assert bozza_ecg.quesito != 'cambiato' and not bozza_ecg.allegati.exists()


def test_chi_non_e_richiedente_non_apre_una_richiesta(client, mondo):
    client.force_login(mondo.ref.user)
    for url in (reverse('consulti:nuova'), reverse('consulti:nuova_esame')):
        risposta = client.get(url)
        assert risposta.status_code == 302 and risposta.url == reverse('consulti:mie_richieste')


# ── Identita' del caso, motivo dell'esame, pie' di pagina ────────────────────

def test_la_pagina_del_caso_si_chiama_come_il_paziente(caso_inviato, client, mondo):
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])))
    assert '<title>Fido · Elettrocardiogramma — VetWay Consulti</title>' in pagina
    assert 'Fido · Elettrocardiogramma <span class="codice-caso ms-1">' + caso_inviato.codice in pagina
    # Il motivo dell'esame non si chiede piu': vuoto, niente etichetta col trattino.
    assert 'Motivo dell' not in pagina


def test_racconto_dice_proiezione_e_sostituzione(loggato, bozza_eco, catalogo):
    from consulti.racconto import racconta
    p = catalogo['pd_clip']
    _carica(loggato, bozza_eco, 'proiezione', _file('a.mp4', MP4), proiezione=p.pk)
    vecchio = bozza_eco.allegati.get()
    _carica(loggato, bozza_eco, 'proiezione', _file('b.mp4', MP4), proiezione=p.pk, sostituisci=vecchio.pk)
    frasi = [r['frase'] for r in racconta(bozza_eco.audit.all())]
    assert 'ha caricato «a.mp4» (Asse lungo 4 camere)' in frasi and 'ha sostituito «a.mp4»' in frasi


def test_catalogo_filmato_libero_sempre_facoltativo(db):
    from django.core.exceptions import ValidationError
    p = ProiezioneCatalogo(codice='X', nome='Libero', libera=True, obbligatoria=True)
    with pytest.raises(ValidationError):
        p.clean()


def test_upload_chunk_pulisce_il_parziale_se_il_file_non_va(loggato, bozza_eco, catalogo):
    contenuto = b'non e un pdf' * 100
    impronta = hashlib.sha256(contenuto).hexdigest()
    loggato.post(reverse('consulti:upload_pezzo', args=[bozza_eco.pk]),
                 {'impronta': impronta, 'offset': '0', 'pezzo': SimpleUploadedFile('p', contenuto)})
    risposta = loggato.post(reverse('consulti:upload_concludi', args=[bozza_eco.pk]),
                            {'impronta': impronta, 'nome': 'x.txt', 'slot': 'eco_referto'})
    assert risposta.status_code == 400 and 'PDF' in risposta.json()['errore']
    assert not bozza_eco.allegati.exists()
    upload_chunk.abbandona(impronta)


def test_categoria_per_senza_riga_e_genere_file():
    assert caricamento.genere_file('clip.AVI') == 'video'
    assert caricamento.genere_file('scan', 'application/dicom') == 'dicom'
    assert caricamento.genere_file('x.bin', 'application/octet-stream') == 'altro'
    with pytest.raises(caricamento.CaricamentoNonValido):
        caricamento.categoria_per('boh', 'x.pdf')
