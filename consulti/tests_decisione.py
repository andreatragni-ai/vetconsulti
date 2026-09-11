"""Test del lato refertatore sui casi (F3): decisioni, riassegnazione,
permessi, casi ricevuti, racconto dell'audit. Ogni transizione nuova o
usata ha il suo test (zona fragile consulti/regole.py). Fixture in conftest.py: mondo, caso_inviato, caso_in_carico.
La sorveglianza (sollecito e rilascio) sta in tests_sorveglianza.py."""

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from consulti import regole
from consulti.models import EventoAudit, Richiesta, StatoRichiesta, TransizioneNonValida
from consulti.racconto import racconta
from notifiche.models import InvioEmail, TipoInvio
from registro.models import Prestazione


def _post(client, utente, nome_url, pk, dati=None):
    client.force_login(utente)
    return client.post(reverse(nome_url, args=[pk]), dati or {})


# ── Presa in carico ──────────────────────────────────────────────────────────

def test_presa_in_carico_dalla_pagina(client, caso_inviato, mondo):
    risp = _post(client, mondo.ref.user, 'consulti:prendi_in_carico', caso_inviato.pk)
    assert risp.status_code == 302 and risp.url == reverse('referti:refertazione', args=[caso_inviato.pk])
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.PRESA_IN_CARICO
    assert caso_inviato.audit.filter(azione='PRESA_IN_CARICO', utente=mondo.ref.user).exists()
    # Nessuna email per la presa in carico: il richiedente la vede sul caso.
    assert not mail.outbox


def test_presa_in_carico_due_volte_non_passa(caso_in_carico, mondo):
    with pytest.raises(TransizioneNonValida):
        caso_in_carico.prendi_in_carico(mondo.ref)


# ── Declina ──────────────────────────────────────────────────────────────────

def test_declina_con_motivo(client, caso_inviato, mondo):
    risp = _post(client, mondo.ref.user, 'consulti:declina', caso_inviato.pk, {'motivo': 'Non referto gatti.'})
    assert risp.status_code == 302
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.DECLINATA
    assert caso_inviato.motivo_rifiuto == 'Non referto gatti.'
    assert caso_inviato.audit.filter(azione='DECLINATA').get().dettaglio['motivo'] == 'Non referto gatti.'
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.to == ['vet@x.it'] and 'declinato' in email.subject and 'Non referto gatti.' in email.body
    assert InvioEmail.objects.filter(tipo=TipoInvio.CASO_DECLINATO, esito='OK').count() == 1


def test_declina_senza_motivo_non_passa(client, caso_inviato, mondo):
    _post(client, mondo.ref.user, 'consulti:declina', caso_inviato.pk, {'motivo': '  '})
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.INVIATA
    assert not mail.outbox


def test_declina_anche_dopo_la_presa_in_carico(client, caso_in_carico, mondo):
    _post(client, mondo.ref.user, 'consulti:declina', caso_in_carico.pk, {'motivo': 'Assente fino al 24/09.'})
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.DECLINATA


# ── Riassegnazione dopo il declino ───────────────────────────────────────────

def test_riassegnazione_dopo_declina(client, caso_in_carico, mondo):
    from referti.models import Referto
    Referto.objects.create(richiesta=caso_in_carico, conclusioni='bozza del collega')
    caso_in_carico.declina('Non referto questa specie.', mondo.ref.user)
    mail.outbox.clear()

    client.force_login(mondo.richiedente.user)
    pagina = client.get(reverse('consulti:dettaglio', args=[caso_in_carico.pk])).content.decode()
    assert 'Non referto questa specie.' in pagina and 'Gira il caso a un altro esperto' in pagina

    risp = client.post(reverse('consulti:riassegna', args=[caso_in_carico.pk]), {'r-refertatore': mondo.ref2.pk})
    assert risp.status_code == 302
    r = Richiesta.objects.get(pk=caso_in_carico.pk)
    assert r.stato == StatoRichiesta.INVIATA and r.refertatore == mondo.ref2
    assert r.motivo_rifiuto == '' and r.chiusa_il is None and r.presa_in_carico_il is None
    assert r.codice == caso_in_carico.codice and r.allegati.count() == 1
    evento = r.audit.get(azione='RIASSEGNATA')
    assert evento.dettaglio == {'da': mondo.ref.id, 'refertatore': mondo.ref2.id}
    # La bozza del collega che ha declinato non passa al nuovo esperto.
    assert not Referto.objects.filter(richiesta=r).exists()
    assert mail.outbox[0].to == ['ref2@x.it'] and 'Nuovo caso' in mail.outbox[0].subject
    # E il nuovo esperto lo prende in carico come un caso qualsiasi.
    r.prendi_in_carico(mondo.ref2)
    assert r.stato == StatoRichiesta.PRESA_IN_CARICO


