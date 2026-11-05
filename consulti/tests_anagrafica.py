"""L'archivio pazienti e lo storico del paziente (decisioni del 05/11/2026).

Cosa dicono questi test, in breve:

- l'archivio e' della **clinica**, e si riempie solo con i casi **inviati**;
- il peso non si precompila mai, l'eta' in anni solo se e' recente;
- lo stesso animale, rinviato, aggiorna la sua voce e non la duplica;
- lo storico si vede anche fra colleghi, ma apre solo cio' che si puo'
  aprire: il PDF del referto firmato, con un ACCESSO_STORICO nell'audit.

Fixture in conftest.py: mondo, caso_inviato, crea_bozza.
"""

import html
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import Clinica, DatiFatturazione, Richiedente, TipoRichiedente
from consulti import anagrafica
from consulti.forms import PazienteForm
from consulti.models import (Allegato, CategoriaAllegato, Paziente, PazienteArchivio, Richiesta,
                             StatoRichiesta)
from consulti.nomi import chiave_archivio
from core.tipi import TipoEsame


def _t(risposta):
    return html.unescape(risposta.content.decode())


def _collega(mondo, username='collega'):
    """Un altro richiedente della stessa clinica di `mondo`."""
    return Richiedente.objects.create(
        user=User.objects.create_user(username, f'{username}@x.it', 'pw', first_name='Carla', last_name='Neri'),
        clinica=mondo.clinica)


def _altra_clinica(nome='Clinica Bianchi'):
    clinica = Clinica.objects.create(denominazione=nome, approvata=True)
    DatiFatturazione.objects.create(
        clinica=clinica, intestatario=nome, partita_iva='00743110157', indirizzo_sede='Via Verdi 2',
        cap='20100', comune='Milano', provincia='MI', pec_fatturazione='b@pec.it', predefinita=True)
    return Richiedente.objects.create(
        user=User.objects.create_user('altro', 'altro@x.it', 'pw', first_name='Ugo', last_name='Bianchi'),
        clinica=clinica)


def _caso(mondo, richiedente=None, tipo=TipoEsame.ECG, invia=True, **paziente):
    """Un caso inviato (o una bozza con `invia=False`) con il suo paziente."""
    richiedente = richiedente or mondo.richiedente
    dati = {'nome': 'Luna', 'specie': 'CANE', 'sesso': 'F', **paziente}
    caso = Richiesta.objects.create(tipo_esame=tipo, richiedente=richiedente, clinica=richiedente.clinica,
                                    refertatore=mondo.ref, quesito='Aritmia?')
    Paziente.objects.create(richiesta=caso, **dati)
    Allegato.da_upload(caso, SimpleUploadedFile('ecg.pdf', b'%PDF-1.4', 'application/pdf'),
                       CategoriaAllegato.ECG_PDF, richiedente.user)
    if invia:
        caso.invia(richiedente.user)
    return caso


# ── La chiave: quando due richieste parlano dello stesso animale ────────────

def test_la_chiave_ignora_maiuscole_accenti_e_punteggiatura():
    assert chiave_archivio('luna', 'CANE', 'rossi') == chiave_archivio('  Luna ', 'CANE', 'Rossi')
    assert chiave_archivio('Nino', 'CANE', "D'Amico") == chiave_archivio('nino', 'CANE', 'd amico')
    # Specie diversa o proprietario diverso: altro animale.
    assert chiave_archivio('Luna', 'CANE', 'Rossi') != chiave_archivio('Luna', 'GATTO', 'Rossi')
    assert chiave_archivio('Luna', 'CANE', 'Rossi') != chiave_archivio('Luna', 'CANE', 'Verdi')


# ── L'archivio si riempie all'invio ────────────────────────────────────────

def test_l_invio_crea_la_voce_e_la_lega_al_paziente(mondo):
    caso = _caso(mondo, cognome_proprietario='Rossi', razza='Labrador')
    voce = PazienteArchivio.objects.get()
    assert (voce.nome, voce.razza, voce.cognome_proprietario) == ('Luna', 'Labrador', 'Rossi')
    assert voce.clinica == mondo.clinica and voce.richiedente == mondo.richiedente
    assert voce.visto_il == caso.inviata_il
    caso.paziente.refresh_from_db()
    assert caso.paziente.archivio == voce


def test_una_bozza_non_lascia_niente_in_archivio(mondo):
    _caso(mondo, invia=False)
    assert not PazienteArchivio.objects.exists()


def test_il_secondo_invio_aggiorna_la_voce_e_non_la_duplica(mondo):
    _caso(mondo, cognome_proprietario='Rossi', razza='')
    secondo = _caso(mondo, cognome_proprietario='Rossi', razza='Labrador', tipo=TipoEsame.ECG)
    voce = PazienteArchivio.objects.get()          # una sola
    assert voce.razza == 'Labrador'                # vince l'ultimo invio
    assert voce.pazienti.count() == 2
    assert secondo.paziente.archivio == voce


