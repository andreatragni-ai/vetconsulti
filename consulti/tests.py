import hashlib
from datetime import date

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import (Clinica, CompetenzaRefertatore, DatiFatturazione, Refertatore, Richiedente,
                             TipoRichiedente)
from consulti import regole, upload_chunk
from consulti.models import (Allegato, AuditNonModificabile, CategoriaAllegato, ContatoreAnno, EventoAudit,
                             Paziente, Richiesta, StatoRichiesta, TransizioneNonValida)
from core.tipi import TipoEsame
from eco.models import ProiezioneCaricata, ProiezioneCatalogo, TipoMedia


# ── Fixture di base ──────────────────────────────────────────────────────────

@pytest.fixture
def clinica(db):
    c = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    DatiFatturazione.objects.create(
        clinica=c, intestatario='Clinica Rossi srl', partita_iva='00743110157',
        indirizzo_sede='Via Roma 1', cap='20100', comune='Milano', provincia='MI',
        codice_sdi='0000000', pec_fatturazione='rossi@pec.it', predefinita=True)
    return c


@pytest.fixture
def richiedente(clinica):
    u = User.objects.create_user('vet', 'vet@x.it', 'pw', first_name='Mario', last_name='Rossi')
    return Richiedente.objects.create(user=u, clinica=clinica)


@pytest.fixture
def refertatore(db):
    u = User.objects.create_user('ref', 'ref@x.it', 'pw', first_name='Anna', last_name='Bianchi')
    r = Refertatore.objects.create(user=u)
    CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=TipoEsame.ECG, referente=True)
    CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=TipoEsame.HOLTER, referente=True)
    return r


@pytest.fixture
def libero_professionista(db):
    u = User.objects.create_user('lp', 'lp@x.it', 'pw', first_name='Luca', last_name='Verdi')
    r = Richiedente.objects.create(user=u, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA, approvato=True)
    DatiFatturazione.objects.create(
        richiedente=r, intestatario='Luca Verdi', codice_fiscale='VRDLCU80A01F205X',
        indirizzo_sede='Via Verdi 2', cap='20100', comune='Milano', provincia='MI',
        codice_sdi='ABC1234', predefinita=True)
    return r


def _richiesta(richiedente, refertatore=None, tipo=TipoEsame.ECG, paziente=True):
    r = Richiesta.objects.create(tipo_esame=tipo, richiedente=richiedente, clinica=richiedente.clinica,
                                 refertatore=refertatore)
    if paziente:
        Paziente.objects.create(richiesta=r, nome='Fido')
    return r


def _allega(richiesta, categoria, nome='f.pdf', contenuto=b'%PDF-1.4 x'):
    return Allegato.da_upload(richiesta, SimpleUploadedFile(nome, contenuto), categoria)


# ── Codice ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_codice_progressivo_per_anno(richiedente):
    anno = timezone.now().year
    a = _richiesta(richiedente)
    b = _richiesta(richiedente)
    assert a.codice == f'TC-{anno}-0001'
    assert b.codice == f'TC-{anno}-0002'
    assert ContatoreAnno.objects.get(anno=anno).ultimo == 2
    # Il codice non cambia ai salvataggi successivi.
    a.quesito = 'x'
    a.save()
    assert a.codice == f'TC-{anno}-0001'


@pytest.mark.django_db
def test_codice_univoco_anche_dopo_cancellazione(richiedente):
    a = _richiesta(richiedente)
    codice_a = a.codice
    a.delete()
    b = _richiesta(richiedente)
    assert b.codice != codice_a


# ── Regole di invio ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_perche_non_puoi_inviare_percorso_completo(richiedente, refertatore):
    r = _richiesta(richiedente, paziente=False)
    assert 'paziente' in regole.perche_non_puoi_inviare(r)
    Paziente.objects.create(richiesta=r, nome='Fido')
    assert 'refertatore' in regole.perche_non_puoi_inviare(r)
    r.refertatore = refertatore
    r.save()
    assert 'tracciato ECG' in regole.perche_non_puoi_inviare(r)
    _allega(r, CategoriaAllegato.ECG_IMMAGINE, 'ecg.png', b'png')
    assert regole.perche_non_puoi_inviare(r) is None


