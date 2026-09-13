"""
La richiesta di consulto e cio' che le sta attorno.

## Il codice e' un contatore per anno, non un id

`TC-2026-0042` si legge al telefono, si scrive su una fattura, non salta
quando una bozza viene cancellata. Il contatore si incrementa dentro una
transazione con select_for_update: due richieste create nello stesso istante
non prendono lo stesso numero (su Postgres; sqlite serializza da solo).

## Le transizioni sono metodi, non assegnazioni

Nessuno scrive `richiesta.stato = 'INVIATA'` da fuori: si chiama `invia()`,
che controlla da dove si parte, applica le regole di consulti/regole.py,
mette la data giusta e scrive l'audit. Se una transizione non e' ammessa
solleva TransizioneNonValida con una frase per l'utente.

## L'intestatario non e' sempre una clinica

Chi chiede puo' essere una clinica o un singolo veterinario: `clinica` e'
nulla nel secondo caso e `intestatario()` ritorna chi va in testa al
referto e alla fattura, senza che chi lo usa debba distinguere.

## L'audit non si tocca

EventoAudit e' append-only: save() rifiuta di modificare una riga esistente
e delete() solleva. Non e' paranoia: e' l'unica cosa che permette, fra sei
mesi, di dire chi ha preso in carico cosa e quando.
"""

import hashlib
import mimetypes
import os

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from accounts.models import Clinica, Refertatore, Richiedente
from core.tipi import TipoEsame


class TransizioneNonValida(Exception):
    """Il messaggio e' pensato per l'utente."""


class ContatoreAnno(models.Model):
    """Ultimo progressivo assegnato in un anno. Una riga per anno."""

    anno = models.PositiveIntegerField(unique=True)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Contatore annuale'
        verbose_name_plural = 'Contatori annuali'

    def __str__(self):
        return f'{self.anno}: {self.ultimo}'

    @classmethod
    def prossimo_codice(cls, anno):
        with transaction.atomic():
            contatore, _ = cls.objects.select_for_update().get_or_create(anno=anno)
            contatore.ultimo += 1
            contatore.save(update_fields=['ultimo'])
            return f'TC-{anno}-{contatore.ultimo:04d}'


class StatoRichiesta(models.TextChoices):
    BOZZA = 'BOZZA', 'Bozza'
    INVIATA = 'INVIATA', 'Inviata'
    PRESA_IN_CARICO = 'PRESA_IN_CARICO', 'Presa in carico'
    REFERTATA = 'REFERTATA', 'Refertata'
    NON_REFERTABILE = 'NON_REFERTABILE', 'Non refertabile'
    DECLINATA = 'DECLINATA', 'Declinata'
    ANNULLATA = 'ANNULLATA', 'Annullata'


STATI_CHIUSI = (StatoRichiesta.REFERTATA, StatoRichiesta.NON_REFERTABILE,
                StatoRichiesta.DECLINATA, StatoRichiesta.ANNULLATA)