def test_riassegnare_solo_un_caso_declinato_e_a_un_referente(caso_inviato, mondo):
    from accounts.models import CompetenzaRefertatore
    with pytest.raises(TransizioneNonValida):
        caso_inviato.riassegna(mondo.ref2)  # e' INVIATA, non declinata
    caso_inviato.declina('no')
    CompetenzaRefertatore.objects.filter(refertatore=mondo.ref2).update(referente=False)
    with pytest.raises(TransizioneNonValida, match='non e\' referente'):
        caso_inviato.riassegna(mondo.ref2)
    assert 'Scegli' in regole.perche_non_puoi_riassegnare(caso_inviato, None)


def test_riassegna_solo_il_richiedente(client, caso_inviato, mondo):
    caso_inviato.declina('no')
    for utente in (mondo.ref.user, mondo.staff, mondo.estraneo):
        assert _post(client, utente, 'consulti:riassegna', caso_inviato.pk,
                     {'r-refertatore': mondo.ref2.pk}).status_code == 404
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.DECLINATA


# ── Non refertabile ──────────────────────────────────────────────────────────

def test_non_refertabile_senza_prestazione(client, caso_in_carico, mondo):
    risp = _post(client, mondo.ref.user, 'consulti:non_refertabile', caso_in_carico.pk,
                 {'voce': 'Derivazioni inadeguate o mancanti', 'dettaglio': 'Manca la II.'})
    assert risp.status_code == 302
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.NON_REFERTABILE
    assert caso_in_carico.motivo_rifiuto == 'Derivazioni inadeguate o mancanti: Manca la II.'
    assert not Prestazione.objects.filter(richiesta=caso_in_carico).exists()
    assert caso_in_carico.audit.filter(azione='NON_REFERTABILE').exists()
    assert InvioEmail.objects.filter(tipo=TipoInvio.NON_REFERTABILE, destinatario='vet@x.it').count() == 1
    assert 'Manca la II.' in mail.outbox[0].body


def test_non_refertabile_altro_vuole_il_dettaglio(client, caso_in_carico, mondo):
    _post(client, mondo.ref.user, 'consulti:non_refertabile', caso_in_carico.pk, {'voce': 'Altro', 'dettaglio': ''})
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.PRESA_IN_CARICO


def test_non_refertabile_solo_dopo_la_presa_in_carico(client, caso_inviato, mondo):
    _post(client, mondo.ref.user, 'consulti:non_refertabile', caso_inviato.pk,
          {'voce': 'Artefatti che impediscono la lettura'})
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.INVIATA


def test_voci_non_refertabile_per_tipo():
    from consulti.motivi import voci_non_refertabile
    from core.tipi import TipoEsame
    assert any('Proiezioni' in v for v in voci_non_refertabile(TipoEsame.ECO))
    assert any('Derivazioni' in v for v in voci_non_refertabile(TipoEsame.ECG))
    assert all(voci_non_refertabile(t)[-1] == 'Altro' for t in TipoEsame.values)


# ── Permessi ─────────────────────────────────────────────────────────────────

def test_solo_il_refertatore_assegnato_decide(client, caso_inviato, mondo):
    for utente in (mondo.ref2.user, mondo.richiedente.user, mondo.staff, mondo.estraneo):
        for nome in ('consulti:prendi_in_carico', 'consulti:declina'):
            assert _post(client, utente, nome, caso_inviato.pk, {'motivo': 'x' * 10}).status_code == 404
        client.force_login(utente)
        risp = client.get(reverse('referti:refertazione', args=[caso_inviato.pk]))
        assert risp.status_code in (404, 302)  # lo staff viene rimandato alla pagina del caso
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.INVIATA


def test_estraneo_e_refertatore_sbagliato_404_sul_caso(client, caso_inviato, mondo):
    for utente in (mondo.estraneo, mondo.ref2.user):
        client.force_login(utente)
        assert client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])).status_code == 404
        allegato = caso_inviato.allegati.get()
        assert client.get(reverse('scarica_allegato', args=[allegato.pk])).status_code == 404


def test_staff_vede_in_lettura_e_lascia_audit(client, caso_inviato, mondo):
    client.force_login(mondo.staff)
    assert client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])).status_code == 200
    allegato = caso_inviato.allegati.get()
    assert client.get(reverse('scarica_allegato', args=[allegato.pk])).status_code == 200
    accessi = caso_inviato.audit.filter(azione='ACCESSO_STAFF', utente=mondo.staff)
    assert accessi.count() == 2
    # ...ma non agisce.
    assert client.post(reverse('consulti:annulla', args=[caso_inviato.pk])).status_code == 404
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.INVIATA
    # Chi ha chiesto non vede gli accessi dello staff nel racconto; lo staff si'.
    client.force_login(mondo.richiedente.user)
    assert 'come staff' not in client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])).content.decode()
    client.force_login(mondo.staff)
    assert 'come staff' in client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])).content.decode()


