"""
Due colleghi finti recitano un consulto eco da cima a fondo, passando dalle
PAGINE del portale e non dai modelli (19/11/2026, chiesto da Andre: «un bot
che simuli il collega che chiede e uno che simuli il collega che referta»).

    manage.py recita_consulto                          # gbianchi -> lmonti, clip dimostrativa
    manage.py recita_consulto --con-riserva            # l'esperto chiede prima un'integrazione
    manage.py recita_consulto --cartella ~/clip_mindray  # con i filmati veri di un ecografo
    manage.py recita_consulto --richiedente prova.clinica --refertatore tandre   # sulla staging

Atto primo, il richiedente: entra, scrive il paziente (se lo trova in
archivio lo prende da li'), sceglie l'eco e l'esperto, carica il referto
dell'ecografo in PDF, le tre proiezioni di base come filmati, una proiezione
in piu' e un filmato libero con la nota, legge il riepilogo e invia.

Atto secondo, il refertatore: trova il caso fra i ricevuti, apre la pagina
di refertazione e CONTROLLA il materiale come farebbe un collega — la riga
di verdetto («Esame completo»), le durate delle clip, i file che il browser
puo' aprire. Poi decide: prende in carico, oppure (--con-riserva) accetta
con riserva chiedendo una proiezione, aspetta che il richiedente la carichi
e dichiari «ho caricato», e solo allora scrive. Il giudizio va nelle tre
caselle del referto (descrizione, conclusioni, raccomandazioni) e si firma.

Tutto passa dal test client di Django contro il database di DOVE SI LANCIA:
in locale le email escono in console e, senza ffmpeg, le clip restano come
arrivano; sul server le email partono davvero e ffmpeg converte. E' lo
stesso portale che usano i colleghi, un passo per volta: se una pagina si
rompe, si rompe qui per prima.

Cosa NON fa: non si iscrive (usa due account che esistono gia') e non
cancella niente alla fine — il caso resta, con il suo codice, da aprire e
guardare.
"""

import html
import mimetypes
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import reverse

from accounts.models import Refertatore, Richiedente
from consulti import anagrafica
from consulti.models import Richiesta, StatoRichiesta
from core import demo
from core.tipi import TipoEsame
from eco.models import ProiezioneCatalogo

MARCATORE = 'RECITA — consulto eco simulato'
ESTENSIONI_CLIP = ('.avi', '.mp4', '.mov', '.mkv', '.wmv')

PAZIENTE = {'nome': 'Luna', 'specie': 'GATTO', 'razza': 'Comune Europeo', 'sesso': 'FS',
            'eta_anni': '11', 'peso_kg': '4,2', 'cognome_proprietario': 'Recita'}
ESAME = {
    'quesito': 'Soffio sistolico 3/6 di recente riscontro in gatta asintomatica: cardiomiopatia? '
               'Serve iniziare una terapia?',
    'anamnesi': 'Gatta di casa, 11 anni, nessun sintomo. Pressione sistolica 150 mmHg. '
                'Esami ematochimici nella norma, T4 nella norma.',
    'terapia': 'Nessuna.',
}
GIUDIZIO = {
    'descrizione': 'Le tre proiezioni di base sono leggibili. In asse lungo e in asse corto il ventricolo '
                   'sinistro mostra un ispessimento concentrico della parete libera e del setto; in apicale '
                   '4 camere l\'atrio sinistro appare dilatato. Dal referto strumentale: IVSd 0,62 cm, '
                   'LVPWd 0,60 cm, LA/Ao 1,9.',
    'conclusioni': 'Quadro compatibile con cardiomiopatia ipertrofica in fase B2 (atrio sinistro dilatato, '
                   'gatta asintomatica).',
    'raccomandazioni': 'Suggerita terapia antitrombotica con clopidogrel 18,75 mg/die; controllo '
                       'ecocardiografico a 3 mesi. Da escludere ipertiroidismo e ipertensione come cause '
                       'secondarie: T4 e pressione risultano gia\' nella norma, quindi non servono altre '
                       'indagini al momento.',
}
RISERVA = 'Manca il color Doppler sull\'apicale 4 camere: senza non si valuta il rigurgito mitralico. ' \
          'Rifallo quando puoi, bastano quattro cicli.'
