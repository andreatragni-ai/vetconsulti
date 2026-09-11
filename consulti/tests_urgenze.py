"""Urgenze (collaudo dell'11/09/2026): un caso urgente aspetta risposta entro
4 ORE, qualunque sia il tempo dichiarato dall'esperto per i casi normali;
e va solo a chi, nel profilo, accetta le urgenze per quel tipo di esame
(CompetenzaRefertatore.accetta_urgenze). La regola vale nel form del passo 2,
all'invio, alla riassegnazione; le 4 ore valgono per la pagina del caso,
l'elenco dei casi ricevuti, il sollecito di sorveglia_consulti (a 2 ore) e
l'email «caso arrivato». Fixture in conftest.py: mondo, caso_inviato."""

import html
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.models import CompetenzaRefertatore, Refertatore
from consulti import percorso, regole
from consulti.models import (Allegato, CategoriaAllegato, Paziente, Richiesta, StatoRichiesta,
                             TransizioneNonValida)
from core.tipi import TipoEsame


def _t(risposta):
    return html.unescape(risposta.content.decode())


def _accetta(refertatore, si=True, tipo=TipoEsame.ECG):
    CompetenzaRefertatore.objects.filter(refertatore=refertatore, tipo_esame=tipo).update(accetta_urgenze=si)


@pytest.fixture
def loggato(client, mondo):
    client.force_login(mondo.richiedente.user)
    return client


def _bozza_ecg(mondo, refertatore, urgenza=True):
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=mondo.richiedente, clinica=mondo.clinica,
                                 refertatore=refertatore, urgenza=urgenza, quesito='Aritmia?')
    Paziente.objects.create(richiesta=r, nome='Fulmine')
    Allegato.da_upload(r, SimpleUploadedFile('ecg.pdf', b'%PDF-1.4 x', 'application/pdf'), CategoriaAllegato.ECG_PDF)
    return r


# ── Chi accetta le urgenze ───────────────────────────────────────────────────

def test_parte_spento_e_vale_per_tipo_di_esame(mondo):
    assert not mondo.ref.accetta_urgenze_per(TipoEsame.ECG)
    _accetta(mondo.ref)
    assert mondo.ref.accetta_urgenze_per(TipoEsame.ECG) and not mondo.ref.accetta_urgenze_per(TipoEsame.ECO)
    # Senza essere referente per quel tipo non conta.
    CompetenzaRefertatore.objects.filter(refertatore=mondo.ref).update(referente=False)
    assert not mondo.ref.accetta_urgenze_per(TipoEsame.ECG)


def test_rifiuta_urgenza_dice_perche(mondo):
    assert regole.rifiuta_urgenza(mondo.ref, TipoEsame.ECG, urgenza=False) is None
    frase = regole.rifiuta_urgenza(mondo.ref, TipoEsame.ECG, urgenza=True)
    assert frase == ('Dott. Anna Test non accetta casi urgenti per elettrocardiogramma: scegli un altro '
                     'collega oppure togli «Urgente».')
    _accetta(mondo.ref)
    assert regole.rifiuta_urgenza(mondo.ref, TipoEsame.ECG, urgenza=True) is None
    assert regole.rifiuta_urgenza(None, TipoEsame.ECG, urgenza=True) is None


# ── Passo 2: le schede e il form ─────────────────────────────────────────────

def test_schede_con_urgente_chi_non_accetta_si_vede_ma_non_si_sceglie(loggato, mondo):
    _accetta(mondo.ref)
    normali = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'ECG'}))
    assert 'Non accetta urgenze' not in normali and 'Risposta in 24 ore' in normali
    assert f'id="esperto-{mondo.ref2.pk}" value="{mondo.ref2.pk}" required' in normali
    urgenti = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'ECG', 'urgenza': '1',
                                                           'refertatore': mondo.ref2.pk}))
    assert f'id="esperto-{mondo.ref2.pk}" value="{mondo.ref2.pk}" disabled' in urgenti   # e non «checked»
    assert f'id="esperto-{mondo.ref.pk}" value="{mondo.ref.pk}" required' in urgenti
    assert urgenti.count('Non accetta urgenze') == 1
    assert 'Risposta entro 4 ore (urgente)' in urgenti and 'Risposta in 24 ore' not in urgenti


def test_schede_nessuno_accetta_urgenze(loggato, mondo):
    urgenti = _t(loggato.get(reverse('consulti:esperti'), {'tipo_esame': 'ECG', 'urgenza': '1'}))
    assert 'nessun esperto accetta urgenze' in urgenti and urgenti.count('Non accetta urgenze') == 2


