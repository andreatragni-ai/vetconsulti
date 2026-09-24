"""Esame incompleto e accettazione con riserva (decisione del 24/09/2026).

Le proiezioni eco mancanti non bloccano piu' l'invio: il richiedente spunta
una presa d'atto, e l'esperto — invece di dover scegliere fra prendere in
carico alla cieca e declinare — puo' accettare **con riserva** chiedendo le
integrazioni. Finche' la richiesta di integrazione e' aperta, e solo allora,
il caso gia' inviato torna ad accettare file.

Fixture in conftest.py: mondo, caso_inviato, caso_in_carico.
"""

import html

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from consulti.models import Allegato, Integrazione, StatoRichiesta, TransizioneNonValida


def _t(risposta):
    return html.unescape(risposta.content.decode())


def _pdf(nome='altro.pdf'):
    return SimpleUploadedFile(nome, b'%PDF-1.4 altro', 'application/pdf')


# ── Il modello ──────────────────────────────────────────────────────────────

def test_presa_in_carico_con_riserva_apre_una_integrazione(caso_inviato, mondo):
    integrazione = caso_inviato.prendi_in_carico(
        mondo.ref, mondo.ref.user, riserva=True, motivo_riserva='Manca l\'asse corto: rifallo.')
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.PRESA_IN_CARICO and caso_inviato.con_riserva
    assert integrazione.aperta and caso_inviato.integrazione_aperta() == integrazione
    # Il caso e' preso in carico a tutti gli effetti: i tempi corrono.
    assert caso_inviato.presa_in_carico_il is not None
    evento = caso_inviato.audit.filter(azione='PRESA_IN_CARICO').last()
    assert evento.dettaglio['riserva'] is True


def test_riserva_senza_motivo_e_rifiutata(caso_inviato, mondo):
    with pytest.raises(TransizioneNonValida, match='cosa manca'):
        caso_inviato.prendi_in_carico(mondo.ref, mondo.ref.user, riserva=True, motivo_riserva='   ')
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.INVIATA and not Integrazione.objects.exists()


def test_presa_in_carico_normale_non_apre_niente(caso_in_carico):
    assert not caso_in_carico.con_riserva
    assert caso_in_carico.integrazione_aperta() is None
    assert not caso_in_carico.apre_al_caricamento


def test_integrazione_si_chiede_solo_su_un_caso_preso_in_carico(caso_inviato, mondo):
    with pytest.raises(TransizioneNonValida):
        caso_inviato.chiedi_integrazione('Serve altro', mondo.ref.user)


def test_il_caricamento_si_riapre_solo_con_una_integrazione_aperta(caso_in_carico, mondo):
    assert not caso_in_carico.apre_al_caricamento
    caso_in_carico.chiedi_integrazione('Serve il transmitralico.', mondo.ref.user)
    assert caso_in_carico.apre_al_caricamento
    assert caso_in_carico.evadi_integrazioni(mondo.richiedente.user) == 1
    assert not caso_in_carico.apre_al_caricamento
    assert caso_in_carico.evadi_integrazioni(mondo.richiedente.user) == 0   # niente da chiudere


# ── Il giro completo, dalle viste ───────────────────────────────────────────

def test_giro_completo_riserva_integrazione_consegna(client, caso_inviato, mondo):
    """L'esperto accetta con riserva, il collega carica e avvisa, l'esperto
    riceve l'email e il caso torna chiuso al caricamento."""
    client.force_login(mondo.ref.user)
    mail.outbox.clear()
    risposta = client.post(reverse('consulti:prendi_in_carico', args=[caso_inviato.pk]),
                           {'riserva': 'si', 'testo': 'Manca l\'asse corto a livello dei papillari.'})
    assert risposta.status_code == 302
    caso_inviato.refresh_from_db()
    assert caso_inviato.con_riserva and caso_inviato.stato == StatoRichiesta.PRESA_IN_CARICO

    # 1. L'email a chi ha chiesto dice cosa serve e manda al caso.
    email = mail.outbox[-1]
    assert email.to == [mondo.richiedente.user.email] and 'integrazioni' in email.subject.lower()
    assert 'asse corto' in email.body

    # 2. Il richiedente vede l'avviso sul caso e puo' caricare.
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])))
    assert 'asse corto' in pagina and 'Ho caricato le integrazioni' in pagina
    prima = caso_inviato.allegati.count()
    risposta = client.post(reverse('consulti:carica_allegato', args=[caso_inviato.pk]),
                           {'slot': 'ecg', 'file': _pdf()})
    assert risposta.status_code in (200, 302)
    assert caso_inviato.allegati.count() == prima + 1

    # 3. «Ho caricato»: l'esperto viene avvisato e il caso si richiude.
    mail.outbox.clear()
    client.post(reverse('consulti:integrazioni_fatte', args=[caso_inviato.pk]))
    caso_inviato.refresh_from_db()
    assert caso_inviato.integrazione_aperta() is None and not caso_inviato.apre_al_caricamento
    assert mail.outbox[-1].to == [mondo.ref.user.email]
    assert 'ntegrazioni' in mail.outbox[-1].subject

    # 4. Chiuse le integrazioni, gli allegati tornano intoccabili.
    risposta = client.post(reverse('consulti:carica_allegato', args=[caso_inviato.pk]),
                           {'slot': 'ecg', 'file': _pdf('ancora.pdf')})
    assert caso_inviato.allegati.count() == prima + 1


