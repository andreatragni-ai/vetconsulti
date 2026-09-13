"""La Gestione: chi entra, cosa vede, e le due azioni di emergenza.

Ogni transizione nuova del modello (sposta_da_gestione, annulla_da_gestione)
ha qui i suoi test, dagli stati ammessi e da quelli no: regola del progetto.
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from consulti.models import Richiesta, StatoRichiesta, TransizioneNonValida
from gestione import casi as q


# ── Accesso ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('nome', ['gestione:cruscotto', 'gestione:casi'])
def test_solo_lo_staff_entra(client, mondo, nome):
    assert client.get(reverse(nome)).status_code == 302          # al login
    client.force_login(mondo.richiedente.user)
    assert client.get(reverse(nome)).status_code == 404          # non si dice che esiste
    client.force_login(mondo.ref.user)
    assert client.get(reverse(nome)).status_code == 404
    client.force_login(mondo.staff)
    assert client.get(reverse(nome)).status_code == 200


def test_le_azioni_non_sono_per_il_refertatore(client, caso_in_carico, mondo):
    client.force_login(mondo.ref.user)
    risp = client.post(reverse('gestione:annulla', args=[caso_in_carico.pk]), {'motivo': 'io'})
    assert risp.status_code == 404
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.PRESA_IN_CARICO


# ── Elenco e ritardi ─────────────────────────────────────────────────────────

def test_bozze_fuori_ritardo_dentro(caso_inviato, mondo):
    bozza = Richiesta.objects.create(tipo_esame='ECG', richiedente=mondo.richiedente, clinica=mondo.clinica)
    assert bozza not in q.inviati()
    # `ref` risponde in 24 ore: 25 ore dopo l'invio il caso e' in ritardo.
    adesso = caso_inviato.inviata_il + timedelta(hours=25)
    assert [r.pk for r in q.elenco('ritardo', adesso=adesso)] == [caso_inviato.pk]
    assert q.elenco('ritardo', adesso=caso_inviato.inviata_il + timedelta(hours=1)) == []


def test_un_declinato_non_e_in_ritardo(caso_inviato, mondo):
    caso_inviato.declina('non posso', mondo.ref.user)
    riga = q.elenco('aperti', adesso=timezone.now() + timedelta(days=30))[0]
    assert riga.scadenza is None and not riga.in_ritardo


def test_cerca_per_paziente(caso_inviato):
    assert len(q.elenco('tutti', 'fid')) == 1 and q.elenco('tutti', 'zzz') == []


def test_pagine_si_aprono(client, caso_in_carico, mondo):
    client.force_login(mondo.staff)
    assert b'Fido' in client.get(reverse('gestione:casi')).content
    html = client.get(reverse('gestione:caso', args=[caso_in_carico.pk])).content.decode()
    assert 'Affida a un altro esperto' in html and 'Bruno Test' in html
    assert 'Anna Test' not in html.split('Affida a un altro esperto')[1].split('Annulla il caso')[0]


# ── sposta_da_gestione ───────────────────────────────────────────────────────

@pytest.mark.parametrize('prima', ['INVIATA', 'PRESA_IN_CARICO', 'DECLINATA'])
def test_sposta_dagli_stati_aperti(caso_inviato, mondo, prima):
    if prima == 'PRESA_IN_CARICO':
        caso_inviato.prendi_in_carico(mondo.ref, mondo.ref.user)
    elif prima == 'DECLINATA':
        caso_inviato.declina('ferie', mondo.ref.user)
    inviata_prima = caso_inviato.inviata_il
    precedente = caso_inviato.sposta_da_gestione(mondo.ref2, 'non risponde', mondo.staff)
    caso_inviato.refresh_from_db()
    assert precedente == mondo.ref.pk
    assert caso_inviato.stato == StatoRichiesta.INVIATA and caso_inviato.refertatore == mondo.ref2
    assert caso_inviato.inviata_il >= inviata_prima and caso_inviato.presa_in_carico_il is None
    evento = caso_inviato.audit.get(azione='SPOSTATA_DA_GESTIONE')
    assert evento.utente == mondo.staff and evento.dettaglio['motivo'] == 'non risponde'


@pytest.mark.parametrize('stato', ['BOZZA', 'REFERTATA', 'NON_REFERTABILE', 'ANNULLATA'])
def test_sposta_rifiutato_dagli_altri_stati(caso_inviato, mondo, stato):
    Richiesta.objects.filter(pk=caso_inviato.pk).update(stato=stato)
    caso_inviato.refresh_from_db()
    with pytest.raises(TransizioneNonValida):
        caso_inviato.sposta_da_gestione(mondo.ref2, 'motivo', mondo.staff)


def test_sposta_vuole_motivo_ed_esperto_giusto(caso_inviato, mondo):
    with pytest.raises(TransizioneNonValida, match='motivo'):
        caso_inviato.sposta_da_gestione(mondo.ref2, '  ', mondo.staff)
    with pytest.raises(TransizioneNonValida, match='gia'):
        caso_inviato.sposta_da_gestione(mondo.ref, 'motivo', mondo.staff)
    mondo.ref2.competenze.update(referente=False)
    with pytest.raises(TransizioneNonValida, match='referente'):
        caso_inviato.sposta_da_gestione(mondo.ref2, 'motivo', mondo.staff)
    caso_inviato.refresh_from_db()
    assert caso_inviato.refertatore == mondo.ref and not caso_inviato.audit.filter(
        azione='SPOSTATA_DA_GESTIONE').exists()


def test_sposta_un_urgente_solo_a_chi_accetta_urgenze(caso_inviato, mondo):
    Richiesta.objects.filter(pk=caso_inviato.pk).update(urgenza=True)
    caso_inviato.refresh_from_db()
    with pytest.raises(TransizioneNonValida):
        caso_inviato.sposta_da_gestione(mondo.ref2, 'motivo', mondo.staff)
    mondo.ref2.competenze.update(accetta_urgenze=True)
    caso_inviato.sposta_da_gestione(mondo.ref2, 'motivo', mondo.staff)


def test_sposta_dalla_pagina_avvisa_tutti(client, caso_in_carico, mondo):
    client.force_login(mondo.staff)
    mail.outbox.clear()
    risp = client.post(reverse('gestione:sposta', args=[caso_in_carico.pk]),
                       {'refertatore': mondo.ref2.pk, 'motivo': 'in ospedale'})
    assert risp.status_code == 302
    destinatari = sorted(d for e in mail.outbox for d in e.to)
    assert destinatari == ['ref2@x.it', 'ref@x.it', 'vet@x.it']
    al_richiedente = next(e for e in mail.outbox if e.to == ['vet@x.it'])
    assert 'in ospedale' not in al_richiedente.body      # il motivo resta alla gestione
    al_vecchio = next(e for e in mail.outbox if e.to == ['ref@x.it'])
    assert 'in ospedale' not in al_vecchio.body


# ── annulla_da_gestione ──────────────────────────────────────────────────────

@pytest.mark.parametrize('prima', ['INVIATA', 'PRESA_IN_CARICO', 'DECLINATA'])
def test_annulla_dagli_stati_aperti(caso_inviato, mondo, prima):
    if prima == 'PRESA_IN_CARICO':
        caso_inviato.prendi_in_carico(mondo.ref, mondo.ref.user)
    elif prima == 'DECLINATA':
        caso_inviato.declina('ferie', mondo.ref.user)
    caso_inviato.annulla_da_gestione('ritirato al telefono', mondo.staff)
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.ANNULLATA and caso_inviato.chiusa_il
    assert caso_inviato.audit.get(azione='ANNULLATA_DA_GESTIONE').dettaglio['motivo'] == 'ritirato al telefono'
    assert not hasattr(caso_inviato, 'prestazione')


@pytest.mark.parametrize('stato', ['BOZZA', 'REFERTATA', 'NON_REFERTABILE', 'ANNULLATA'])
def test_annulla_rifiutato_dagli_altri_stati(caso_inviato, mondo, stato):
    Richiesta.objects.filter(pk=caso_inviato.pk).update(stato=stato)
    caso_inviato.refresh_from_db()
    with pytest.raises(TransizioneNonValida):
        caso_inviato.annulla_da_gestione('motivo', mondo.staff)


def test_annulla_vuole_il_motivo(caso_inviato, mondo):
    with pytest.raises(TransizioneNonValida):
        caso_inviato.annulla_da_gestione('', mondo.staff)


def test_annulla_dalla_pagina_avvisa_richiedente_ed_esperto(client, caso_in_carico, mondo):
    client.force_login(mondo.staff)
    mail.outbox.clear()
    client.post(reverse('gestione:annulla', args=[caso_in_carico.pk]), {'motivo': 'paziente deceduto'})
    assert sorted(d for e in mail.outbox for d in e.to) == ['ref@x.it', 'vet@x.it']
    assert all('paziente deceduto' in e.body for e in mail.outbox)
    # Il richiedente legge la decisione nella storia del suo caso, col motivo.
    client.force_login(mondo.richiedente.user)
    html = client.get(reverse('consulti:dettaglio', args=[caso_in_carico.pk])).content.decode()
    assert 'la gestione ha annullato il caso' in html and 'paziente deceduto' in html


def test_errore_di_transizione_torna_con_un_messaggio(client, caso_inviato, mondo):
    client.force_login(mondo.staff)
    risp = client.post(reverse('gestione:sposta', args=[caso_inviato.pk]),
                       {'refertatore': mondo.ref2.pk, 'motivo': ''}, follow=True)
    assert 'Serve un motivo' in risp.content.decode()


# ── Refertatori ─────────────────────────────────────────────────────────────

def _post_refertatore(ref, **extra):
    from accounts.forms import competenze_complete
    dati = {
        'u-first_name': ref.user.first_name or 'Anna', 'u-last_name': ref.user.last_name or 'Test',
        'u-email': ref.user.email, 'r-titolo': ref.titolo, 'r-specializzazione': '', 'r-numero_iscrizione': '',
        'r-ordine_provinciale': '', 'r-messaggio': '', 'r-attivo': 'on', 'r-assente_dal': '', 'r-assente_al': '',
        'r-soggetto_emittente': 'SOCIETA',
        'k-TOTAL_FORMS': '3', 'k-INITIAL_FORMS': '3', 'k-MIN_NUM_FORMS': '0', 'k-MAX_NUM_FORMS': '1000',
    }
    for i, c in enumerate(competenze_complete(ref)):
        dati.update({f'k-{i}-id': c.pk, f'k-{i}-tipo_esame': c.tipo_esame,
                     f'k-{i}-prezzo_personalizzato': '', f'k-{i}-tempo_risposta_ore': c.tempo_risposta_ore or ''})
        if c.referente:
            dati[f'k-{i}-referente'] = 'on'
    dati.update(extra)
    return dati


def test_scheda_refertatore_salva_competenze_e_disponibilita(client, mondo):
    from accounts.models import CompetenzaRefertatore
    client.force_login(mondo.staff)
    url = reverse('gestione:refertatore', args=[mondo.ref.pk])
    assert client.get(url).status_code == 200
    ecg = next(i for i in range(3) if CompetenzaRefertatore.objects.order_by('tipo_esame')
               .filter(refertatore=mondo.ref)[i].tipo_esame == 'ECG')
    risp = client.post(url, _post_refertatore(mondo.ref, **{
        f'k-{ecg}-prezzo_personalizzato': '55.00', f'k-{ecg}-accetta_urgenze': 'on',
        'r-assente_al': '2030-01-10', 'u-last_name': 'Verdi'}))
    assert risp.status_code == 302
    mondo.ref.refresh_from_db()
    comp = mondo.ref.competenza_per('ECG')
    assert str(comp.prezzo_personalizzato) == '55.00' and comp.accetta_urgenze
    assert str(mondo.ref.assente_al) == '2030-01-10' and mondo.ref.user.last_name == 'Verdi'


def test_in_proprio_senza_dati_non_salva_niente(client, mondo):
    from accounts.models import DatiFatturazione
    client.force_login(mondo.staff)
    url = reverse('gestione:refertatore', args=[mondo.ref.pk])
    risp = client.post(url, _post_refertatore(mondo.ref, **{'r-soggetto_emittente': 'REFERTATORE',
                                                              'u-last_name': 'Cambiato'}))
    assert risp.status_code == 200 and 'Non salvato' in risp.content.decode()
    mondo.ref.refresh_from_db()
    assert mondo.ref.soggetto_emittente == 'SOCIETA' and mondo.ref.user.last_name == 'Test'
    n = DatiFatturazione.objects.count()

    risp = client.post(url, _post_refertatore(mondo.ref, **{
        'r-soggetto_emittente': 'REFERTATORE', 'f-intestatario': 'Anna Test', 'f-partita_iva': '01234567897',
        'f-indirizzo_sede': 'Via Po 1', 'f-cap': '10100', 'f-comune': 'Torino', 'f-provincia': 'TO',
        'f-nazione': 'IT', 'f-codice_sdi': 'ABC1234', 'f-regime_iva': 'FORFETTARIO'}))
    assert risp.status_code == 302
    mondo.ref.refresh_from_db()
    assert mondo.ref.soggetto_emittente == 'REFERTATORE' and mondo.ref.dati_fatturazione.comune == 'Torino'
    assert DatiFatturazione.objects.count() == n + 1


def test_email_di_un_altro_account_rifiutata(client, mondo):
    client.force_login(mondo.staff)
    risp = client.post(reverse('gestione:refertatore', args=[mondo.ref.pk]),
                       _post_refertatore(mondo.ref, **{'u-email': 'ref2@x.it'}))
    assert risp.status_code == 200 and 'usa gia&#x27; questa email' in risp.content.decode()


def test_nuovo_refertatore_manda_invito_e_porta_alla_scheda(client, mondo):
    from accounts.models import Refertatore
    client.force_login(mondo.staff)
    mail.outbox.clear()
    risp = client.post(reverse('gestione:refertatore_nuovo'), {
        'first_name': 'Carla', 'last_name': 'Neri', 'email': 'carla@x.it', 'username': 'cneri',
        'titolo': 'Dott.ssa', 'tipi_referente': ['ECO']})
    nuovo = Refertatore.objects.get(user__username='cneri')
    assert risp.status_code == 302 and risp.url == reverse('gestione:refertatore', args=[nuovo.pk])
    assert nuovo.referta('ECO') and [e.to for e in mail.outbox] == [['carla@x.it']]


# ── Iscrizioni ──────────────────────────────────────────────────────────────

def test_iscrizioni_in_attesa_prima(client, mondo):
    from django.contrib.auth.models import User
    from accounts.models import Clinica, Richiedente
    c = Clinica.objects.create(denominazione='Clinica Nuova')
    Richiedente.objects.create(user=User.objects.create_user('n', 'n@x.it', 'pw'), clinica=c)
    client.force_login(mondo.staff)
    html = client.get(reverse('gestione:iscrizioni')).content.decode()
    attesa, approvati = html.split('Gia\' approvati')
    assert 'Clinica Nuova' in attesa and 'Clinica Rossi' in approvati