def test_form_del_passo_2_rifiuta_l_urgente_a_chi_non_lo_accetta(loggato, mondo):
    loggato.post(reverse('consulti:nuova'), {'nome': 'Fido', 'specie': 'CANE', 'sesso': 'M'})
    dati = {'tipo_esame': 'ECG', 'refertatore': mondo.ref2.pk, 'quesito': 'x', 'azione': 'avanti', 'urgenza': 'on'}
    risposta = loggato.post(reverse('consulti:nuova_esame'), dati)
    assert risposta.status_code == 200 and 'non accetta casi urgenti' in _t(risposta)
    assert not Richiesta.objects.exists()
    # Senza «Urgente» lo stesso esperto va bene; con un esperto che accetta anche urgente.
    _accetta(mondo.ref)
    risposta = loggato.post(reverse('consulti:nuova_esame'), {**dati, 'refertatore': mondo.ref.pk})
    assert risposta.status_code == 302 and Richiesta.objects.get().urgenza


def test_accendere_urgente_su_una_bozza_con_esperto_che_non_accetta(loggato, mondo):
    r = _bozza_ecg(mondo, mondo.ref2, urgenza=False)
    risposta = loggato.post(reverse('consulti:passo_esame', args=[r.pk]), {
        'tipo_esame': 'ECG', 'refertatore': mondo.ref2.pk, 'quesito': 'x', 'azione': 'avanti', 'urgenza': 'on'})
    assert risposta.status_code == 200 and 'non accetta casi urgenti' in _t(risposta)
    r.refresh_from_db()
    assert not r.urgenza


# ── Invio e riassegnazione (regole.py) ───────────────────────────────────────

def test_invio_bloccato_se_l_esperto_non_accetta_urgenze(mondo):
    r = _bozza_ecg(mondo, mondo.ref)
    assert 'non accetta casi urgenti' in regole.perche_non_puoi_inviare(r)
    assert percorso.passo_da_riprendere(r) == 2      # si corregge al passo 2
    with pytest.raises(TransizioneNonValida):
        r.invia(mondo.richiedente.user)
    r.refresh_from_db()
    assert r.stato == StatoRichiesta.BOZZA
    _accetta(mondo.ref)
    assert regole.perche_non_puoi_inviare(r) is None and percorso.passo_da_riprendere(r) == 4
    r.invia(mondo.richiedente.user)
    assert r.stato == StatoRichiesta.INVIATA


def test_riepilogo_segnala_il_blocco_e_rimanda_al_passo_2(loggato, mondo):
    r = _bozza_ecg(mondo, mondo.ref)
    pagina = _t(loggato.get(reverse('consulti:passo_riepilogo', args=[r.pk])))
    assert 'non accetta casi urgenti' in pagina
    assert f'href="{reverse("consulti:passo_esame", args=[r.pk])}">Vai a sistemarlo' in pagina


def test_riassegnare_un_urgente_solo_a_chi_accetta(mondo):
    _accetta(mondo.ref)
    r = _bozza_ecg(mondo, mondo.ref)
    r.invia(mondo.richiedente.user)
    r.declina('Non riesco entro 4 ore.')
    assert 'non accetta casi urgenti' in regole.perche_non_puoi_riassegnare(r, mondo.ref2)
    with pytest.raises(TransizioneNonValida):
        r.riassegna(mondo.ref2)
    _accetta(mondo.ref2)
    r.riassegna(mondo.ref2)
    assert r.stato == StatoRichiesta.INVIATA and r.refertatore == mondo.ref2


def test_select_della_riassegnazione_spegne_chi_non_accetta(client, mondo):
    _accetta(mondo.ref)
    r = _bozza_ecg(mondo, mondo.ref)
    r.invia(mondo.richiedente.user)
    r.declina('No.')
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[r.pk])))
    assert f'<option value="{mondo.ref2.pk}" disabled>' in pagina and 'non accetta urgenze' in pagina


# ── Le 4 ore ovunque ─────────────────────────────────────────────────────────

@pytest.fixture
def urgente_inviato(mondo):
    """Un ECG urgente inviato a `ref`, che per i casi normali dichiara 24 ore."""
    _accetta(mondo.ref)
    r = _bozza_ecg(mondo, mondo.ref)
    r.invia(mondo.richiedente.user)
    return r


def test_scadenza_a_4_ore_anche_se_l_esperto_dichiara_24(urgente_inviato):
    assert regole.ore_risposta(urgente_inviato) == 4
    assert regole.scadenza(urgente_inviato) == urgente_inviato.inviata_il + timedelta(hours=4)