class Richiesta(models.Model):
    codice = models.CharField(max_length=15, unique=True, editable=False)
    tipo_esame = models.CharField(max_length=10, choices=TipoEsame.choices, db_index=True)
    richiedente = models.ForeignKey(Richiedente, on_delete=models.PROTECT, related_name='richieste')
    clinica = models.ForeignKey(
        Clinica, on_delete=models.PROTECT, null=True, blank=True, related_name='richieste',
        help_text='Vuota se chiede un libero professionista.')
    refertatore = models.ForeignKey(
        Refertatore, on_delete=models.PROTECT, null=True, blank=True, related_name='richieste')
    urgenza = models.BooleanField(default=False)
    stato = models.CharField(
        max_length=20, choices=StatoRichiesta.choices, default=StatoRichiesta.BOZZA, db_index=True)

    quesito = models.TextField(blank=True, help_text='Cosa si chiede al collega.')
    anamnesi = models.TextField(blank=True)
    terapia = models.TextField(blank=True, help_text='Terapia in corso.')
    motivo_esame = models.CharField(max_length=200, blank=True)

    creata_il = models.DateTimeField(auto_now_add=True)
    inviata_il = models.DateTimeField(null=True, blank=True)
    presa_in_carico_il = models.DateTimeField(null=True, blank=True)
    chiusa_il = models.DateTimeField(null=True, blank=True)
    motivo_rifiuto = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Richiesta di consulto'
        verbose_name_plural = 'Richieste di consulto'
        ordering = ['-creata_il']

    def __str__(self):
        return f'{self.codice} — {self.get_tipo_esame_display()} ({self.get_stato_display()})'

    # Tono della pillola di stato (.pill-stato--<tono> di vetway-ui): la
    # semantica sta qui, accanto agli stati, non sparsa nei template.
    TONO_STATO = {
        'BOZZA': '',                    # neutro
        'INVIATA': 'corso',
        'PRESA_IN_CARICO': 'attesa',
        'REFERTATA': 'ok',
        'ANNULLATA': 'chiusa',
        'DECLINATA': 'errore',
        'NON_REFERTABILE': 'errore',
    }

    @property
    def tono_stato(self):
        return self.TONO_STATO.get(self.stato, '')

    @property
    def titolo(self):
        """Come la ricorda un veterinario: «Luna · Ecocardiografia», non
        «TC-2026-0001». Il codice resta accanto, piccolo (fatture, telefono).
        Senza paziente (non dovrebbe capitare) si ripiega sul codice."""
        paziente = getattr(self, 'paziente', None)
        if paziente is None or not paziente.nome:
            return f'{self.codice} · {self.get_tipo_esame_display()}'
        return f'{paziente.nome} · {self.get_tipo_esame_display()}'

    def save(self, *args, **kwargs):
        if not self.codice:
            self.codice = ContatoreAnno.prossimo_codice(timezone.now().year)
        super().save(*args, **kwargs)

    def intestatario(self):
        """Chi va in testa al referto e alla fattura: la clinica, oppure il
        richiedente stesso se e' un libero professionista. Entrambi espongono
        `denominazione` e `dati_fatturazione_predefiniti`."""
        return self.clinica if self.clinica_id else self.richiedente

    # ── Audit ──────────────────────────────────────────────────────────

    def registra(self, azione, utente=None, **dettaglio):
        return EventoAudit.objects.create(
            richiesta=self, utente=utente, azione=azione, dettaglio=dettaglio)

    # ── Transizioni ────────────────────────────────────────────────────

    def _pretendi_stato(self, *ammessi):
        if self.stato not in ammessi:
            raise TransizioneNonValida(
                f'La richiesta {self.codice} e\' «{self.get_stato_display()}»: '
                f'operazione non ammessa.')

    def invia(self, utente=None):
        from . import regole
        self._pretendi_stato(StatoRichiesta.BOZZA)
        motivo = regole.perche_non_puoi_inviare(self)
        if motivo:
            raise TransizioneNonValida(motivo)
        self.stato = StatoRichiesta.INVIATA
        self.inviata_il = timezone.now()
        self.save(update_fields=['stato', 'inviata_il'])
        self.registra('INVIATA', utente, refertatore=self.refertatore_id)

    def prendi_in_carico(self, refertatore, utente=None):
        self._pretendi_stato(StatoRichiesta.INVIATA)
        if not refertatore.referta(self.tipo_esame):
            raise TransizioneNonValida(
                f'{refertatore} non e\' referente per {self.get_tipo_esame_display()}.')
        self.refertatore = refertatore
        self.stato = StatoRichiesta.PRESA_IN_CARICO
        self.presa_in_carico_il = timezone.now()
        self.save(update_fields=['refertatore', 'stato', 'presa_in_carico_il'])
        self.registra('PRESA_IN_CARICO', utente or refertatore.user, refertatore=refertatore.id)

    def rilascia_presa_in_carico(self, utente=None, motivo=''):
        """Torna INVIATA: il refertatore resta indicato, ma il caso e' di
        nuovo aperto. Lo usa anche sorveglia_consulti per le prese in carico
        dimenticate."""
        self._pretendi_stato(StatoRichiesta.PRESA_IN_CARICO)
        self.stato = StatoRichiesta.INVIATA
        self.presa_in_carico_il = None
        self.save(update_fields=['stato', 'presa_in_carico_il'])
        self.registra('RILASCIATA', utente, motivo=motivo)

    def declina(self, motivo, utente=None):
        self._pretendi_stato(StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO)
        if not (motivo or '').strip():
            raise TransizioneNonValida('Per declinare serve un motivo: lo legge chi ha chiesto.')
        self.stato = StatoRichiesta.DECLINATA
        self.motivo_rifiuto = motivo.strip()
        self.chiusa_il = timezone.now()
        self.save(update_fields=['stato', 'motivo_rifiuto', 'chiusa_il'])
        self.registra('DECLINATA', utente, motivo=self.motivo_rifiuto)

    def riassegna(self, refertatore, utente=None):
        """Un caso declinato torna a chi l'ha chiesto, che lo gira a un altro
        esperto: stesso codice, stessi allegati, di nuovo INVIATA. Il motivo
        del rifiuto resta nell'audit. Una bozza di referto non firmata del
        collega che ha declinato si butta: il nuovo esperto parte da zero."""
        from . import regole
        self._pretendi_stato(StatoRichiesta.DECLINATA)
        motivo = regole.perche_non_puoi_riassegnare(self, refertatore)
        if motivo:
            raise TransizioneNonValida(motivo)
        precedente = self.refertatore_id
        bozza = getattr(self, 'referto', None)
        if bozza is not None and not bozza.firmato:
            bozza.delete()
        self.refertatore = refertatore
        self.stato = StatoRichiesta.INVIATA
        self.inviata_il = timezone.now()
        self.presa_in_carico_il = None
        self.chiusa_il = None
        self.motivo_rifiuto = ''
        self.save(update_fields=['refertatore', 'stato', 'inviata_il', 'presa_in_carico_il', 'chiusa_il',
                                 'motivo_rifiuto'])
        self.registra('RIASSEGNATA', utente, da=precedente, refertatore=refertatore.id)

    def segna_non_refertabile(self, motivo, utente=None):
        self._pretendi_stato(StatoRichiesta.PRESA_IN_CARICO)
        if not (motivo or '').strip():
            raise TransizioneNonValida('Serve il motivo per cui il caso non e\' refertabile.')
        self.stato = StatoRichiesta.NON_REFERTABILE
        self.motivo_rifiuto = motivo.strip()
        self.chiusa_il = timezone.now()
        self.save(update_fields=['stato', 'motivo_rifiuto', 'chiusa_il'])
        self.registra('NON_REFERTABILE', utente, motivo=self.motivo_rifiuto)

    def annulla(self, utente=None):
        """Solo chi ha chiesto annulla, e solo prima che qualcuno ci lavori."""
        self._pretendi_stato(StatoRichiesta.BOZZA, StatoRichiesta.INVIATA)
        self.stato = StatoRichiesta.ANNULLATA
        self.chiusa_il = timezone.now()
        self.save(update_fields=['stato', 'chiusa_il'])
        self.registra('ANNULLATA', utente)

    # ── Emergenze: solo dalla Gestione ────────────────────────────────

    STATI_SPOSTABILI = (StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO, StatoRichiesta.DECLINATA)

    def sposta_da_gestione(self, refertatore, motivo, utente):
        """La gestione affida un caso aperto a un altro esperto: quello
        assegnato si e' ammalato, non risponde, o il caso non era il suo.

        Da INVIATA, PRESA_IN_CARICO o DECLINATA si torna INVIATA al nuovo
        esperto, con il tempo di risposta che riparte da adesso (anche il
        sollecito, che guarda `inviata_il`). Valgono le stesse regole di chi
        sceglie l'esperto: referente per quel tipo, e disposto alle urgenze
        se il caso e' urgente. Una bozza di referto non firmata del collega
        precedente si butta, come nella riassegnazione.

        Il motivo e' obbligatorio e resta nell'audit: e' l'unica traccia del
        perche' qualcuno ha tolto un caso a un collega.
        """
        from . import regole
        self._pretendi_stato(*self.STATI_SPOSTABILI)
        if not (motivo or '').strip():
            raise TransizioneNonValida('Serve un motivo: resta scritto nella storia del caso.')
        if refertatore is None:
            raise TransizioneNonValida('Scegli l\'esperto a cui affidare il caso.')
        if refertatore.pk == self.refertatore_id and self.stato != StatoRichiesta.DECLINATA:
            raise TransizioneNonValida(f'Il caso e\' gia\' di {refertatore}.')
        if not refertatore.referta(self.tipo_esame):
            raise TransizioneNonValida(
                f'{refertatore} non e\' referente per {self.get_tipo_esame_display()}.')
        rifiuto = regole.rifiuta_urgenza(refertatore, self.tipo_esame, self.urgenza)
        if rifiuto:
            raise TransizioneNonValida(rifiuto)
        precedente = self.refertatore_id
        bozza = getattr(self, 'referto', None)
        if bozza is not None and not bozza.firmato:
            bozza.delete()
        self.refertatore = refertatore
        self.stato = StatoRichiesta.INVIATA
        self.inviata_il = timezone.now()
        self.presa_in_carico_il = None
        self.chiusa_il = None
        self.motivo_rifiuto = ''
        self.save(update_fields=['refertatore', 'stato', 'inviata_il', 'presa_in_carico_il', 'chiusa_il',
                                 'motivo_rifiuto'])
        self.registra('SPOSTATA_DA_GESTIONE', utente, da=precedente, refertatore=refertatore.id,
                      motivo=motivo.strip())
        return precedente

    def annulla_da_gestione(self, motivo, utente):
        """La gestione chiude un caso che non deve andare avanti (inviato per
        sbaglio, paziente morto, richiedente che chiama per ritirarlo quando
        l'esperto ci sta gia' lavorando). Nessuna prestazione: non c'e' un
        referto firmato. Il motivo arriva per email a chi ha chiesto."""
        self._pretendi_stato(*self.STATI_SPOSTABILI)
        if not (motivo or '').strip():
            raise TransizioneNonValida('Serve un motivo: lo legge chi ha chiesto il consulto.')
        self.stato = StatoRichiesta.ANNULLATA
        self.chiusa_il = timezone.now()
        self.save(update_fields=['stato', 'chiusa_il'])
        self.registra('ANNULLATA_DA_GESTIONE', utente, motivo=motivo.strip())

    def segna_refertata(self, utente=None):
        """Chiamata da Referto.firma(): non si referta da fuori."""
        self._pretendi_stato(StatoRichiesta.PRESA_IN_CARICO)
        self.stato = StatoRichiesta.REFERTATA
        self.chiusa_il = timezone.now()
        self.save(update_fields=['stato', 'chiusa_il'])
        self.registra('REFERTATA', utente)

    @property
    def chiusa(self):
        return self.stato in STATI_CHIUSI

    @property
    def modificabile(self):
        return self.stato == StatoRichiesta.BOZZA