@pytest.mark.django_db
def test_refertatore_non_referente_per_il_tipo(richiedente, refertatore):
    r = _richiesta(richiedente, refertatore, tipo=TipoEsame.ECO)
    assert 'non e\' referente' in regole.perche_non_puoi_inviare(r)


@pytest.mark.django_db
def test_senza_dati_fatturazione_non_si_invia(richiedente, refertatore):
    richiedente.clinica.dati_fatturazione.all().delete()
    r = _richiesta(richiedente, refertatore)
    assert 'fatturazione' in regole.perche_non_puoi_inviare(r)


@pytest.mark.django_db
def test_clinica_non_approvata(richiedente, refertatore):
    richiedente.clinica.approvata = False
    richiedente.clinica.save()
    r = _richiesta(richiedente, refertatore)
    assert 'approvata' in regole.perche_non_puoi_inviare(r)


@pytest.mark.django_db
def test_holter_richiede_referto(richiedente, refertatore):
    r = _richiesta(richiedente, refertatore, tipo=TipoEsame.HOLTER)
    assert 'Holter' in regole.perche_non_puoi_inviare(r)
    _allega(r, CategoriaAllegato.HOLTER_REFERTO)
    assert regole.perche_non_puoi_inviare(r) is None


@pytest.mark.django_db
def test_eco_richiede_pdf_e_proiezioni_obbligatorie(richiedente, refertatore):
    CompetenzaRefertatore.objects.create(refertatore=refertatore, tipo_esame=TipoEsame.ECO, referente=True)
    p1 = ProiezioneCatalogo.objects.create(codice='A', nome='Quattro camere', obbligatoria=True, ordine=1)
    ProiezioneCatalogo.objects.create(codice='B', nome='Facoltativa', obbligatoria=False, ordine=2)
    ProiezioneCatalogo.objects.create(codice='C', nome='Disattivata', obbligatoria=True, attiva=False, ordine=3)
    r = _richiesta(richiedente, refertatore, tipo=TipoEsame.ECO)
    motivo = regole.perche_non_puoi_inviare(r)
    assert 'ecografo' in motivo and 'Quattro camere' in motivo and 'Disattivata' not in motivo
    _allega(r, CategoriaAllegato.ECO_REFERTO_PDF)
    assert regole.perche_non_puoi_inviare(r) == 'Manca la proiezione «Quattro camere».'
    clip = _allega(r, CategoriaAllegato.ECO_CLIP, 'c.mp4', b'mp4')
    ProiezioneCaricata.objects.create(richiesta=r, proiezione=p1, allegato=clip)
    assert regole.perche_non_puoi_inviare(r) is None


@pytest.mark.django_db
def test_elementi_obbligatori_sono_la_stessa_regola_della_frase(richiedente, refertatore):
    """La lista con le caselle (passo «Carica gli esami») e la frase di
    perche_non_puoi_inviare vengono dalla stessa funzione: stessi elementi,
    stesso ordine, e a lista tutta spuntata corrisponde nessun blocco."""
    CompetenzaRefertatore.objects.create(refertatore=refertatore, tipo_esame=TipoEsame.ECO, referente=True)
    p1 = ProiezioneCatalogo.objects.create(codice='A', nome='Quattro camere', obbligatoria=True, ordine=2)
    p2 = ProiezioneCatalogo.objects.create(codice='B', nome='Asse corto', obbligatoria=True, ordine=1)
    ProiezioneCatalogo.objects.create(codice='C', nome='Facoltativa', obbligatoria=False, ordine=3)
    r = _richiesta(richiedente, refertatore, tipo=TipoEsame.ECO)
    elementi = regole.elementi_obbligatori(r)
    assert [e.etichetta for e in elementi] == ['Referto dell\'ecografo (PDF)', 'Asse corto', 'Quattro camere']
    assert [e.proiezione_id for e in elementi] == [None, p2.id, p1.id]
    assert not any(e.fatto for e in elementi)
    assert regole.allegati_mancanti(r) == [e.frase for e in elementi]
    assert regole.perche_non_puoi_inviare(r) == 'Mancano: ' + '; '.join(e.frase for e in elementi) + '.'
    _allega(r, CategoriaAllegato.ECO_REFERTO_PDF)
    clip = _allega(r, CategoriaAllegato.ECO_CLIP, 'c.mp4', b'mp4')
    ProiezioneCaricata.objects.create(richiesta=r, proiezione=p2, allegato=clip)
    fatti = {e.chiave: e.fatto for e in regole.elementi_obbligatori(r)}
    assert fatti == {'eco_referto': True, f'proiezione_{p2.id}': True, f'proiezione_{p1.id}': False}
    assert regole.perche_non_puoi_inviare(r) == 'Manca la proiezione «Quattro camere».'
    ProiezioneCaricata.objects.create(richiesta=r, proiezione=p1, allegato=clip)
    assert all(e.fatto for e in regole.elementi_obbligatori(r))
    assert regole.perche_non_puoi_inviare(r) is None