def test_pagina_del_caso_e_casi_ricevuti_dicono_4_ore(client, mondo, urgente_inviato, caso_inviato):
    client.force_login(mondo.ref.user)
    entro = timezone.localtime(urgente_inviato.inviata_il + timedelta(hours=4)).strftime('%d/%m %H:%M')
    pagina = _t(client.get(reverse('referti:refertazione', args=[urgente_inviato.pk])))
    assert f'urgente</strong>: risposta entro 4 h, entro il {entro}' in pagina and '24 h' not in pagina
    elenco = _t(client.get(reverse('consulti:casi_ricevuti')))
    riga = elenco[elenco.index(urgente_inviato.codice):elenco.index(caso_inviato.codice)]
    assert '4 h <span class="small">(urgente)</span>' in riga and f'entro il {entro}' in riga
    # Il caso normale dello stesso esperto resta a 24 ore.
    assert '24 h<br>' in elenco[elenco.index(caso_inviato.codice):]


def test_email_caso_arrivato_con_la_scadenza_di_4_ore(mondo, urgente_inviato):
    from notifiche.servizi import avvisa_caso_arrivato
    mail.outbox.clear()
    avvisa_caso_arrivato(urgente_inviato)
    scadenza = timezone.localtime(urgente_inviato.inviata_il + timedelta(hours=4))
    corpo = mail.outbox[0].body
    assert 'URGENTE' in mail.outbox[0].subject
    assert f'Risposta entro: {scadenza:%d/%m/%Y} alle {scadenza:%H:%M} (4 ore, caso urgente)' in corpo


def test_email_caso_arrivato_normale_con_le_ore_dichiarate(caso_inviato):
    from notifiche.servizi import avvisa_caso_arrivato
    mail.outbox.clear()
    avvisa_caso_arrivato(caso_inviato)
    assert '(24 ore)' in mail.outbox[0].body and 'caso urgente' not in mail.outbox[0].body


def test_sollecito_di_un_urgente_a_2_ore(mondo, urgente_inviato):
    def sorveglia():
        call_command('sorveglia_consulti', stdout=StringIO())
    mail.outbox.clear()
    with mock.patch('django.utils.timezone.now', return_value=urgente_inviato.inviata_il + timedelta(minutes=110)):
        sorveglia()
    assert not mail.outbox                                    # prima delle 2 ore niente
    with mock.patch('django.utils.timezone.now', return_value=urgente_inviato.inviata_il + timedelta(minutes=125)):
        sorveglia()
    assert len(mail.outbox) == 1 and 'Promemoria' in mail.outbox[0].subject
    assert 'caso urgente, con risposta entro 4 ore' in mail.outbox[0].body
    assert urgente_inviato.audit.get(azione='SOLLECITO').dettaglio['ore_dichiarate'] == 4


# ── Profilo, seed e listino ──────────────────────────────────────────────────

def test_il_refertatore_dichiara_nel_profilo_se_accetta_urgenze(client, mondo):
    client.force_login(mondo.ref.user)
    url = reverse('accounts:profilo_refertatore')
    pagina = _t(client.get(url))
    assert 'Accetta urgenze' in pagina and 'entro 4 ore' in pagina
    competenze = list(CompetenzaRefertatore.objects.filter(refertatore=mondo.ref).order_by('tipo_esame'))
    dati = {'p-titolo': 'Dott.', 'k-TOTAL_FORMS': str(len(competenze)), 'k-INITIAL_FORMS': str(len(competenze))}
    for i, c in enumerate(competenze):
        dati.update({f'k-{i}-id': c.pk, f'k-{i}-tipo_esame': c.tipo_esame})
        if c.referente:
            dati.update({f'k-{i}-referente': 'on', f'k-{i}-accetta_urgenze': 'on'})
    assert client.post(url, dati).status_code == 302
    assert mondo.ref.accetta_urgenze_per(TipoEsame.ECG)


@pytest.mark.django_db
def test_seed_urgenze_e_supplemento_entro_4_ore(settings):
    from listino.models import Supplemento
    settings.DEBUG = True
    call_command('seed_demo', stdout=StringIO())
    assert Supplemento.objects.get(codice='URGENZA').descrizione == 'Risposta entro 4 ore'
    rferrari = Refertatore.objects.get(user__username='rferrari')
    lmonti = Refertatore.objects.get(user__username='lmonti')
    assert rferrari.accetta_urgenze_per(TipoEsame.ECG) and not rferrari.accetta_urgenze_per(TipoEsame.HOLTER)
    assert lmonti.accetta_urgenze_per(TipoEsame.ECO)
    assert User.objects.filter(username='gbianchi').exists()


def test_la_pagina_del_richiedente_dice_entro_quando(client, mondo, urgente_inviato):
    client.force_login(mondo.richiedente.user)
    entro = timezone.localtime(urgente_inviato.inviata_il + timedelta(hours=4))
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[urgente_inviato.pk])))
    assert f'Risposta attesa entro il {entro:%d/%m} alle {entro:%H:%M} (urgente: 4 ore).' in pagina