def test_richiedente_annulla_solo_prima_della_presa_in_carico(client, caso_inviato, mondo):
    client.force_login(mondo.richiedente.user)
    caso_inviato.prendi_in_carico(mondo.ref)
    client.post(reverse('consulti:annulla', args=[caso_inviato.pk]))
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.PRESA_IN_CARICO
    caso_inviato.rilascia_presa_in_carico()
    client.post(reverse('consulti:annulla', args=[caso_inviato.pk]))
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.ANNULLATA


def test_il_refertatore_non_vede_le_bozze(client, mondo):
    """Bug corretto: una bozza con il refertatore gia' scelto era visibile a
    lui (pagina e allegati) prima dell'invio."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from consulti.models import Allegato, CategoriaAllegato
    from core.tipi import TipoEsame
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=mondo.richiedente, clinica=mondo.clinica,
                                 refertatore=mondo.ref)
    a = Allegato.da_upload(r, SimpleUploadedFile('e.pdf', b'%PDF'), CategoriaAllegato.ECG_PDF)
    client.force_login(mondo.ref.user)
    assert client.get(reverse('consulti:dettaglio', args=[r.pk])).status_code == 404
    assert client.get(reverse('scarica_allegato', args=[a.pk])).status_code == 404
    assert client.get(reverse('referti:refertazione', args=[r.pk])).status_code == 404


def test_il_refertatore_dal_caso_va_alla_refertazione(client, caso_inviato, mondo):
    client.force_login(mondo.ref.user)
    risp = client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk]))
    assert risp.status_code == 302 and risp.url == reverse('referti:refertazione', args=[caso_inviato.pk])


# ── Casi ricevuti e navbar ───────────────────────────────────────────────────

def test_casi_ricevuti_urgenti_in_cima_e_contatore(client, caso_inviato, mondo):
    from consulti.models import Paziente
    from core.tipi import TipoEsame
    urgente = Richiesta.objects.create(tipo_esame=TipoEsame.ECG, richiedente=mondo.richiedente,
                                       clinica=mondo.clinica, refertatore=mondo.ref, urgenza=True,
                                       stato=StatoRichiesta.INVIATA, inviata_il=timezone.now())
    Paziente.objects.create(richiesta=urgente, nome='Urgentino')
    client.force_login(mondo.ref.user)
    pagina = client.get(reverse('consulti:casi_ricevuti')).content.decode()
    assert pagina.index(urgente.codice) < pagina.index(caso_inviato.codice)
    assert 'Casi ricevuti (2)' in pagina           # contatore della navbar: 2 da decidere
    assert '24 h' in pagina                         # tempo di risposta dichiarato
    caso_inviato.prendi_in_carico(mondo.ref)
    assert 'Casi ricevuti (1)' in client.get(reverse('consulti:casi_ricevuti')).content.decode()


def test_solo_refertatore_va_ai_casi_ricevuti(client, mondo):
    client.force_login(mondo.ref.user)
    risp = client.get(reverse('consulti:mie_richieste'))
    assert risp.status_code == 302 and risp.url == reverse('consulti:casi_ricevuti')


def test_ore_risposta(caso_inviato, mondo):
    assert regole.ore_risposta(caso_inviato) == 24          # dalla competenza
    caso_inviato.urgenza = True
    assert regole.ore_risposta(caso_inviato) == 4           # urgente: 4 ore anche se l'esperto ne dichiara 24
    caso_inviato.urgenza = False
    caso_inviato.refertatore = mondo.ref2
    assert regole.ore_risposta(caso_inviato) == 48          # non dichiarato
    caso_inviato.urgenza = True
    assert regole.ore_risposta(caso_inviato) == 4


# ── Racconto dell'audit ──────────────────────────────────────────────────────

def test_racconto_leggibile(caso_in_carico, mondo):
    caso_in_carico.registra('ACCESSO_STAFF', mondo.staff, pagina='caso')
    eventi = EventoAudit.objects.filter(richiesta=caso_in_carico)
    righe = racconta(eventi)
    frasi = [r['frase'] for r in righe]
    assert 'ha inviato il caso a Dott. Anna Test' in frasi
    assert 'ha preso in carico il caso' in frasi
    assert not any('staff' in f for f in frasi)
    assert any('staff' in r['frase'] for r in racconta(eventi, per_staff=True))
