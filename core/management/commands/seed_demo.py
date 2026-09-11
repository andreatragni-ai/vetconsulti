"""Dati dimostrativi per il collaudo a mano del portale.

Non e' una fixture di test: i test si costruiscono i propri oggetti e non
devono dipendere da qui. Questo comando serve a una persona che apre il
browser e vuole vedere il portale con dentro qualcosa — senza listino e
senza refertatori la pagina «Nuova richiesta» e' una scatola vuota, e non
si capisce se funziona o se e' rotta.

Idempotente: si puo' rilanciare, aggiorna invece di duplicare.
Rifiuta di girare con DEBUG=False: sono account con password note.

## I casi dimostrativi (refertazione, F3)

Due casi gia' INVIATI da `gbianchi`, per collaudare subito il lato del
refertatore: un ECG a `rferrari` e un'eco a `lmonti`, quest'ultima con il
referto dell'ecografo e tutte le proiezioni obbligatorie del catalogo
(rispetta `perche_non_puoi_inviare`, come un invio vero; per ogni riga un
PNG segnaposto, anche dove il catalogo chiede un filmato). Gli allegati li
genera `core/demo.py`: PDF segnati DIMOSTRATIVO e PNG segnaposto, nessun
file reale. Un caso dimostrativo si crea solo se non ce n'e' gia' uno
aperto (inviato o preso in carico): rilanciare subito non duplica nulla,
rilanciare dopo averlo refertato ne prepara uno nuovo per un altro giro.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import (Clinica, CompetenzaRefertatore, DatiFatturazione,
                             Refertatore, Richiedente, RuoloRichiedente,
                             SoggettoEmittente, TipoRichiedente)
from consulti.models import (Allegato, CategoriaAllegato, Paziente, Richiesta,
                             Sesso, Specie, StatoRichiesta, TransizioneNonValida)
from core import demo
from core.tipi import TipoEsame
from listino.models import Supplemento, TipoSupplemento, VoceListino

PASSWORD = 'prova12345'
# Il segno che distingue i casi dimostrativi (sta in motivo_esame).
DEMO_ECG = 'DEMO — ECG di collaudo'
DEMO_ECO = 'DEMO — ecocardiografia di collaudo'


class Command(BaseCommand):
    help = 'Popola il database di sviluppo con dati dimostrativi (password note).'

    def handle(self, *args, **opzioni):
        if not settings.DEBUG:
            raise CommandError(
                'Questo comando crea account con password note: gira solo con DEBUG=True.')
        with transaction.atomic():
            self._admin()
            self._listino()
            self._refertatori()
            self._richiedenti()
            self._catalogo_eco()
        self._casi_demo()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Dati dimostrativi pronti.'))
        self.stdout.write(f'Password di tutti gli account di prova: {PASSWORD}')

    # ── Staff ────────────────────────────────────────────────────────

    def _admin(self):
        """admin/admin, superuser: serve per l'area staff e per vedere il
        portale in sola lettura con l'audit degli accessi."""
        utente, creato = User.objects.get_or_create(
            username='admin', defaults={'email': 'admin@esempio.it', 'is_staff': True, 'is_superuser': True})
        if creato:
            utente.set_password('admin')
            utente.save()
        self.stdout.write('Staff admin/admin: ' + ('creato.' if creato else 'gia\' presente (password invariata).'))

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

    # ── Catalogo proiezioni eco ─────────────────────────────────────

    def _catalogo_eco(self):
        """Il catalogo di Andre (eco/catalogo/, con le immagini di
        riferimento), solo se il catalogo e' vuoto: se lo ha gia' ritoccato
        dall'admin non lo si sovrascrive. Per ricaricarlo dal file:
        `manage.py carica_catalogo_eco`."""
        from io import StringIO
        from eco.models import ProiezioneCatalogo
        if ProiezioneCatalogo.objects.exists():
            self.stdout.write(f'Catalogo eco: {ProiezioneCatalogo.objects.count()} proiezioni (lasciato com\'e\').')
            return
        uscita = StringIO()
        call_command('carica_catalogo_eco', stdout=uscita)
        self.stdout.write(uscita.getvalue().strip())

    # ── Casi dimostrativi ───────────────────────────────────────────

    def _casi_demo(self):
        richiedente = Richiedente.objects.get(user__username='gbianchi')
        self._caso(richiedente, 'rferrari', TipoEsame.ECG, DEMO_ECG, self._allegati_ecg, {
            'nome': 'Bruno', 'specie': Specie.CANE, 'razza': 'Boxer', 'sesso': Sesso.M,
            'eta_testo': '9 anni', 'peso_kg': Decimal('31.50'), 'cognome_proprietario': 'Esempio',
        }, quesito='Aritmia all\'auscultazione in visita pre-anestesiologica: e\' idoneo a una TPLO?',
            anamnesi='Nessun sintomo riferito. Soffio non rilevato. Esami del sangue nella norma.',
            terapia='Nessuna.')
        self._caso(richiedente, 'lmonti', TipoEsame.ECO, DEMO_ECO, self._allegati_eco, {
            'nome': 'Luna', 'specie': Specie.GATTO, 'razza': 'Comune Europeo', 'sesso': Sesso.FS,
            'eta_testo': '11 anni', 'peso_kg': Decimal('4.20'), 'cognome_proprietario': 'Esempio',
        }, quesito='Soffio sistolico 3/6 di recente riscontro: cardiomiopatia? Serve terapia?',
            anamnesi='Gatta di casa, asintomatica. Pressione sistolica 150 mmHg.',
            terapia='Nessuna.')

    def _caso(self, richiedente, username_ref, tipo, marcatore, allegati, paziente, **testi):
        aperti = Richiesta.objects.filter(
            richiedente=richiedente, motivo_esame=marcatore,
            stato__in=[StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO])
        if aperti.exists():
            self.stdout.write(f'Caso demo {tipo}: {aperti.first().codice} gia\' aperto, nessun duplicato.')
            return
        refertatore = Refertatore.objects.get(user__username=username_ref)
        utente = richiedente.user
        with transaction.atomic():
            richiesta = Richiesta.objects.create(
                tipo_esame=tipo, richiedente=richiedente, clinica=richiedente.clinica,
                refertatore=refertatore, motivo_esame=marcatore, **testi)
            Paziente.objects.create(richiesta=richiesta, **paziente)
            richiesta.registra('CREATA', utente, tipo=tipo, demo=True)
            allegati(richiesta, utente)
            try:
                richiesta.invia(utente)
            except TransizioneNonValida as e:
                raise CommandError(f'Il caso demo {tipo} non si puo\' inviare: {e}')
        self.stdout.write(f'Caso demo {tipo}: {richiesta.codice} inviato da gbianchi a {username_ref}.')

    @staticmethod
    def _allega(richiesta, utente, categoria, nome, contenuto, mime):
        return Allegato.da_upload(richiesta, SimpleUploadedFile(nome, contenuto, content_type=mime),
                                  categoria, utente)

    def _allegati_ecg(self, richiesta, utente):
        self._allega(richiesta, utente, CategoriaAllegato.ECG_PDF, 'ecg_dimostrativo.pdf',
                     demo.pdf_ecg_dimostrativo(), 'application/pdf')

    def _allegati_eco(self, richiesta, utente):
        from eco.models import ProiezioneCaricata, ProiezioneCatalogo
        self._allega(richiesta, utente, CategoriaAllegato.ECO_REFERTO_PDF, 'referto_ecografo_dimostrativo.pdf',
                     demo.pdf_referto_ecografo_dimostrativo(), 'application/pdf')
        for p in ProiezioneCatalogo.objects.filter(obbligatoria=True, attiva=True).order_by('ordine'):
            immagine = self._allega(richiesta, utente, CategoriaAllegato.ECO_STATICA,
                                    f'{p.codice.lower()}_dimostrativa.png',
                                    demo.png_proiezione_dimostrativa(p.nome), 'image/png')
            ProiezioneCaricata.objects.create(richiesta=richiesta, proiezione=p, allegato=immagine,
                                              nota='Immagine segnaposto (seed_demo)')