class Specie(models.TextChoices):
    """Solo cane e gatto (collaudo dell'11/09/2026): il portale e' di
    cardiologia dei piccoli animali, «Altro» non serviva a nessuno."""
    CANE = 'CANE', 'Cane'
    GATTO = 'GATTO', 'Gatto'


class Sesso(models.TextChoices):
    M = 'M', 'Maschio'
    MC = 'MC', 'Maschio castrato'
    F = 'F', 'Femmina'
    FS = 'FS', 'Femmina sterilizzata'
    ND = 'ND', 'Non noto'


class Paziente(models.Model):
    """I dati del paziente vivono sulla richiesta, non in un'anagrafica: il
    portale non e' la cartella clinica della clinica, e lo stesso cane su due
    richieste diverse sono due pazienti (potrebbe essere cambiato il peso,
    o il proprietario)."""

    richiesta = models.OneToOneField(Richiesta, on_delete=models.CASCADE, related_name='paziente')
    nome = models.CharField(max_length=100)
    specie = models.CharField(max_length=10, choices=Specie.choices, default=Specie.CANE)
    razza = models.CharField(max_length=100, blank=True)
    sesso = models.CharField(max_length=2, choices=Sesso.choices, default=Sesso.ND)
    data_nascita = models.DateField(null=True, blank=True)
    eta_testo = models.CharField(max_length=30, blank=True, help_text='Es. «8 anni», se la data non e\' nota.')
    peso_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cognome_proprietario = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = 'Paziente'
        verbose_name_plural = 'Pazienti'

    def __str__(self):
        return f'{self.nome} ({self.get_specie_display()}{", " + self.razza if self.razza else ""})'

    def save(self, *args, **kwargs):
        # «luna» -> «Luna», «de simone» -> «De Simone»; «McDonald» resta com'e' (consulti/nomi.py).
        from .nomi import maiuscole_nome
        self.nome = maiuscole_nome(self.nome)
        self.cognome_proprietario = maiuscole_nome(self.cognome_proprietario)
        super().save(*args, **kwargs)