@pytest.mark.django_db
@pytest.mark.parametrize('tipo, categoria', [(TipoEsame.ECG, CategoriaAllegato.ECG_IMMAGINE),
                                             (TipoEsame.HOLTER, CategoriaAllegato.HOLTER_REFERTO)])
def test_elementi_obbligatori_ecg_e_holter(richiedente, refertatore, tipo, categoria):
    r = _richiesta(richiedente, refertatore, tipo=tipo)
    [elemento] = regole.elementi_obbligatori(r)
    assert not elemento.fatto and regole.perche_non_puoi_inviare(r) == f'Manca {elemento.frase}.'
    _allega(r, categoria)
    [elemento] = regole.elementi_obbligatori(r)
    assert elemento.fatto and regole.perche_non_puoi_inviare(r) is None


@pytest.mark.django_db
def test_intestatario_clinica_e_libero_professionista(richiedente, libero_professionista):
    a = _richiesta(richiedente)
    assert a.intestatario() == richiedente.clinica
    assert a.intestatario().denominazione == 'Clinica Rossi'
    b = _richiesta(libero_professionista)
    assert b.clinica is None
    assert b.intestatario() == libero_professionista
    assert b.intestatario().denominazione == 'Luca Verdi'
    assert b.intestatario().dati_fatturazione_predefiniti.codice_sdi == 'ABC1234'


@pytest.mark.django_db
def test_invio_libero_professionista(libero_professionista, refertatore):
    r = _richiesta(libero_professionista, refertatore)
    _allega(r, CategoriaAllegato.ECG_PDF)
    assert regole.perche_non_puoi_inviare(r) is None
    # Senza approvazione del profilo (non della clinica) non parte.
    libero_professionista.approvato = False
    libero_professionista.save()
    r.refresh_from_db()
    assert 'profilo' in regole.perche_non_puoi_inviare(r)
    libero_professionista.approvato = True
    libero_professionista.save()
    # Senza dati fiscali propri non parte.
    libero_professionista.dati_fatturazione.all().delete()
    r.refresh_from_db()
    assert 'fatturazione' in regole.perche_non_puoi_inviare(r)


@pytest.mark.django_db
def test_libero_professionista_crea_bozza_e_invia(client, libero_professionista, refertatore):
    client.force_login(libero_professionista.user)
    risp = client.post(reverse('consulti:nuova'), {
        'r-tipo_esame': 'ECG', 'r-refertatore': refertatore.pk, 'p-nome': 'Micio', 'p-specie': 'GATTO', 'p-sesso': 'F'})
    assert risp.status_code == 302
    r = Richiesta.objects.get()
    assert r.clinica is None and r.richiedente == libero_professionista
    _allega(r, CategoriaAllegato.ECG_PDF)
    assert client.post(reverse('consulti:invia', args=[r.pk])).status_code == 302
    r.refresh_from_db()
    assert r.stato == StatoRichiesta.INVIATA
    pagina = client.get(reverse('consulti:dettaglio', args=[r.pk])).content.decode()
    assert 'Luca Verdi' in pagina and 'libero professionista' in pagina