CODICE_INTEGRAZIONE = 'SX1_C'


def _t(risposta):
    return html.unescape(risposta.content.decode())


def _peso(byte):
    return f'{byte / 1024 / 1024:.1f} MB' if byte >= 1024 * 1024 else f'{byte / 1024:.0f} KB'


class _niente:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Command(BaseCommand):
    help = 'Due colleghi finti recitano un consulto eco dalle pagine del portale.'

    def add_arguments(self, parser):
        parser.add_argument('--richiedente', default='gbianchi', help='Username di chi chiede (default gbianchi).')
        parser.add_argument('--refertatore', default='lmonti', help='Username di chi referta (default lmonti).')
        parser.add_argument('--cartella', help='Cartella con i filmati veri da usare (i primi tre, in ordine di nome).')
        parser.add_argument('--con-riserva', action='store_true',
                            help='L\'esperto accetta con riserva e chiede una proiezione prima di refertare.')

    # ── Infrastruttura ──────────────────────────────────────────────────

    def handle(self, *args, **opzioni):
        self.inizio = time.time()
        host = urlparse(settings.CONSULTI_BASE_URL).hostname or 'testserver'
        self.sicuro = settings.CONSULTI_BASE_URL.startswith('https')
        self.client = Client(headers={'host': host})
        richiedente = self._richiedente(opzioni['richiedente'])
        refertatore = self._refertatore(opzioni['refertatore'])
        clip = self._clip(opzioni['cartella'])
        from eco.transcodifica import ffmpeg_disponibile
        if not ffmpeg_disponibile():
            self._dice('qui ffmpeg non c\'e\': le clip restano come arrivano, senza durata ne\' conversione',
                       ok=False)

        # In locale le email vanno in console e il PDF in base64 coprirebbe
        # il racconto: finche' dura la recita si tengono in memoria, e il
        # sipario le elenca da InvioEmail. Con l'SMTP vero non si tocca nulla.
        from django.test.utils import override_settings
        contesto = (override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
                    if 'console' in settings.EMAIL_BACKEND else _niente())
        with contesto:
            self._titolo('ATTO PRIMO — il collega che chiede: %s' % richiedente.user.get_full_name())
            caso = self._atto_primo(richiedente, refertatore, clip)
            self._titolo('ATTO SECONDO — il collega che referta: %s' % refertatore.nome_completo)
            self._atto_secondo(caso, richiedente, refertatore, opzioni['con_riserva'], clip)
        self._sipario(caso)

    def _richiedente(self, username):
        try:
            return Richiedente.objects.select_related('user', 'clinica').get(user__username=username)
        except Richiedente.DoesNotExist:
            raise CommandError(f'Nessun richiedente con username «{username}».')

    def _refertatore(self, username):
        try:
            r = Refertatore.objects.select_related('user').get(user__username=username)
        except Refertatore.DoesNotExist:
            raise CommandError(f'Nessun refertatore con username «{username}».')
        if not r.referta(TipoEsame.ECO):
            raise CommandError(f'{r} non e\' referente per l\'eco: scegline un altro con --refertatore.')
        return r

    def _clip(self, cartella):
        """[(nome, byte, mime)] per le tre proiezioni di base: i filmati veri
        della cartella, oppure tre copie della clip dimostrativa."""
        if not cartella:
            byte = demo.mp4_clip_dimostrativa()
            return [(f'clip_dimostrativa_{i}.mp4', byte, 'video/mp4') for i in (1, 2, 3)]
        percorso = Path(cartella).expanduser()
        file = sorted(p for p in percorso.iterdir() if p.suffix.lower() in ESTENSIONI_CLIP)
        if len(file) < 3:
            raise CommandError(f'In {percorso} ci sono {len(file)} filmati: ne servono almeno tre.')
        return [(p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
                for p in file[:3]]

    def _vai(self, metodo, url, dati=None, **extra):
        """Una richiesta come la farebbe il browser, con il controllo che la
        pagina abbia risposto. In https (la staging) il client deve dirlo,
        altrimenti SECURE_SSL_REDIRECT lo rimanda indietro."""
        chiamata = getattr(self.client, metodo)
        risposta = chiamata(url, dati or {}, secure=self.sicuro, **extra)
        if risposta.status_code >= 400:
            raise CommandError(f'{metodo.upper()} {url} ha risposto {risposta.status_code}: '
                               f'{_t(risposta)[:300]}')
        return risposta

    def _entra(self, utente):
        self.client.logout()
        self.client.force_login(utente)

    def _carica(self, caso, slot, nome, byte, mime, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        risposta = self._vai('post', reverse('consulti:carica_allegato', args=[caso.pk]),
                             {'slot': slot, 'file': SimpleUploadedFile(nome, byte, content_type=mime), **extra},
                             HTTP_ACCEPT='application/json')
        return risposta

    def _aspetta_transcodifiche(self):
        fili = [t for t in threading.enumerate() if t.name.startswith('transcodifica-')]
        if fili:
            self._dice(f'(aspetto {len(fili)} transcodific{"a" if len(fili) == 1 else "he"} sul server…)')
            for t in fili:
                t.join(timeout=600)

    # ── Il racconto ─────────────────────────────────────────────────────

    def _titolo(self, testo):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(testo))

    def _dice(self, testo, ok=True):
        segno = self.style.SUCCESS('✓') if ok else self.style.WARNING('!')
        self.stdout.write(f'  {segno} {testo}')

    def _legge(self, testo):
        self.stdout.write(f'    {self.style.HTTP_INFO("legge:")} {testo}')

    # ── Atto primo ──────────────────────────────────────────────────────

    def _atto_primo(self, richiedente, refertatore, clip):
        self._entra(richiedente.user)
        self._vai('get', reverse('consulti:nuova') + '?ricomincia=1')

        # Passo 1: il paziente, dall'archivio se c'e' gia'.
        dati = dict(PAZIENTE)
        voce = anagrafica.archivio_di(richiedente).filter(
            nome=PAZIENTE['nome'], cognome_proprietario=PAZIENTE['cognome_proprietario']).first()
        if voce is not None:
            self._vai('get', reverse('consulti:nuova'), {'archivio': voce.pk})
            dati['archivio'] = str(voce.pk)
            self._dice(f'scrive «{PAZIENTE["nome"]}» e il portale gliela propone dall\'archivio: la prende, '
                       f'riscrive solo il peso')
        else:
            self._dice(f'scrive il paziente da zero: {PAZIENTE["nome"]}, {PAZIENTE["razza"]}, '
                       f'{PAZIENTE["eta_anni"]} anni, {PAZIENTE["peso_kg"]} kg')
        self._vai('post', reverse('consulti:nuova'), dati)

        # Passo 2: l'esame e l'esperto.
        self._vai('post', reverse('consulti:nuova_esame'), {
            'tipo_esame': TipoEsame.ECO, 'refertatore': refertatore.pk, 'azione': 'avanti', **ESAME})
        caso = Richiesta.objects.filter(richiedente=richiedente, stato=StatoRichiesta.BOZZA).order_by('-pk').first()
        if caso is None:
            raise CommandError('La bozza non e\' nata: il passo 2 ha rifiutato qualcosa.')
        caso.motivo_esame = MARCATORE
        caso.save(update_fields=['motivo_esame'])
        self._dice(f'sceglie l\'eco e {refertatore.nome_completo}; nasce la bozza {caso.codice}')
        self._legge(f'quesito: «{ESAME["quesito"][:70]}…»')

        # Passo 3: il referto in PDF, le tre clip di base, una in piu', un filmato libero.
        pagina = _t(self._vai('get', reverse('consulti:passo_carica', args=[caso.pk])))
        riga = re.search(r'Che cosa serve per questo consulto.*?</ul>', pagina, re.S)
        if riga:
            self._legge('in cima al passo 3: ' + re.sub(r'<[^>]+>|\s+', ' ', riga.group(0))[:160] + '…')
        self._carica(caso, 'eco_referto', 'referto_ecografo.pdf',
                     demo.pdf_referto_ecografo_dimostrativo(), 'application/pdf')
        self._dice('carica il referto dell\'ecografo in PDF')
        base = list(ProiezioneCatalogo.objects.filter(obbligatoria=True, attiva=True, libera=False)
                    .order_by('ordine'))
        for p, (nome, byte, mime) in zip(base, clip):
            self._carica(caso, 'proiezione', nome, byte, mime, proiezione=p.pk)
            self._dice(f'carica «{nome}» come {p.nome} ({_peso(len(byte))})')
        extra = ProiezioneCatalogo.objects.filter(codice='DX5_LAAO', attiva=True).first()
        if extra is not None:
            self._carica(caso, 'proiezione', 'la_ao.png', demo.png_proiezione_dimostrativa(extra.nome),
                         'image/png', proiezione=extra.pk)
            self._dice(f'aggiunge una proiezione facoltativa: {extra.nome}')
        libero = ProiezioneCatalogo.objects.filter(libera=True, attiva=True).order_by('ordine').first()
        if libero is not None:
            self._carica(caso, 'proiezione', 'reperto.mp4', clip[0][1], clip[0][2], proiezione=libero.pk,
                         nota='Jet sospetto sulla valvola aortica in sottocostale: lo vedi anche tu?')
            self._dice('aggiunge un filmato libero con la nota «jet sospetto sulla valvola aortica…»')
        self._aspetta_transcodifiche()

        # Riepilogo e invio.
        riepilogo = _t(self._vai('get', reverse('consulti:passo_riepilogo', args=[caso.pk])))
        incompleto = 'presa_atto' in riepilogo
        if incompleto:
            self._dice('il riepilogo avvisa che manca qualcosa: spunta la presa d\'atto', ok=False)
        self._vai('post', reverse('consulti:invia', args=[caso.pk]),
                  {'presa_atto': 'si'} if incompleto else {}, follow=True)
        caso.refresh_from_db()
        if caso.stato != StatoRichiesta.INVIATA:
            raise CommandError(f'Il caso non e\' partito: e\' «{caso.get_stato_display()}».')
        self._dice(f'invia: {caso.codice} e\' {caso.get_stato_display().upper()}, email «caso arrivato» a '
                   f'{refertatore.user.email}')
        return caso

    # ── Atto secondo ────────────────────────────────────────────────────

    def _atto_secondo(self, caso, richiedente, refertatore, con_riserva, clip):
        self._entra(refertatore.user)
        ricevuti = _t(self._vai('get', reverse('consulti:casi_ricevuti')))
        if caso.codice not in ricevuti:
            raise CommandError(f'{caso.codice} non compare fra i casi ricevuti di {refertatore}.')
        self._dice(f'trova {caso.codice} fra i casi ricevuti')

        # Controlla il materiale come farebbe un collega.
        pagina = _t(self._vai('get', reverse('referti:refertazione', args=[caso.pk])))
        verdetto = re.search(r'Esame (completo|incompleto)[^<]*', pagina)
        self._legge(verdetto.group(0).strip() if verdetto else 'nessuna riga di verdetto')
        n = re.search(r'di (\d+)</span>', pagina)
        self._legge(f'il visore mostra {n.group(1) if n else "?"} file, «Altri casi di {PAZIENTE["nome"]}» '
                    f'{"c\'e\'" if f"Altri casi di {PAZIENTE['nome']}" in pagina else "non c\'e\'"}')
        for a in caso.allegati.filter(categoria='ECO_CLIP').order_by('pk'):
            apribile = a.genere == 'video'
            durata = f'{float(a.durata_s):.1f} s' if a.durata_s else 'durata non misurata'
            self._legge(f'clip «{a.nome_originale}»: {a.get_stato_display().lower()}, {durata}, '
                        f'{"si apre nel browser" if apribile else "da scaricare (il browser non la apre)"}'
                        + (' — piu\' lunga del necessario' if a.durata_oltre_il_massimo else ''))

        if con_riserva:
            self._vai('post', reverse('consulti:prendi_in_carico', args=[caso.pk]),
                      {'riserva': 'si', 'testo': RISERVA})
            caso.refresh_from_db()
            self._dice(f'prende in carico CON RISERVA: «{RISERVA[:60]}…» — email al richiedente')

            self._entra(richiedente.user)
            dettaglio = _t(self._vai('get', reverse('consulti:dettaglio', args=[caso.pk])))
            if 'Ho caricato le integrazioni' not in dettaglio:
                raise CommandError('Il richiedente non vede il pulsante «Ho caricato le integrazioni».')
            self._dice('il richiedente legge la richiesta sul caso e torna a caricare')
            p = ProiezioneCatalogo.objects.filter(codice=CODICE_INTEGRAZIONE, attiva=True).first()
            if p is None:
                raise CommandError(f'La proiezione {CODICE_INTEGRAZIONE} non e\' nel catalogo.')
            self._carica(caso, 'proiezione', clip[2][0], clip[2][1], clip[2][2], proiezione=p.pk)
            self._aspetta_transcodifiche()
            self._vai('post', reverse('consulti:integrazioni_fatte', args=[caso.pk]), follow=True)
            self._dice(f'carica «{p.nome}» e preme «Ho caricato le integrazioni» — email all\'esperto')
            self._entra(refertatore.user)
        else:
            self._vai('post', reverse('consulti:prendi_in_carico', args=[caso.pk]))
            caso.refresh_from_db()
            self._dice('prende in carico il caso')

        # Il giudizio nelle tre caselle, poi la firma.
        self._vai('post', reverse('referti:salva_bozza', args=[caso.pk]), GIUDIZIO)
        self._dice('scrive descrizione, giudizio e suggerimenti nel referto (bozza salvata, non firmata)')
        self._vai('post', reverse('referti:firma', args=[caso.pk]), follow=True)
        caso.refresh_from_db()
        if caso.stato != StatoRichiesta.REFERTATA:
            raise CommandError(f'La firma non ha chiuso il caso: e\' «{caso.get_stato_display()}».')
        self._dice(f'firma: {caso.codice} e\' REFERTATO, PDF in email a {richiedente.user.email}')

    # ── Sipario ─────────────────────────────────────────────────────────

    def _sipario(self, caso):
        from notifiche.models import InvioEmail
        self._titolo('SIPARIO')
        email = InvioEmail.objects.filter(richiesta=caso).order_by('pk')
        for e in email:
            self._dice(f'email {e.get_tipo_display().lower()} → {e.destinatario}: {e.esito}',
                       ok=(e.esito == 'OK'))
        audit = list(caso.audit.order_by('quando').values_list('azione', flat=True))
        self.stdout.write(f'  audit: {" → ".join(audit)}')
        base = settings.CONSULTI_BASE_URL.rstrip('/')
        self.stdout.write(f'  caso: {base}{reverse("consulti:dettaglio", args=[caso.pk])}  '
                          f'(refertazione: {base}{reverse("referti:refertazione", args=[caso.pk])})')
        self.stdout.write(self.style.SUCCESS(
            f'  {caso.codice} recitato in {time.time() - self.inizio:.1f} s. Resta li\': guardalo.'))