class CategoriaAllegato(models.TextChoices):
    ECG_PDF = 'ECG_PDF', 'Tracciato ECG (PDF)'
    ECG_IMMAGINE = 'ECG_IMMAGINE', 'Tracciato ECG (immagine)'
    HOLTER_REFERTO = 'HOLTER_REFERTO', 'Referto Holter dell\'apparecchio'
    HOLTER_FILE = 'HOLTER_FILE', 'File grezzo Holter'
    ECO_REFERTO_PDF = 'ECO_REFERTO_PDF', 'Referto ecografo (PDF)'
    ECO_STATICA = 'ECO_STATICA', 'Immagine eco statica'
    ECO_CLIP = 'ECO_CLIP', 'Clip eco'
    ALTRO = 'ALTRO', 'Altro'


class StatoAllegato(models.TextChoices):
    CARICATO = 'CARICATO', 'Caricato'
    TRANSCODIFICATO = 'TRANSCODIFICATO', 'Transcodificato'
    SCARTATO = 'SCARTATO', 'Scartato'


def percorso_allegato(allegato, nome):
    """allegati/2026/TC-2026-0042/<nome>: si ritrova a mano e non collide
    fra richieste. Il nome originale sta nel campo, non nel percorso."""
    base, ext = os.path.splitext(nome)
    ext = ext.lower()[:10]
    codice = allegato.richiesta.codice
    anno = codice.split('-')[1]
    return f'allegati/{anno}/{codice}/{allegato.categoria.lower()}_{timezone.now():%H%M%S%f}{ext}'


