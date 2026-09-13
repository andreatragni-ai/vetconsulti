import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from accounts import fiscale
from accounts.models import (Clinica, CompetenzaRefertatore, DatiFatturazione, Refertatore,
                             Richiedente, TipoRichiedente)
from core.tipi import TipoEsame


# ── fiscale.py ──────────────────────────────────────────────────────────────

def test_partita_iva_valida():
    assert fiscale.valida_partita_iva('01234567897') == '01234567897'
    assert fiscale.valida_partita_iva(' 00743110157 ') == '00743110157'


@pytest.mark.parametrize('valore', ['0123456789', '01234567891', 'ABCDEFGHIJK', ''])
def test_partita_iva_non_valida(valore):
    with pytest.raises(ValueError):
        fiscale.valida_partita_iva(valore)


def test_codice_fiscale_persona_e_societa():
    assert fiscale.valida_codice_fiscale('rssmra85m01h501z') == 'RSSMRA85M01H501Z'
    assert fiscale.valida_codice_fiscale('01234567890') == '01234567890'


@pytest.mark.parametrize('valore', ['RSSMRA85M01H501', '1234567890A', 'RSSMRA85M01H501ZZ', '3391234567'])
def test_codice_fiscale_non_valido(valore):
    with pytest.raises(ValueError):
        fiscale.valida_codice_fiscale(valore)


def test_codice_sdi():
    assert fiscale.valida_codice_sdi('abc1234') == 'ABC1234'
    for cattivo in ('ABC123', 'ABC12345', 'ABC-123'):
        with pytest.raises(ValueError):
            fiscale.valida_codice_sdi(cattivo)


def test_recapito_fattura():
    assert not fiscale.recapito_fattura_valido('0000000', '')
    assert fiscale.recapito_fattura_valido('0000000', 'x@pec.it')
    assert fiscale.recapito_fattura_valido('ABC1234', '')


# ── DatiFatturazione.clean ──────────────────────────────────────────────────

def _dati(**extra):
    base = dict(intestatario='Clinica Rossi srl', partita_iva='00743110157',
                indirizzo_sede='Via Roma 1', cap='20100', comune='Milano', provincia='MI',
                codice_sdi='0000000', pec_fatturazione='rossi@pec.it')
    base.update(extra)
    return DatiFatturazione(**base)


@pytest.mark.django_db
def test_dati_fatturazione_validi():
    _dati().clean()


@pytest.mark.django_db
def test_dati_fatturazione_senza_recapito():
    with pytest.raises(ValidationError) as e:
        _dati(pec_fatturazione='').clean()
    assert 'pec_fatturazione' in e.value.error_dict


@pytest.mark.django_db
def test_dati_fatturazione_piva_sbagliata():
    with pytest.raises(ValidationError) as e:
        _dati(partita_iva='01234567891').clean()
    assert 'partita_iva' in e.value.error_dict


# ── referenti_per e puo_richiedere ──────────────────────────────────────────

def _refertatore(username, attivo=True, tipi=()):
    u = User.objects.create_user(username, f'{username}@x.it', 'pw')
    r = Refertatore.objects.create(user=u, attivo=attivo)
    for tipo, referente in tipi:
        CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=tipo, referente=referente)
    return r


@pytest.mark.django_db
def test_referenti_per_filtra_attivi_e_referenti():
    a = _refertatore('a', tipi=[(TipoEsame.ECG, True)])
    _refertatore('b', tipi=[(TipoEsame.ECG, False)])
    _refertatore('c', attivo=False, tipi=[(TipoEsame.ECG, True)])
    _refertatore('d', tipi=[(TipoEsame.ECO, True)])
    assert list(Refertatore.referenti_per(TipoEsame.ECG)) == [a]
    assert a.referta(TipoEsame.ECG)
    assert not a.referta(TipoEsame.ECO)