def test_riserva_dalla_pagina_senza_testo_non_prende_in_carico(client, caso_inviato, mondo):
    client.force_login(mondo.ref.user)
    client.post(reverse('consulti:prendi_in_carico', args=[caso_inviato.pk]), {'riserva': 'si', 'testo': ''})
    caso_inviato.refresh_from_db()
    assert caso_inviato.stato == StatoRichiesta.INVIATA


def test_altre_integrazioni_durante_la_presa_in_carico(client, caso_in_carico, mondo):
    client.force_login(mondo.ref.user)
    mail.outbox.clear()
    client.post(reverse('consulti:chiedi_integrazione', args=[caso_in_carico.pk]),
                {'testo': 'Mandami anche il Doppler continuo.'})
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.integrazione_aperta() is not None
    assert not caso_in_carico.con_riserva          # non era una riserva: era un caso gia' accettato
    assert 'Doppler continuo' in mail.outbox[-1].body


def test_solo_il_refertatore_assegnato_chiede_integrazioni(client, caso_in_carico, mondo):
    client.force_login(mondo.ref2.user)
    risposta = client.post(reverse('consulti:chiedi_integrazione', args=[caso_in_carico.pk]), {'testo': 'Dammi altro'})
    assert risposta.status_code == 404
    assert caso_in_carico.integrazione_aperta() is None


def test_il_richiedente_di_un_altro_caso_non_consegna(client, caso_in_carico, mondo):
    caso_in_carico.chiedi_integrazione('Serve altro.', mondo.ref.user)
    client.force_login(mondo.ref.user)      # l'esperto non e' il richiedente
    assert client.post(reverse('consulti:integrazioni_fatte', args=[caso_in_carico.pk])).status_code == 404
    assert caso_in_carico.integrazione_aperta() is not None


def test_l_esperto_vede_cosa_manca_e_che_il_collega_lo_sapeva(client, mondo, crea_bozza):
    """Sulla pagina di refertazione, un'eco incompleta si presenta con
    l'elenco di cio' che non e' arrivato."""
    from accounts.models import CompetenzaRefertatore
    from eco.models import ProiezioneCatalogo
    from consulti.models import CategoriaAllegato
    from core.tipi import TipoEsame
    ProiezioneCatalogo.objects.create(codice='PDC', nome='Asse corto', obbligatoria=True, ordine=1)
    CompetenzaRefertatore.objects.create(refertatore=mondo.ref, tipo_esame=TipoEsame.ECO, referente=True)
    client.force_login(mondo.richiedente.user)
    bozza = crea_bozza(client, TipoEsame.ECO, mondo.ref)
    Allegato.da_upload(bozza, SimpleUploadedFile('referto.pdf', b'%PDF-1.4', 'application/pdf'),
                       CategoriaAllegato.ECO_REFERTO_PDF, mondo.richiedente.user)
    client.post(reverse('consulti:invia', args=[bozza.pk]), {'presa_atto': 'si'})
    bozza.refresh_from_db()
    assert bozza.stato == StatoRichiesta.INVIATA and bozza.inviata_incompleta

    client.force_login(mondo.ref.user)
    pagina = _t(client.get(reverse('referti:refertazione', args=[bozza.pk])))
    assert 'Esame incompleto: 1 proiezione manca' in pagina and 'Asse corto' in pagina
    assert 'Il collega lo sapeva' in pagina
    assert 'Prendi in carico con riserva' in pagina