def test_il_peso_non_entra_in_archivio(mondo):
    caso = _caso(mondo, peso_kg=Decimal('12.50'))
    voce = PazienteArchivio.objects.get()
    assert not hasattr(voce, 'peso_kg')
    assert 'peso_kg' not in PazienteForm.iniziale_da_archivio(voce)
    assert caso.paziente.peso_kg == Decimal('12.50')   # sulla fotografia c'e'


def test_rinominare_il_paziente_crea_un_altro_animale(mondo):
    caso = _caso(mondo, cognome_proprietario='Rossi')
    voce = PazienteArchivio.objects.get()
    # Sopra una bozza precompilata il collega scrive un altro cane.
    altro = _caso(mondo, nome='Nerone', cognome_proprietario='Rossi')
    altro.paziente.archivio = voce      # come se il legame fosse rimasto appeso
    altro.paziente.save(update_fields=['archivio'])
    anagrafica.registra(altro)
    altro.paziente.refresh_from_db()
    assert PazienteArchivio.objects.count() == 2
    assert altro.paziente.archivio.nome == 'Nerone'
    assert caso.paziente.archivio == voce


# ── Lo scope: di chi e' l'archivio ────────────────────────────────────────

def test_l_archivio_e_della_clinica_non_di_chi_ha_scritto(mondo):
    _caso(mondo, cognome_proprietario='Rossi')
    collega = _collega(mondo)
    assert anagrafica.cerca(collega, 'Luna').count() == 1
    assert anagrafica.cerca(_altra_clinica(), 'Luna').count() == 0


def test_il_libero_professionista_ha_il_suo_archivio(mondo, db):
    lp = Richiedente.objects.create(
        user=User.objects.create_user('solo', 'solo@x.it', 'pw', first_name='Ada', last_name='Soli'),
        tipo=TipoRichiedente.LIBERO_PROFESSIONISTA, approvato=True)
    PazienteArchivio.objects.create(richiedente=lp, nome='Pluto', specie='CANE')
    _caso(mondo, nome='Luna')
    assert [v.nome for v in anagrafica.archivio_di(lp)] == ['Pluto']
    assert [v.nome for v in anagrafica.archivio_di(mondo.richiedente)] == ['Luna']
    # Una voce di un altro non si risolve nemmeno conoscendone l'id.
    assert anagrafica.voce(mondo.richiedente, PazienteArchivio.objects.get(nome='Pluto').pk) is None


def test_la_ricerca_vuole_due_lettere_e_guarda_anche_il_proprietario(mondo):
    _caso(mondo, cognome_proprietario='Rossi')
    assert anagrafica.cerca(mondo.richiedente, 'l').count() == 0
    assert anagrafica.cerca(mondo.richiedente, 'lu').count() == 1
    assert anagrafica.cerca(mondo.richiedente, 'ross').count() == 1
    assert anagrafica.cerca(mondo.richiedente, 'zz').count() == 0


# ── L'eta': si precompila solo se e' recente ───────────────────────────────

def test_l_eta_vecchia_non_si_precompila(mondo):
    _caso(mondo, eta_testo='8 anni')
    voce = PazienteArchivio.objects.get()
    assert voce.eta_dal == timezone.localdate() and anagrafica.eta_fresca(voce)
    assert PazienteForm.iniziale_da_archivio(voce)['eta_anni'] == '8'
    # Un anno dopo la stessa frase e' una bugia: meglio chiederla.
    voce.eta_dal = timezone.localdate() - timedelta(days=365)
    voce.save(update_fields=['eta_dal'])
    assert not anagrafica.eta_fresca(voce)
    assert 'eta_anni' not in PazienteForm.iniziale_da_archivio(voce)


def test_la_data_di_nascita_si_precompila_sempre(mondo):
    _caso(mondo, data_nascita=date(2019, 3, 15))
    voce = PazienteArchivio.objects.get()
    assert PazienteForm.iniziale_da_archivio(voce)['data_nascita'] == '15/03/2019'


def test_rinviare_con_la_stessa_eta_non_la_fa_tornare_fresca(mondo):
    _caso(mondo, eta_testo='8 anni')
    voce = PazienteArchivio.objects.get()
    vecchia = timezone.localdate() - timedelta(days=300)
    PazienteArchivio.objects.filter(pk=voce.pk).update(eta_dal=vecchia)
    _caso(mondo, eta_testo='8 anni')
    voce.refresh_from_db()
    assert voce.eta_dal == vecchia          # nessuno l'ha ricontrollata
    _caso(mondo, eta_testo='9 anni')
    voce.refresh_from_db()
    assert voce.eta_dal == timezone.localdate()


# ── Le pagine: proposte e precompilazione ──────────────────────────────────