@pytest.mark.django_db
def test_puo_richiedere_richiede_dati_fatturazione_validi():
    u = User.objects.create_user('vet', 'vet@x.it', 'pw')
    r = Richiedente.objects.create(user=u)
    assert not r.puo_richiedere
    c = Clinica.objects.create(denominazione='Clinica Rossi')
    r.clinica = c
    r.save()
    assert not r.puo_richiedere
    d = _dati(clinica=c, predefinita=True)
    d.save()
    assert r.puo_richiedere
    d.pec_fatturazione = ''
    d.save()
    assert not r.puo_richiedere


# ── Libero professionista ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_libero_professionista_con_dati_propri_puo_richiedere():
    u = User.objects.create_user('lp', 'lp@x.it', 'pw', first_name='Luca', last_name='Verdi')
    r = Richiedente.objects.create(user=u, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
    r.full_clean()  # nessuna clinica richiesta
    assert not r.puo_richiedere
    assert r.soggetto_fatturazione is r
    d = _dati(richiedente=r, predefinita=True, intestatario='Luca Verdi')
    d.save()
    assert r.puo_richiedere
    assert r.dati_fatturazione_predefiniti == d
    assert r.denominazione == 'Luca Verdi'
    assert not r.approvazione_ok()
    r.approvato = True
    assert r.approvazione_ok()


@pytest.mark.django_db
def test_tipo_clinica_senza_clinica_non_valida():
    u = User.objects.create_user('c', 'c@x.it', 'pw')
    r = Richiedente(user=u, tipo=TipoRichiedente.CLINICA)
    with pytest.raises(ValidationError) as e:
        r.full_clean()
    assert 'clinica' in e.value.error_dict
    assert not r.approvazione_ok()


@pytest.mark.django_db
def test_approvazione_ok_segue_la_clinica():
    c = Clinica.objects.create(denominazione='C', approvata=False)
    u = User.objects.create_user('c', 'c@x.it', 'pw')
    r = Richiedente.objects.create(user=u, clinica=c)
    assert not r.approvazione_ok()
    c.approvata = True
    c.save()
    r.refresh_from_db()
    assert r.approvazione_ok()


@pytest.mark.django_db
def test_dati_fatturazione_con_entrambi_i_soggetti():
    from django.db import IntegrityError, transaction
    c = Clinica.objects.create(denominazione='C')
    u = User.objects.create_user('lp', 'lp@x.it', 'pw')
    r = Richiedente.objects.create(user=u, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
    d = _dati(clinica=c, richiedente=r)
    with pytest.raises(ValidationError) as e:
        d.clean()
    assert 'richiedente' in e.value.error_dict
    # Anche scavalcando clean(): il database lo rifiuta.
    with pytest.raises(IntegrityError), transaction.atomic():
        d.save()


@pytest.mark.django_db
def test_una_sola_predefinita_per_richiedente():
    from django.db import IntegrityError, transaction
    u = User.objects.create_user('lp', 'lp@x.it', 'pw')
    r = Richiedente.objects.create(user=u, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
    _dati(richiedente=r, predefinita=True).save()
    with pytest.raises(IntegrityError), transaction.atomic():
        _dati(richiedente=r, predefinita=True).save()


@pytest.mark.django_db
def test_refertatore_diventa_richiedente_riusa_i_dati(client):
    from django.urls import reverse
    u = User.objects.create_user('ref', 'ref@x.it', 'pw', first_name='Anna', last_name='Bianchi')
    d = _dati(intestatario='Anna Bianchi')
    d.save()
    ref = Refertatore.objects.create(user=u, dati_fatturazione=d)
    client.force_login(u)
    risp = client.post(reverse('accounts:refertatore_diventa_richiedente'))
    assert risp.status_code == 302
    r = Richiedente.objects.get(user=u)
    assert r.tipo == TipoRichiedente.LIBERO_PROFESSIONISTA and r.approvato
    d.refresh_from_db()
    assert d.richiedente == r and d.predefinita
    assert DatiFatturazione.objects.count() == 1  # collegata, non copiata
    assert r.puo_richiedere
    assert ref.dati_fatturazione_id == r.dati_fatturazione_predefiniti.id


def _post_registrazione(**extra):
    base = {
        'first_name': 'Luca', 'last_name': 'Verdi', 'email': 'lp@x.it', 'username': 'lp',
        'password1': 'Passw0rd-lunga!', 'password2': 'Passw0rd-lunga!', 'ruolo': 'VETERINARIO',
        'numero_iscrizione': '123', 'ordine_provinciale': 'Milano',
        'partita_iva': '00743110157', 'indirizzo_sede': 'Via Verdi 2', 'cap': '20100', 'comune': 'Milano',
        'provincia': 'mi', 'codice_sdi': '0000000', 'pec_fatturazione': 'lp@pec.it', 'regime_iva': 'FORFETTARIO',
        'accetto_privacy': 'on', 'accetto_termini': 'on',
    }
    base.update(extra)
    return base


@pytest.mark.django_db
def test_registrazione_a_due_passi(client):
    from django.urls import reverse
    assert client.get(reverse('accounts:registrati')).status_code == 200
    assert client.get(reverse('accounts:registrati_tipo', args=['clinica'])).status_code == 200
    risp = client.get(reverse('accounts:registrati_tipo', args=['libero-professionista']))
    html = risp.content.decode()
    assert risp.status_code == 200 and 'name="nuova_clinica"' not in html
    assert 'href="/privacy/" target="_blank"' in html and 'href="/termini/" target="_blank"' in html
    assert client.get(reverse('accounts:registrati_tipo', args=['altro'])).status_code == 404


@pytest.mark.django_db
def test_registrazione_libero_professionista_crea_dati_fatturazione(client, settings):
    from django.urls import reverse
    settings.VERSIONE_PRIVACY = '2030-01-01'
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']), _post_registrazione())
    assert risp.status_code == 200 and b'conferma' in risp.content
    r = Richiedente.objects.get(user__username='lp')
    assert r.tipo == TipoRichiedente.LIBERO_PROFESSIONISTA and r.clinica is None and not r.approvato
    assert not r.user.is_active
    d = r.dati_fatturazione_predefiniti
    assert d is not None and d.richiedente == r and d.clinica is None
    assert d.intestatario == 'Luca Verdi'  # precompilato da nome e cognome
    assert d.partita_iva == '00743110157' and d.provincia == 'MI' and d.regime_iva == 'FORFETTARIO'
    assert r.puo_richiedere
    assert r.user.consensi.get(tipo='PRIVACY').versione == '2030-01-01'


@pytest.mark.django_db
def test_registrazione_clinica_nuova_crea_dati_sulla_clinica(client):
    from django.urls import reverse
    dati = _post_registrazione(username='vet', email='vet@x.it', ruolo='TECNICO', numero_iscrizione='',
                               ordine_provinciale='', nuova_clinica='Clinica Blu', nuova_clinica_comune='Roma',
                               nuova_clinica_provincia='rm', codice_sdi='ABC1234', pec_fatturazione='')
    risp = client.post(reverse('accounts:registrati_tipo', args=['clinica']), dati)
    assert risp.status_code == 200 and b'conferma' in risp.content
    r = Richiedente.objects.get(user__username='vet')
    c = r.clinica
    assert c.denominazione == 'Clinica Blu' and c.provincia == 'RM' and not c.approvata
    d = c.dati_fatturazione_predefiniti
    assert d is not None and d.intestatario == 'Clinica Blu' and d.richiedente is None and d.codice_sdi == 'ABC1234'
    assert r.puo_richiedere and not r.approvazione_ok()


@pytest.mark.django_db
def test_registrazione_clinica_esistente_con_dati_non_richiede_fatturazione(client):
    from django.urls import reverse
    c = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    _dati(clinica=c, predefinita=True).save()
    dati = _post_registrazione(username='vet2', email='vet2@x.it', clinica=c.pk, partita_iva='', indirizzo_sede='',
                               cap='', comune='', provincia='', pec_fatturazione='')
    risp = client.post(reverse('accounts:registrati_tipo', args=['clinica']), dati)
    assert risp.status_code == 200 and b'conferma' in risp.content
    assert DatiFatturazione.objects.count() == 1
    assert Richiedente.objects.get(user__username='vet2').puo_richiedere


@pytest.mark.django_db
def test_registrazione_sdi_nullo_senza_pec_e_rifiutata(client):
    from django.urls import reverse
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']),
                       _post_registrazione(codice_sdi='0000000', pec_fatturazione=''))
    assert risp.status_code == 200
    assert 'pec_fatturazione' in risp.context['form'].errors
    assert 'serve una PEC' in str(risp.context['form'].errors['pec_fatturazione'])
    assert not User.objects.filter(username='lp').exists()


@pytest.mark.django_db
def test_registrazione_piva_errata_e_rifiutata(client):
    from django.urls import reverse
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']),
                       _post_registrazione(partita_iva='01234567890'))
    assert risp.status_code == 200
    assert 'cifra di controllo' in str(risp.context['form'].errors['partita_iva'])
    assert not User.objects.filter(username='lp').exists()


@pytest.mark.django_db
def test_pagine_legali_pubbliche(client):
    from django.urls import reverse
    for nome in ('core:privacy', 'core:termini'):
        risp = client.get(reverse(nome))
        assert risp.status_code == 200
        assert 'Bozza da far validare a un legale' in risp.content.decode()


@pytest.mark.django_db
def test_privacy_dice_dello_smistamento_automatico(client):
    """Le miniature dei file dell'eco vanno a un fornitore di intelligenza
    artificiale: l'informativa lo dice, e la frase e' segnata da validare."""
    from django.urls import reverse
    testo = client.get(reverse('core:privacy')).content.decode()
    assert "Smistamento automatico dei file dell'ecocardiografia" in testo
    assert 'intelligenza artificiale' in testo and 'ritaglia' in testo
    assert 'da validare dal legale' in testo


@pytest.mark.django_db
def test_libero_professionista_senza_albo_si_registra(client):
    """Chi carica gli esami puo' essere un tecnico, che all'Ordine non e'
    iscritto: numero e Ordine restano facoltativi (decisione del 12/09)."""
    from django.urls import reverse
    from accounts.models import RuoloRichiedente
    dati = _post_registrazione(numero_iscrizione='', ordine_provinciale='',
                               ruolo=RuoloRichiedente.TECNICO)
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']), dati)
    assert risp.status_code == 200 and b'conferma' in risp.content
    r = Richiedente.objects.get(user__username='lp')
    assert r.numero_iscrizione == '' and r.ordine_provinciale == ''
    assert r.ruolo == RuoloRichiedente.TECNICO


# ── Iscrizione con la fatturazione rimandata (decisione del 12/09/2026) ─────

@pytest.mark.django_db
def test_registrazione_senza_fatturazione_e_permessa(client):
    """Blocco fiscale vuoto = «dopo»: l'account nasce, l'invio resta chiuso."""
    from django.urls import reverse
    dati = _post_registrazione(partita_iva='', indirizzo_sede='', cap='', comune='',
                               provincia='', pec_fatturazione='', codice_sdi='0000000')
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']), dati)
    assert risp.status_code == 200 and b'conferma' in risp.content
    r = Richiedente.objects.get(user__username='lp')
    assert r.dati_fatturazione_predefiniti is None and not r.puo_richiedere
    assert DatiFatturazione.objects.count() == 0


@pytest.mark.django_db
def test_intestatario_precompilato_non_obbliga_la_fatturazione(client):
    """L'intestatario lo scrive il JS da nome e cognome: da solo non deve
    far scattare la validazione del resto del blocco."""
    from django.urls import reverse
    dati = _post_registrazione(intestatario='Luca Verdi', partita_iva='', indirizzo_sede='',
                               cap='', comune='', provincia='', pec_fatturazione='')
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']), dati)
    assert risp.status_code == 200 and b'conferma' in risp.content
    assert not Richiedente.objects.get(user__username='lp').puo_richiedere


@pytest.mark.django_db
def test_fatturazione_a_meta_resta_un_errore(client):
    """Chi comincia a compilarla la deve finire: meglio l'errore adesso che
    una fattura senza indirizzo fra un mese."""
    from django.urls import reverse
    dati = _post_registrazione(indirizzo_sede='', cap='', comune='', provincia='')
    risp = client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']), dati)
    assert risp.status_code == 200
    assert 'indirizzo_sede' in risp.context['form'].errors
    assert not User.objects.filter(username='lp').exists()


# ── Invito di un collega nella stessa clinica ──────────────────────────────

@pytest.mark.django_db
def test_invito_porta_nella_clinica_di_chi_invita(client):
    from django.urls import reverse
    from accounts import inviti
    c = Clinica.objects.create(denominazione='Clinica Rossi', comune='Milano', approvata=True)
    _dati(clinica=c, predefinita=True).save()
    capo = User.objects.create_user('capo', 'capo@x.it', 'pw', first_name='Gina', last_name='Bianchi')
    Richiedente.objects.create(user=capo, tipo=TipoRichiedente.CLINICA, clinica=c)

    url = reverse('accounts:registrati_invitato', args=[inviti.crea(c, capo)])
    html = client.get(url).content.decode()
    # La clinica non si sceglie e non si propone: la decide il link.
    assert 'name="clinica"' not in html and 'name="nuova_clinica"' not in html
    assert 'Clinica Rossi' in html and 'Gina Bianchi' in html
    # Ha gia' i dati di fatturazione: il blocco fiscale non compare nemmeno.
    assert 'name="partita_iva"' not in html

    dati = _post_registrazione(username='collega', email='collega@x.it', partita_iva='',
                               indirizzo_sede='', cap='', comune='', provincia='', pec_fatturazione='')
    risp = client.post(url, dati)
    assert risp.status_code == 200 and b'conferma' in risp.content
    r = Richiedente.objects.get(user__username='collega')
    assert r.clinica == c and r.tipo == TipoRichiedente.CLINICA
    assert DatiFatturazione.objects.count() == 1      # eredita quelli della clinica
    assert r.puo_richiedere and r.approvazione_ok()   # clinica approvata: invia subito


@pytest.mark.django_db
def test_invito_manomesso_o_scaduto(client, monkeypatch):
    from django.urls import reverse
    from accounts import inviti
    c = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    capo = User.objects.create_user('capo', 'capo@x.it', 'pw')

    assert client.get(reverse('accounts:registrati_invitato', args=['non-un-token'])).status_code == 400

    token = inviti.crea(c, capo)
    monkeypatch.setattr(inviti, '_MAX_AGE', -1)       # come se fosse scaduto
    risp = client.get(reverse('accounts:registrati_invitato', args=[token]))
    assert risp.status_code == 400 and 'scaduto' in risp.content.decode()


@pytest.mark.django_db
def test_invito_di_una_clinica_cancellata(client):
    from accounts import inviti
    c = Clinica.objects.create(denominazione='Clinica Sparita')
    capo = User.objects.create_user('capo', 'capo@x.it', 'pw')
    token = inviti.crea(c, capo)
    c.delete()
    with pytest.raises(inviti.InvitoNonValido):
        inviti.leggi(token)


@pytest.mark.django_db
def test_link_invito_solo_per_chi_ha_una_clinica(client):
    """Un libero professionista non ha nessuno da far entrare."""
    from django.urls import reverse
    u = User.objects.create_user('lp', 'lp@x.it', 'pw')
    Richiedente.objects.create(user=u, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
    client.force_login(u)
    assert client.get(reverse('accounts:profilo_richiedente')).context['link_invito'] == ''

    c = Clinica.objects.create(denominazione='Clinica Rossi', approvata=True)
    u2 = User.objects.create_user('vet', 'vet@x.it', 'pw')
    Richiedente.objects.create(user=u2, tipo=TipoRichiedente.CLINICA, clinica=c)
    client.force_login(u2)
    risp = client.get(reverse('accounts:profilo_richiedente'))
    link = risp.context['link_invito']
    assert '/registrati/invito/' in link
    assert 'Invita un collega' in risp.content.decode()


# ── Le email dell'iscrizione, attaccate al percorso vero ───────────────────

@pytest.mark.django_db
def test_iscriversi_avvisa_il_gestore(client, settings):
    from django.core import mail
    from django.urls import reverse
    settings.EMAIL_GESTORE = 'andre@vetway.it'
    client.post(reverse('accounts:registrati_tipo', args=['libero-professionista']),
                _post_registrazione())
    destinatari = [d for e in mail.outbox for d in e.to]
    assert 'lp@x.it' in destinatari          # conferma email a chi si iscrive
    assert 'andre@vetway.it' in destinatari  # avviso a chi approva


@pytest.mark.django_db
def test_approvare_la_clinica_avvisa_i_colleghi(client):
    """Un ok, tanti abilitati: l'email va a ognuno. Chi non ha confermato
    l'email resta fuori — non potrebbe nemmeno accedere."""
    from django.core import mail
    from django.urls import reverse
    c = Clinica.objects.create(denominazione='Clinica Blu')
    dentro = User.objects.create_user('dentro', 'dentro@x.it', 'pw')
    fuori = User.objects.create_user('fuori', 'fuori@x.it', 'pw', is_active=False)
    for u in (dentro, fuori):
        Richiedente.objects.create(user=u, tipo=TipoRichiedente.CLINICA, clinica=c)
    staff = User.objects.create_user('staff', 'staff@x.it', 'pw', is_staff=True)

    client.force_login(staff)
    mail.outbox.clear()
    risp = client.post(reverse('gestione:clinica_approva', args=[c.pk]))
    assert risp.status_code == 302
    c.refresh_from_db()
    assert c.approvata
    assert [d for e in mail.outbox for d in e.to] == ['dentro@x.it']


@pytest.mark.django_db
def test_approvare_il_libero_professionista_lo_avvisa(client):
    from django.core import mail
    from django.urls import reverse
    u = User.objects.create_user('lp', 'lp@x.it', 'pw')
    r = Richiedente.objects.create(user=u, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
    client.force_login(User.objects.create_user('staff', 'staff@x.it', 'pw', is_staff=True))
    mail.outbox.clear()
    assert client.post(reverse('gestione:richiedente_approva', args=[r.pk])).status_code == 302
    r.refresh_from_db()
    assert r.approvato
    assert [d for e in mail.outbox for d in e.to] == ['lp@x.it']


# ── Pagine di errore ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_pagina_404_del_portale(client):
    risp = client.get('/questa-pagina-non-esiste/')
    assert risp.status_code == 404
    assert 'Questa pagina non c\'e\'' in risp.content.decode()


def test_pagina_500_si_rende_senza_request():
    """django.views.defaults.server_error la rende SENZA request e senza
    context processor: se un giorno passasse a estendere base.html, il
    crash si vedrebbe qui e non in produzione."""
    from django.template.loader import get_template
    for nome in ('500.html', '400.html'):
        html = get_template(nome).render()
        assert 'VetWay Consulti' in html
    assert 'Qualcosa si e\' rotto' in get_template('500.html').render()


@pytest.mark.django_db
def test_invito_in_clinica_senza_dati_chiede_la_fatturazione(client):
    """Se la clinica non ha ancora i dati fiscali, il collega invitato li
    vede e quelli che compila finiscono sulla clinica, non su di lui."""
    from django.urls import reverse
    from accounts import inviti
    c = Clinica.objects.create(denominazione='Clinica Blu', approvata=True)
    capo = User.objects.create_user('capo', 'capo@x.it', 'pw')
    Richiedente.objects.create(user=capo, tipo=TipoRichiedente.CLINICA, clinica=c)
    url = reverse('accounts:registrati_invitato', args=[inviti.crea(c, capo)])
    assert 'name="partita_iva"' in client.get(url).content.decode()

    risp = client.post(url, _post_registrazione(username='collega', email='collega@x.it'))
    assert risp.status_code == 200 and b'conferma' in risp.content
    d = Clinica.objects.get(pk=c.pk).dati_fatturazione_predefiniti
    assert d is not None and d.richiedente is None and d.intestatario == 'Clinica Blu'
    assert Richiedente.objects.get(user__username='collega').puo_richiedere