# ── Transizioni e audit ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_ciclo_di_vita_con_audit(richiedente, refertatore):
    r = _richiesta(richiedente, refertatore)
    _allega(r, CategoriaAllegato.ECG_PDF)
    r.invia(richiedente.user)
    assert r.stato == StatoRichiesta.INVIATA and r.inviata_il
    r.prendi_in_carico(refertatore)
    assert r.stato == StatoRichiesta.PRESA_IN_CARICO and r.presa_in_carico_il
    r.rilascia_presa_in_carico(motivo='test')
    assert r.stato == StatoRichiesta.INVIATA and r.presa_in_carico_il is None
    r.prendi_in_carico(refertatore)
    r.declina('Tracciato illeggibile')
    assert r.stato == StatoRichiesta.DECLINATA and r.chiusa_il and r.motivo_rifiuto == 'Tracciato illeggibile'
    azioni = list(r.audit.values_list('azione', flat=True))
    assert azioni == ['ALLEGATO_CARICATO', 'INVIATA', 'PRESA_IN_CARICO', 'RILASCIATA', 'PRESA_IN_CARICO', 'DECLINATA']


@pytest.mark.django_db
def test_transizioni_non_ammesse(richiedente, refertatore):
    r = _richiesta(richiedente, refertatore)
    with pytest.raises(TransizioneNonValida):
        r.invia()  # manca l'allegato
    with pytest.raises(TransizioneNonValida):
        r.prendi_in_carico(refertatore)  # e' in bozza
    with pytest.raises(TransizioneNonValida):
        r.declina('x')
    r.annulla()
    assert r.stato == StatoRichiesta.ANNULLATA
    with pytest.raises(TransizioneNonValida):
        r.annulla()


@pytest.mark.django_db
def test_declinare_senza_motivo_non_si_puo(richiedente, refertatore):
    r = _richiesta(richiedente, refertatore)
    _allega(r, CategoriaAllegato.ECG_PDF)
    r.invia()
    with pytest.raises(TransizioneNonValida):
        r.declina('   ')


@pytest.mark.django_db
def test_audit_append_only(richiedente):
    r = _richiesta(richiedente)
    e = r.registra('CREATA')
    e.azione = 'ALTRO'
    with pytest.raises(AuditNonModificabile):
        e.save()
    with pytest.raises(AuditNonModificabile):
        e.delete()
    with pytest.raises(AuditNonModificabile):
        EventoAudit.objects.filter(pk=e.pk).delete()
    with pytest.raises(AuditNonModificabile):
        EventoAudit.objects.filter(pk=e.pk).update(azione='X')
    assert EventoAudit.objects.get(pk=e.pk).azione == 'CREATA'


# ── sorveglia_consulti ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sorveglia_rilascia_le_ferme(richiedente, refertatore, settings):
    from datetime import timedelta
    from io import StringIO
    from django.core.management import call_command
    settings.CONSULTI_ORE_PRESA_IN_CARICO = 24
    r = _richiesta(richiedente, refertatore)
    _allega(r, CategoriaAllegato.ECG_PDF)
    r.invia()
    r.prendi_in_carico(refertatore)
    Richiesta.objects.filter(pk=r.pk).update(presa_in_carico_il=timezone.now() - timedelta(hours=30))
    out = StringIO()
    call_command('sorveglia_consulti', stdout=out)
    r.refresh_from_db()
    assert r.stato == StatoRichiesta.INVIATA
    assert r.codice in out.getvalue()
    assert r.audit.filter(azione='RILASCIATA').exists()


# ── Upload a pezzi (portato da VetCardio, solo il chunking) ─────────────────

@pytest.fixture
def bozza_con_login(client, richiedente, refertatore):
    r = _richiesta(richiedente, refertatore, tipo=TipoEsame.HOLTER)
    client.force_login(richiedente.user)
    return r