def test_il_frammento_propone_i_pazienti_della_clinica(client, mondo):
    _caso(mondo, cognome_proprietario='Rossi', razza='Labrador')
    client.force_login(_collega(mondo).user)
    pagina = _t(client.get(reverse('consulti:archivio'), {'nome': 'lun'}))
    assert 'Luna' in pagina and 'Cane, Labrador' in pagina and 'ultimo caso' in pagina
    assert f'?archivio={PazienteArchivio.objects.get().pk}' in pagina
    # Niente da proporre: nessuna scatola vuota.
    assert _t(client.get(reverse('consulti:archivio'), {'nome': 'zz'})).strip() == ''


def test_il_frammento_di_un_altra_clinica_non_vede_nulla(client, mondo):
    _caso(mondo)
    client.force_login(_altra_clinica().user)
    assert 'Luna' not in _t(client.get(reverse('consulti:archivio'), {'nome': 'lun'}))


def test_usa_questi_dati_precompila_il_passo_1_tranne_il_peso(client, mondo):
    _caso(mondo, cognome_proprietario='Rossi', razza='Labrador', peso_kg=Decimal('12.50'),
          data_nascita=date(2019, 3, 15))
    voce = PazienteArchivio.objects.get()
    client.force_login(mondo.richiedente.user)
    risposta = client.get(reverse('consulti:nuova'), {'archivio': voce.pk}, follow=True)
    pagina = _t(risposta)
    assert 'value="Luna"' in pagina and 'value="Labrador"' in pagina and 'value="15/03/2019"' in pagina
    assert 'value="12,50"' not in pagina and 'value="12.50"' not in pagina
    assert 'Il peso scrivilo comunque' in pagina
    assert 'Avevi gia\' iniziato' not in pagina
    assert client.session['richiesta_guidata_paziente']['archivio'] == str(voce.pk)


def test_l_eta_vecchia_lo_dice_sulla_pagina(client, mondo):
    _caso(mondo, eta_testo='8 anni')
    voce = PazienteArchivio.objects.get()
    PazienteArchivio.objects.filter(pk=voce.pk).update(eta_dal=timezone.localdate() - timedelta(days=400))
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:nuova'), {'archivio': voce.pk}, follow=True))
    assert 'ricontrollala' in pagina and 'value="8"' not in pagina


def test_un_archivio_di_un_altra_clinica_non_precompila_e_non_e_un_errore(client, mondo):
    _caso(mondo)
    voce = PazienteArchivio.objects.get()
    altro = _altra_clinica()
    client.force_login(altro.user)
    risposta = client.get(reverse('consulti:nuova'), {'archivio': voce.pk}, follow=True)
    assert risposta.status_code == 200 and 'value="Luna"' not in _t(risposta)


def test_il_giro_completo_lega_il_nuovo_caso_alla_stessa_voce(client, mondo, crea_bozza):
    """Primo caso inviato, secondo caso aperto dalla proposta: un solo
    paziente in archivio e due fotografie legate a lui."""
    _caso(mondo, cognome_proprietario='Rossi', razza='Labrador')
    voce = PazienteArchivio.objects.get()
    collega = _collega(mondo)
    client.force_login(collega.user)
    client.get(reverse('consulti:nuova'), {'archivio': voce.pk})
    bozza = crea_bozza(client, TipoEsame.ECG, mondo.ref,
                       paziente={'nome': 'Luna', 'specie': 'CANE', 'sesso': 'F', 'razza': 'Labrador',
                                 'cognome_proprietario': 'Rossi', 'archivio': str(voce.pk),
                                 'peso_kg': '13,1'})
    assert bozza.paziente.archivio == voce
    Allegato.da_upload(bozza, SimpleUploadedFile('e.pdf', b'%PDF-1.4', 'application/pdf'),
                       CategoriaAllegato.ECG_PDF, collega.user)
    bozza.invia(collega.user)
    assert PazienteArchivio.objects.count() == 1 and voce.pazienti.count() == 2


def test_il_passo_1_di_una_bozza_si_precompila_e_tiene_il_legame(client, mondo, crea_bozza):
    _caso(mondo, cognome_proprietario='Rossi', razza='Labrador')
    voce = PazienteArchivio.objects.get()
    client.force_login(mondo.richiedente.user)
    bozza = crea_bozza(client, TipoEsame.ECG, mondo.ref, paziente={'nome': 'Nerone'})
    pagina = _t(client.get(reverse('consulti:passo_paziente', args=[bozza.pk]), {'archivio': voce.pk}))
    assert 'value="Luna"' in pagina and f'value="{voce.pk}"' in pagina
    client.post(reverse('consulti:passo_paziente', args=[bozza.pk]),
                {'nome': 'Luna', 'specie': 'CANE', 'sesso': 'F', 'razza': 'Labrador',
                 'cognome_proprietario': 'Rossi', 'archivio': str(voce.pk)})
    bozza.paziente.refresh_from_db()
    assert bozza.paziente.archivio == voce