def percorso_anteprima(allegato, nome):
    """Accanto agli allegati della richiesta, in anteprime/: sempre JPEG."""
    codice = allegato.richiesta.codice
    anno = codice.split('-')[1]
    return f'allegati/{anno}/{codice}/anteprime/{timezone.now():%H%M%S%f}.jpg'


class Allegato(models.Model):
    richiesta = models.ForeignKey(Richiesta, on_delete=models.CASCADE, related_name='allegati')
    categoria = models.CharField(max_length=20, choices=CategoriaAllegato.choices, db_index=True)
    file = models.FileField(upload_to=percorso_allegato, max_length=300)
    nome_originale = models.CharField(max_length=255, blank=True)
    dimensione = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    mime = models.CharField(max_length=100, blank=True)
    stato = models.CharField(max_length=20, choices=StatoAllegato.choices, default=StatoAllegato.CARICATO)
    caricato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    caricato_il = models.DateTimeField(auto_now_add=True)
    # Miniatura JPEG (lato lungo al massimo 800 px): per un filmato il
    # fotogramma a meta' durata, per un'immagine l'immagine ridotta. La fa il
    # browser mentre carica; se non c'e' la fa il server (consulti/anteprime.py:
    # Pillow per le immagini, ffmpeg per i filmati se installato). Serve allo
    # smistamento automatico dell'eco e agli elenchi dei file: `url_anteprima`.
    anteprima = models.ImageField(upload_to=percorso_anteprima, blank=True, max_length=300)

    class Meta:
        verbose_name = 'Allegato'
        verbose_name_plural = 'Allegati'
        ordering = ['caricato_il']

    def __str__(self):
        return f'{self.richiesta.codice} — {self.get_categoria_display()} — {self.nome_originale or self.file.name}'

    @property
    def url_anteprima(self):
        """L'indirizzo della miniatura (view protetta, stessi permessi del
        file: core.views_media.anteprima_allegato), o None se non c'e'."""
        if not self.anteprima:
            return None
        from django.urls import reverse
        return reverse('anteprima_allegato', args=[self.pk])

    @property
    def genere(self):
        """Come lo mostra il visore: 'pdf', 'immagine', 'video' o 'altro'
        (quest'ultimo solo da scaricare). Prima il MIME dichiarato, poi
        l'estensione del file salvato (la transcodifica cambia in .mp4)."""
        mime = (self.mime or '').lower()
        if not mime or mime == 'application/octet-stream':
            mime = (mimetypes.guess_type(self.file.name or self.nome_originale or '')[0] or '').lower()
        if mime == 'application/pdf':
            return 'pdf'
        if mime.startswith('image/') and mime not in ('image/tiff', 'image/x-tiff'):
            return 'immagine'
        if mime in ('video/mp4', 'video/webm', 'video/ogg', 'video/quicktime'):
            return 'video'
        return 'altro'

    @classmethod
    def da_upload(cls, richiesta, file_caricato, categoria, utente=None, *, nome=None, mime=None,
                  impronta=None, **dettaglio_audit):
        """Crea un allegato da un UploadedFile (o da un File gia' su disco,
        come alla fine del caricamento a pezzi) calcolando impronta e
        dimensione in un solo passaggio, prima che il file finisca nello
        storage. `impronta` si passa quando e' gia' stata verificata;
        `dettaglio_audit` finisce nell'evento ALLEGATO_CARICATO."""
        if impronta is None:
            digest = hashlib.sha256()
            for blocco in file_caricato.chunks():
                digest.update(blocco)
            file_caricato.seek(0)
            impronta = digest.hexdigest()
        nome = nome or getattr(file_caricato, 'name', '') or ''
        mime = (mime or getattr(file_caricato, 'content_type', '') or mimetypes.guess_type(nome)[0] or '')
        if mime == 'application/octet-stream':
            mime = mimetypes.guess_type(nome)[0] or mime
        allegato = cls(richiesta=richiesta, categoria=categoria, nome_originale=os.path.basename(nome)[:255],
                       dimensione=file_caricato.size, sha256=impronta, mime=mime[:100],
                       caricato_da=utente)
        allegato.file.save(os.path.basename(nome) or 'allegato', file_caricato, save=True)
        richiesta.registra('ALLEGATO_CARICATO', utente, allegato=allegato.id, categoria=categoria,
                           nome=allegato.nome_originale, **dettaglio_audit)
        return allegato


