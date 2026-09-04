"""Dati dimostrativi per il collaudo a mano del portale.

Non e' una fixture di test: i test si costruiscono i propri oggetti e non
devono dipendere da qui. Questo comando serve a una persona che apre il
browser e vuole vedere il portale con dentro qualcosa — senza listino e
senza refertatori la pagina «Nuova richiesta» e' una scatola vuota, e non
si capisce se funziona o se e' rotta.

Idempotente: si puo' rilanciare, aggiorna invece di duplicare.
Rifiuta di girare con DEBUG=False: sono account con password note.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import (Clinica, CompetenzaRefertatore, DatiFatturazione,
                             Refertatore, Richiedente, RuoloRichiedente,
                             SoggettoEmittente, TipoRichiedente)
from core.tipi import TipoEsame
from listino.models import Supplemento, TipoSupplemento, VoceListino

PASSWORD = 'prova12345'


class Command(BaseCommand):
    help = 'Popola il database di sviluppo con dati dimostrativi (password note).'

    def handle(self, *args, **opzioni):
        if not settings.DEBUG:
            raise CommandError(
                'Questo comando crea account con password note: gira solo con DEBUG=True.')
        with transaction.atomic():
            self._listino()
            self._refertatori()
            self._richiedenti()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Dati dimostrativi pronti.'))
        self.stdout.write(f'Password di tutti gli account di prova: {PASSWORD}')

    # ── Listino ──────────────────────────────────────────────────────

    def _listino(self):
        prezzi = {
            TipoEsame.ECG: ('Refertazione elettrocardiogramma', Decimal('35.00')),
            TipoEsame.HOLTER: ('Refertazione Holter 24 ore', Decimal('90.00')),
            TipoEsame.ECO: ('Refertazione ecocardiografia', Decimal('70.00')),
        }
        for tipo, (descrizione, prezzo) in prezzi.items():
            VoceListino.objects.update_or_create(
                tipo_esame=tipo, valido_al=None,
                defaults={'descrizione': descrizione, 'prezzo': prezzo,
                          'aliquota_iva': Decimal('22.00'),
                          'valido_dal': date(2026, 1, 1)})
        Supplemento.objects.update_or_create(
            codice='URGENZA',
            defaults={'descrizione': 'Risposta entro 4 ore',
                      'tipo': TipoSupplemento.URGENZA,
                      'importo': Decimal('25.00'), 'percentuale': None,
                      'valido_dal': date(2026, 1, 1), 'valido_al': None})
        self.stdout.write('Listino: 3 voci + supplemento urgenza.')

    # ── Refertatori ──────────────────────────────────────────────────

    def _refertatori(self):
        # Due profili diversi apposta: serve a vedere che l'elenco degli
        # esperti cambia in base al tipo di esame scelto.
        persone = [
            ('rferrari', 'Roberto', 'Ferrari', 'Dott.', 'Cardiologia',
             '1234', 'Bergamo',
             {TipoEsame.ECG: (True, None, 24),
              TipoEsame.HOLTER: (True, Decimal('110.00'), 48),
              TipoEsame.ECO: (False, None, None)}),
            ('lmonti', 'Laura', 'Monti', 'Dott.ssa', 'Ecocardiografia',
             '5678', 'Milano',
             {TipoEsame.ECG: (False, None, None),
              TipoEsame.HOLTER: (False, None, None),
              TipoEsame.ECO: (True, Decimal('85.00'), 24)}),
        ]
        for (username, nome, cognome, titolo, spec, iscrizione, ordine,
             competenze) in persone:
            utente, _ = User.objects.get_or_create(
                username=username,
                defaults={'first_name': nome, 'last_name': cognome,
                          'email': f'{username}@esempio.it'})
            utente.set_password(PASSWORD)
            utente.save()
            refertatore, _ = Refertatore.objects.update_or_create(
                user=utente,
                defaults={'titolo': titolo, 'specializzazione': spec,
                          'numero_iscrizione': iscrizione,
                          'ordine_provinciale': ordine, 'attivo': True,
                          'soggetto_emittente': SoggettoEmittente.SOCIETA})
            for tipo, (referente, prezzo, ore) in competenze.items():
                CompetenzaRefertatore.objects.update_or_create(
                    refertatore=refertatore, tipo_esame=tipo,
                    defaults={'referente': referente,
                              'prezzo_personalizzato': prezzo,
                              'tempo_risposta_ore': ore})
            quali = ', '.join(t for t, (r, _p, _o) in competenze.items() if r)
            self.stdout.write(f'Refertatore {username}: referente per {quali}.')

    # ── Richiedenti ──────────────────────────────────────────────────

    def _richiedenti(self):
        # 1) Clinica, con i dati fiscali intestati alla struttura.
        clinica, _ = Clinica.objects.update_or_create(
            denominazione='Ambulatorio Veterinario San Rocco',
            defaults={'indirizzo': 'Via Roma 12', 'cap': '24100',
                      'comune': 'Bergamo', 'provincia': 'BG',
                      'telefono': '035112233', 'email': 'info@sanrocco.example',
                      'approvata': True})
        DatiFatturazione.objects.update_or_create(
            clinica=clinica, richiedente=None,
            defaults={'intestatario': 'Ambulatorio Veterinario San Rocco Srl',
                      'partita_iva': '00743110157',
                      'codice_fiscale': '00743110157',
                      'indirizzo_sede': 'Via Roma 12', 'cap': '24100',
                      'comune': 'Bergamo', 'provincia': 'BG',
                      'codice_sdi': 'ABCDEFG', 'predefinita': True})
        utente, _ = User.objects.get_or_create(
            username='gbianchi',
            defaults={'first_name': 'Giulia', 'last_name': 'Bianchi',
                      'email': 'gbianchi@esempio.it'})
        utente.set_password(PASSWORD)
        utente.save()
        Richiedente.objects.update_or_create(
            user=utente,
            defaults={'tipo': TipoRichiedente.CLINICA, 'clinica': clinica,
                      'approvato': True, 'telefono': '035112233',
                      'numero_iscrizione': '9012', 'ordine_provinciale': 'Bergamo',
                      'ruolo': RuoloRichiedente.VETERINARIO})
        self.stdout.write('Richiedente gbianchi: clinica San Rocco (approvata).')

        # 2) Libero professionista, fattura a suo nome.
        utente2, _ = User.objects.get_or_create(
            username='mrossi',
            defaults={'first_name': 'Marco', 'last_name': 'Rossi',
                      'email': 'mrossi@esempio.it'})
        utente2.set_password(PASSWORD)
        utente2.save()
        richiedente2, _ = Richiedente.objects.update_or_create(
            user=utente2,
            defaults={'tipo': TipoRichiedente.LIBERO_PROFESSIONISTA,
                      'clinica': None, 'approvato': True,
                      'telefono': '3391122334', 'numero_iscrizione': '3456',
                      'ordine_provinciale': 'Genova',
                      'ruolo': RuoloRichiedente.VETERINARIO})
        DatiFatturazione.objects.update_or_create(
            clinica=None, richiedente=richiedente2,
            defaults={'intestatario': 'Marco Rossi',
                      'partita_iva': '01234567897',
                      'codice_fiscale': 'RSSMRC80A01D969P',
                      'indirizzo_sede': 'Corso Italia 5', 'cap': '16145',
                      'comune': 'Genova', 'provincia': 'GE',
                      'codice_sdi': '0000000',
                      'pec_fatturazione': 'marco.rossi@pec.example',
                      'predefinita': True})
        self.stdout.write('Richiedente mrossi: libero professionista (approvato).')