# ── Lo storico ─────────────────────────────────────────────────────────────

def test_lo_storico_mostra_il_caso_del_collega_senza_aprirlo(client, mondo):
    collega = _collega(mondo)
    vecchio = _caso(mondo, richiedente=collega, cognome_proprietario='Rossi')
    nuovo = _caso(mondo, cognome_proprietario='Rossi')
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[nuovo.pk])))
    assert 'Altri casi di Luna' in pagina and vecchio.codice in pagina
    assert f'/consulti/{vecchio.pk}/' not in pagina        # si legge, non si apre
    assert 'chiesto da Carla Neri' in pagina
    # E il caso del collega non si apre nemmeno a mano.
    assert client.get(reverse('consulti:dettaglio', args=[vecchio.pk])).status_code == 404


def test_lo_storico_non_elenca_le_bozze(client, mondo):
    inviato = _caso(mondo, cognome_proprietario='Rossi')
    bozza = _caso(mondo, cognome_proprietario='Rossi', invia=False)
    anagrafica.registra(bozza)      # anche se qualcuno la legasse a mano
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[inviato.pk])))
    assert bozza.codice not in pagina


def test_l_esperto_legge_il_referto_firmato_dell_altro_caso(client, mondo):
    """L'eccezione ai permessi: chi referta Luna oggi apre il referto di
    marzo, anche se quel caso e' di un altro esperto, e lascia traccia."""
    from referti.models import Referto

    vecchio = _caso(mondo, cognome_proprietario='Rossi')
    vecchio.prendi_in_carico(mondo.ref2, mondo.ref2.user)
    referto = Referto.objects.create(richiesta=vecchio, conclusioni='Ritmo sinusale.')
    with mock.patch('referti.pdf.genera_pdf', return_value=b'%PDF-1.4 finto'):
        referto.firma(mondo.ref2.user)
    nuovo = _caso(mondo, cognome_proprietario='Rossi')
    nuovo.prendi_in_carico(mondo.ref, mondo.ref.user)

    client.force_login(mondo.ref.user)
    pagina = _t(client.get(reverse('referti:refertazione', args=[nuovo.pk])))
    assert 'Altri casi di Luna' in pagina and vecchio.codice in pagina
    url_pdf = reverse('referti:stampa', args=[referto.pk])
    assert url_pdf in pagina
    assert client.get(url_pdf).status_code == 200
    assert vecchio.audit.filter(azione='ACCESSO_STORICO').count() == 1
    # La pagina del caso del collega resta chiusa.
    assert client.get(reverse('referti:refertazione', args=[vecchio.pk])).status_code == 404


def test_un_esperto_estraneo_al_paziente_non_legge_il_referto(client, mondo):
    from referti.models import Referto

    caso = _caso(mondo, cognome_proprietario='Rossi')
    caso.prendi_in_carico(mondo.ref, mondo.ref.user)
    referto = Referto.objects.create(richiesta=caso, conclusioni='x')
    with mock.patch('referti.pdf.genera_pdf', return_value=b'%PDF-1.4 finto'):
        referto.firma(mondo.ref.user)
    client.force_login(mondo.ref2.user)
    assert client.get(reverse('referti:stampa', args=[referto.pk])).status_code == 404
    assert not caso.audit.filter(azione='ACCESSO_STORICO').exists()


def test_lo_storico_di_un_caso_vecchio_senza_archivio_e_vuoto(client, mondo, caso_inviato):
    Paziente.objects.filter(pk=caso_inviato.paziente.pk).update(archivio=None)
    caso_inviato.refresh_from_db()
    assert list(anagrafica.altri_casi(caso_inviato)) == []
    client.force_login(mondo.richiedente.user)
    pagina = _t(client.get(reverse('consulti:dettaglio', args=[caso_inviato.pk])))
    assert 'Altri casi' not in pagina


def test_il_comando_popola_l_archivio_dai_casi_gia_inviati(mondo):
    from django.core.management import call_command
    from io import StringIO

    caso = _caso(mondo, cognome_proprietario='Rossi')
    PazienteArchivio.objects.all().delete()           # come i casi di prima del 05/11/2026
    caso.paziente.refresh_from_db()
    assert caso.paziente.archivio_id is None
    uscita = StringIO()
    call_command('popola_archivio_pazienti', stdout=uscita)
    caso.paziente.refresh_from_db()
    assert PazienteArchivio.objects.count() == 1 and caso.paziente.archivio is not None
    assert '1 pazienti nuovi' in uscita.getvalue()
    call_command('popola_archivio_pazienti', stdout=StringIO())   # idempotente
    assert PazienteArchivio.objects.count() == 1