class TestUploadAPezzi:
    contenuto = b'HOLTERBLOB' * 5000
    impronta = hashlib.sha256(contenuto).hexdigest()

    @pytest.fixture(autouse=True)
    def _pulisci(self):
        yield
        upload_chunk.abbandona(self.impronta)

    def _pezzo(self, client, richiesta, offset, dati):
        return client.post(reverse('consulti:upload_pezzo', args=[richiesta.pk]),
                           {'impronta': self.impronta, 'offset': str(offset),
                            'pezzo': SimpleUploadedFile('p', dati)})

    def test_un_file_arriva_a_pezzi(self, client, bozza_con_login):
        r = bozza_con_login
        meta = len(self.contenuto) // 2
        assert self._pezzo(client, r, 0, self.contenuto[:meta]).json()['ricevuti'] == meta
        assert self._pezzo(client, r, meta, self.contenuto[meta:]).json()['ricevuti'] == len(self.contenuto)
        risp = client.post(reverse('consulti:upload_concludi', args=[r.pk]),
                           {'impronta': self.impronta, 'nome': 'paziente.ecg', 'categoria': 'HOLTER_FILE'})
        assert risp.status_code == 200
        a = r.allegati.get()
        assert a.nome_originale == 'paziente.ecg'
        assert a.sha256 == self.impronta
        assert a.dimensione == len(self.contenuto)
        assert a.file.read() == self.contenuto
        assert upload_chunk.quanto_ho(self.impronta) == 0

    def test_si_riprende_da_dove_si_era_interrotto(self, client, bozza_con_login):
        r = bozza_con_login
        meta = len(self.contenuto) // 2
        self._pezzo(client, r, 0, self.contenuto[:meta])
        risp = client.get(reverse('consulti:upload_stato', args=[r.pk]), {'impronta': self.impronta})
        assert risp.json()['ricevuti'] == meta
        self._pezzo(client, r, meta, self.contenuto[meta:])
        assert upload_chunk.quanto_ho(self.impronta) == len(self.contenuto)

    def test_un_pezzo_fuori_sequenza_e_rifiutato(self, client, bozza_con_login):
        r = bozza_con_login
        self._pezzo(client, r, 0, self.contenuto[:100])
        risp = self._pezzo(client, r, 9999, self.contenuto[100:])
        assert risp.status_code == 409
        assert risp.json()['ricevuti'] == 100

    def test_un_file_corrotto_non_si_attacca(self, client, bozza_con_login):
        r = bozza_con_login
        self._pezzo(client, r, 0, b'non e il file giusto')
        risp = client.post(reverse('consulti:upload_concludi', args=[r.pk]),
                           {'impronta': self.impronta, 'nome': 'x.dat', 'categoria': 'HOLTER_FILE'})
        assert risp.status_code == 400
        assert not r.allegati.exists()

    def test_un_impronta_inventata_non_costruisce_percorsi(self, client, bozza_con_login):
        risp = client.get(reverse('consulti:upload_stato', args=[bozza_con_login.pk]),
                          {'impronta': '../../etc/passwd'})
        assert risp.status_code == 400

    def test_oltre_il_limite_si_ferma(self, client, bozza_con_login, settings):
        settings.UPLOAD_MAX_BYTE = 100
        risp = self._pezzo(client, bozza_con_login, 0, self.contenuto)
        assert risp.status_code == 409
        assert 'limite' in risp.json()['errore']

    def test_solo_chi_ha_titolo_scarica_il_file(self, client, bozza_con_login):
        r = bozza_con_login
        self._pezzo(client, r, 0, self.contenuto)
        client.post(reverse('consulti:upload_concludi', args=[r.pk]),
                    {'impronta': self.impronta, 'nome': 'x.dat', 'categoria': 'HOLTER_FILE'})
        a = r.allegati.get()
        assert client.get(reverse('scarica_allegato', args=[a.pk])).status_code == 200
        estraneo = User.objects.create_user('estraneo', 'e@x.it', 'pw')
        client.force_login(estraneo)
        assert client.get(reverse('scarica_allegato', args=[a.pk])).status_code == 404


# ── Pagine ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_pagine_base_rispondono(client, richiedente, refertatore):
    client.force_login(richiedente.user)
    assert client.get(reverse('consulti:mie_richieste')).status_code == 200
    assert client.get(reverse('consulti:nuova')).status_code == 200
    risp = client.get(reverse('consulti:esperti'), {'tipo_esame': 'ECG'})
    assert risp.status_code == 200 and 'Bianchi' in risp.content.decode()


