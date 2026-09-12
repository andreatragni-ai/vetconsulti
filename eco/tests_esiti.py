"""
Test della misura sul campo dello smistamento (EsitoSmistamento,
eco/smistamento/esiti.py e `manage.py accuratezza_smistamento`): la proposta
si fotografa quando lo smistamento finisce, la conferma dice dove il file e'
finito davvero, e il dato sopravvive a tutto cio' che gli succede intorno.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.forms.models import model_to_dict
from django.urls import reverse
from django.utils import timezone

from consulti.models import Allegato
from consulti.tests_smistamento import (_avvia, _cartella, ai_finta, esame_caricato,  # noqa: F401
                                        _jpeg)
from consulti.tests_percorso import (MP4, PDF, bozza_eco, catalogo,  # noqa: F401
                                     esperto_eco, loggato)
from eco.models import EsitoSmistamento, PropostaSmistamento
from eco.smistamento.dati import Lettura


LETTURE = {
    'IMG_0001.mp4': Lettura('PDC', confidenza='alta', tracciato='2D', motivo='quattro camere da destra'),
    'IMG_0002.mp4': Lettura('AP4', confidenza='media', tracciato='2D', motivo='apicale'),
    'IMG_0003.mp4': Lettura(None, motivo='fuori fuoco'),
    'IMG_0004.jpg': Lettura('PDS', confidenza='alta', tracciato='M', motivo='base del cuore'),
}


def _esiti(richiesta):
    return {e.allegato_interno: e for e in EsitoSmistamento.objects.filter(richiesta=richiesta)}


def _per_nome(richiesta):
    ids = dict(richiesta.allegati.values_list('nome_originale', 'pk'))
    esiti = _esiti(richiesta)
    return {nome: esiti[pk] for nome, pk in ids.items() if pk in esiti}


# ── La fotografia e la conferma ──────────────────────────────────────────────

def test_la_proposta_si_fotografa_e_la_conferma_dice_dove_e_finita(
        loggato, esame_caricato, catalogo, ai_finta, django_capture_on_commit_callbacks):
    ai_finta(LETTURE)
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    # Appena smistato: cinque file fotografati, nessuno ancora confermato.
    assert EsitoSmistamento.objects.count() == 5
    assert not EsitoSmistamento.objects.filter(confermato_il__isnull=False).exists()

    # Il collega corregge: IMG_0002 non era l'apicale, era l'arteria polmonare.
    allegato = esame_caricato.allegati.get(nome_originale='IMG_0002.mp4')
    risposta = loggato.post(reverse('consulti:smistamento_sposta', args=[esame_caricato.pk]),
                            {'allegato': allegato.pk, 'destinazione': f'proiezione:{catalogo["pd_facoltativa"].pk}'})
    assert risposta.status_code == 302
    assert loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk])).status_code == 302

    esiti = _per_nome(esame_caricato)
    giusto = esiti['IMG_0001.mp4']
    assert (giusto.proposta, giusto.finale, giusto.corretto, giusto.sicura) == ('PDC', 'PDC', False, True)
    assert giusto.fonte == 'AI' and giusto.tracciato == '2D' and giusto.confermato
    corretto = esiti['IMG_0002.mp4']
    assert (corretto.proposta, corretto.finale, corretto.corretto) == ('AP4', 'PDF', True)
    assert not corretto.sicura
    non_assegnato = esiti['IMG_0003.mp4']
    assert (non_assegnato.proposta, non_assegnato.finale, non_assegnato.corretto) == ('', '', False)
    referto = esiti['referto.pdf']
    assert referto.proposta_referto and referto.finale_referto and not referto.corretto


def test_l_esito_sopravvive_alla_proposta_consumata_e_al_file_cancellato(
        loggato, esame_caricato, catalogo, ai_finta, django_capture_on_commit_callbacks):
    """La proposta viene consumata (uno spostamento a mano le riscrive fonte e
    riga): l'esito no, e per questo si puo' ancora misurare."""
    ai_finta(LETTURE)
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    allegato = esame_caricato.allegati.get(nome_originale='IMG_0002.mp4')
    loggato.post(reverse('consulti:smistamento_sposta', args=[esame_caricato.pk]),
                 {'allegato': allegato.pk, 'destinazione': f'proiezione:{catalogo["pd_facoltativa"].pk}'})
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    # La proposta non ricorda piu' cosa aveva detto l'AI...
    proposta = PropostaSmistamento.objects.get(allegato=allegato)
    assert proposta.fonte == 'MANUALE' and proposta.proiezione.codice == 'PDF'
    # ...l'esito si'.
    esito = EsitoSmistamento.objects.get(allegato_interno=allegato.pk)
    assert esito.proposta == 'AP4' and esito.corretto
    # E resta anche se il file se ne va (non e' una chiave esterna).
    identificativo = allegato.pk
    allegato.delete()
    assert not Allegato.objects.filter(pk=identificativo).exists()
    assert EsitoSmistamento.objects.get(allegato_interno=identificativo).proposta == 'AP4'


def test_l_esito_non_contiene_dati_del_paziente(
        loggato, esame_caricato, catalogo, ai_finta, django_capture_on_commit_callbacks):
    ai_finta(LETTURE)
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    paziente = esame_caricato.paziente.nome                     # «Luna»
    for esito in EsitoSmistamento.objects.all():
        valori = ' '.join(str(v) for v in model_to_dict(esito).values())
        assert paziente.lower() not in valori.lower()
        assert 'IMG_' not in valori and '.mp4' not in valori    # nemmeno i nomi dei file
        assert esito.codice_richiesta == esame_caricato.codice  # solo identificativi interni


def test_un_secondo_giro_rigiudica_solo_cio_che_rismista(
        loggato, esame_caricato, catalogo, ai_finta, django_capture_on_commit_callbacks):
    """Un giro nuovo non tocca cio' che e' gia' confermato (esecuzione.py lo
    lascia dov'e'), quindi nemmeno il suo esito: rigiudica solo i file che
    rimette in gioco. E resta una riga per file, non due."""
    ai_finta(LETTURE)
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    loggato.post(reverse('consulti:smistamento_conferma', args=[esame_caricato.pk]))
    assert EsitoSmistamento.objects.filter(confermato_il__isnull=False).count() == 5
    ai_finta(LETTURE)
    _avvia(loggato, esame_caricato, django_capture_on_commit_callbacks)
    assert EsitoSmistamento.objects.count() == 5
    esiti = _per_nome(esame_caricato)
    assert esiti['IMG_0001.mp4'].confermato                    # gia' confermato: non si rimette in gioco
    assert not esiti['IMG_0003.mp4'].confermato                # era da smistare: proposta nuova, da confermare


# ── Il comando ───────────────────────────────────────────────────────────────

def _esito(codice='TC-2026-0001', allegato=1, proposta='PDC', finale='PDC', sicura=True, fonte='AI',
           quando=None, **extra):
    return EsitoSmistamento.objects.create(
        codice_richiesta=codice, allegato_interno=allegato, modello='claude-opus-5', proposta=proposta,
        finale=finale, sicura=sicura, fonte=fonte, corretto=proposta != finale, tracciato='2D',
        confermato_il=quando or timezone.now(), **extra)


def _lancia(**opzioni):
    uscita = StringIO()
    call_command('accuratezza_smistamento', stdout=uscita, **opzioni)
    return uscita.getvalue()


@pytest.mark.django_db
def test_senza_esami_il_comando_lo_dice_invece_di_stampare_zeri():
    testo = _lancia()
    assert 'Nessun esame ancora' in testo
    assert '0%' not in testo and '0/0' not in testo


@pytest.mark.django_db
def test_le_conferme_non_ancora_avvenute_non_contano():
    EsitoSmistamento.objects.create(codice_richiesta='TC-2026-0001', allegato_interno=1, proposta='PDC')
    assert 'Nessun esame ancora' in _lancia()


@pytest.mark.django_db
def test_i_conti_del_comando(catalogo):
    # Un esame: 4 proposte giuste, 2 sbagliate (di cui una col bollino
    # «sicuro»), 2 file che l'automatismo non ha saputo assegnare.
    for i in range(4):
        _esito(allegato=i, proposta='PDC', finale='PDC', sicura=True)
    _esito(allegato=10, proposta='AP4', finale='PDF', sicura=False)      # da verificare, sbagliato
    _esito(allegato=11, proposta='PDS', finale='AP4', sicura=True)       # «sicuro» sbagliato: il numero che conta
    _esito(allegato=12, proposta='', finale='AP4', sicura=False, fonte='')
    _esito(allegato=13, proposta='', finale='', sicura=False, fonte='')
    testo = _lancia()
    assert '8 file in un esame,' in testo
    assert 'Proposta fatta: 6/8 (75%)' in testo
    assert 'Riga giusta sulle proposte fatte: 4/6 (67%)' in testo
    assert 'Riga giusta su tutti i file:      4/8 (50%)' in testo
    assert '«Sicuro»:       4/5 (80%) giusti' in testo
    assert '«Sicuri» sbagliati: 1' in testo
    assert '«Da verificare»: 0/1 (0%) giusti' in testo
    assert 'AP4 <- PDS  (x1)' in testo                                  # la confusione
    assert 'Parasternale destra' in testo                               # per finestra
    assert 'Asse lungo 4 camere' in testo                               # per riga del catalogo
    assert 'un esame solo' in testo and 'un\'indicazione' in testo      # un solo esame: si avvisa


@pytest.mark.django_db
def test_nessun_sicuro_sbagliato_si_vede(catalogo):
    _esito(allegato=1)
    assert 'nessun file col bollino «sicuro»' in _lancia()


@pytest.mark.django_db
def test_da_lascia_fuori_il_collaudo(catalogo):
    _esito(allegato=1, quando=timezone.now() - timedelta(days=30))
    _esito(allegato=2, quando=timezone.now())
    assert '2 file in un esame' in _lancia()
    ieri = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    assert '1 file in un esame' in _lancia(da=ieri)
    vecchio = (timezone.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    assert '2 file in un esame' in _lancia(da=vecchio)


@pytest.mark.django_db
def test_json(catalogo, tmp_path):
    _esito(allegato=1)
    _esito(allegato=2, proposta='AP4', finale='PDS', sicura=True)
    percorso = tmp_path / 'misure.json'
    _lancia(json=str(percorso))
    import json
    numeri = json.loads(percorso.read_text(encoding='utf-8'))
    assert numeri['file'] == 2 and numeri['sicuri_sbagliati'] == 1 and numeri['esami'] == 1