class Commento(models.Model):
    richiesta = models.ForeignKey(Richiesta, on_delete=models.CASCADE, related_name='commenti')
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    testo = models.TextField()
    allegato = models.ForeignKey(Allegato, on_delete=models.SET_NULL, null=True, blank=True)
    quando = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Commento'
        verbose_name_plural = 'Commenti'
        ordering = ['quando']

    def __str__(self):
        return f'{self.richiesta.codice} — {self.autore} — {self.quando:%d/%m/%Y %H:%M}'


class AuditNonModificabile(Exception):
    pass


class EventoAuditQuerySet(models.QuerySet):
    def delete(self):
        raise AuditNonModificabile('L\'audit non si cancella.')

    def update(self, **kwargs):
        raise AuditNonModificabile('L\'audit non si modifica.')


class EventoAudit(models.Model):
    richiesta = models.ForeignKey(Richiesta, on_delete=models.CASCADE, related_name='audit')
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    azione = models.CharField(max_length=40, db_index=True)
    dettaglio = models.JSONField(default=dict, blank=True)
    quando = models.DateTimeField(auto_now_add=True)

    objects = EventoAuditQuerySet.as_manager()

    class Meta:
        verbose_name = 'Evento di audit'
        verbose_name_plural = 'Eventi di audit'
        ordering = ['quando']

    def __str__(self):
        return f'{self.richiesta.codice} — {self.azione} — {self.quando:%d/%m/%Y %H:%M}'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AuditNonModificabile('Un evento di audit non si modifica: se ne scrive un altro.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditNonModificabile('L\'audit non si cancella.')