@pytest.mark.django_db
def test_creazione_bozza_da_form(client, richiedente, refertatore):
    client.force_login(richiedente.user)
    risp = client.post(reverse('consulti:nuova'), {
        'r-tipo_esame': 'ECG', 'r-refertatore': refertatore.pk, 'r-quesito': 'Aritmia?',
        'p-nome': 'Fido', 'p-specie': 'CANE', 'p-sesso': 'M',
    })
    assert risp.status_code == 302
    r = Richiesta.objects.get()
    assert r.stato == StatoRichiesta.BOZZA and r.paziente.nome == 'Fido' and r.refertatore == refertatore
    assert client.get(reverse('consulti:dettaglio', args=[r.pk])).status_code == 200


@pytest.mark.django_db
def test_elimina_allegato_solo_in_bozza(client, richiedente, refertatore):
    r = _richiesta(richiedente, refertatore)
    a = _allega(r, CategoriaAllegato.ECG_PDF)
    client.force_login(richiedente.user)
    assert client.post(reverse('consulti:elimina_allegato', args=[r.pk, a.pk])).status_code == 302
    assert not r.allegati.exists()
    assert r.audit.filter(azione='ALLEGATO_ELIMINATO').exists()
    b = _allega(r, CategoriaAllegato.ECG_PDF)
    r.invia()
    client.post(reverse('consulti:elimina_allegato', args=[r.pk, b.pk]))
    assert r.allegati.count() == 1  # dopo l'invio non si tocca
    estraneo = User.objects.create_user('x', 'x@x.it', 'pw')
    client.force_login(estraneo)
    assert client.post(reverse('consulti:elimina_allegato', args=[r.pk, b.pk])).status_code == 404


def test_ogni_stato_ha_un_tono_per_la_pillola():
    """La pillola .pill-stato di vetway-ui prende il tono da Richiesta.TONO_STATO:
    uno stato nuovo senza tono uscirebbe grigio in silenzio."""
    assert set(Richiesta.TONO_STATO) == {s.value for s in StatoRichiesta}
    assert set(Richiesta.TONO_STATO.values()) <= {'', 'corso', 'ok', 'attesa', 'chiusa', 'errore'}


# ── Nuova richiesta dal form: l'esperto dipende dal tipo scelto ─────────────

@pytest.fixture
def esperto_eco(db):
    """Referente solo per l'eco: e' il caso che il bug del prefisso rompeva."""
    u = User.objects.create_user('eco', 'eco@x.it', 'pw', first_name='Laura', last_name='Monti')
    r = Refertatore.objects.create(user=u)
    CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=TipoEsame.ECO, referente=True)
    return r


def _crea_dal_form(client, tipo, esperto):
    return client.post(reverse('consulti:nuova'), {
        'r-tipo_esame': tipo, 'r-refertatore': esperto.pk, 'r-quesito': 'Soffio da valutare',
        'p-nome': 'Luna', 'p-specie': 'GATTO', 'p-sesso': 'ND'})


@pytest.mark.django_db
@pytest.mark.parametrize('tipo', [TipoEsame.ECO, TipoEsame.HOLTER, TipoEsame.ECG])
def test_nuova_richiesta_accetta_l_esperto_del_tipo_scelto(client, richiedente, refertatore, esperto_eco, tipo):
    """Il form ha il prefisso 'r': il tipo va letto da 'r-tipo_esame'. Prima si
    leggeva 'tipo_esame', il tipo risultava sempre ECG e chiedere un'eco a un
    referente solo eco dava 'Scegli un'opzione valida'."""
    esperto = esperto_eco if tipo == TipoEsame.ECO else refertatore
    client.force_login(richiedente.user)
    risposta = _crea_dal_form(client, tipo, esperto)
    assert risposta.status_code == 302, 'la richiesta non e\' stata creata'
    creata = Richiesta.objects.get()
    assert creata.tipo_esame == tipo and creata.refertatore == esperto


@pytest.mark.django_db
def test_nuova_richiesta_rifiuta_un_esperto_non_referente_per_quel_tipo(client, richiedente, refertatore):
    """Il rovescio: Anna referta ECG e Holter, non l'eco."""
    client.force_login(richiedente.user)
    risposta = _crea_dal_form(client, TipoEsame.ECO, refertatore)
    assert risposta.status_code == 200
    assert not Richiesta.objects.exists()
