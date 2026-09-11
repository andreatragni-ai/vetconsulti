"""
Il referto del consulto.

## Due cose diverse: la copia di lavoro e le versioni firmate

`Referto` e' la copia di lavoro del refertatore: una per richiesta, la si
salva quante volte si vuole (a mano o in automatico ogni 30 secondi) e non
la vede nessun altro. Salvare NON firma mai.

`VersioneReferto` e' un'istantanea firmata: i testi di quel momento, chi
ha firmato, quando, il PDF. Nasce solo da due rotte esplicite:

- `Referto.firma()` — la prima firma. Qui succede tutto: la richiesta passa
  a REFERTATA, si scrive l'audit, si registra la prestazione nel registro
  (con i prezzi di quel giorno) e nasce la versione 1.
- `Referto.rettifica()` — dopo la firma il refertatore corregge la copia di
  lavoro, scrive il motivo e emette la versione n+1. La prestazione NON si
  duplica (e' la stessa consulenza), le versioni precedenti restano con il
  loro PDF, consultabili e scaricabili.

Chi ha chiesto vede SOLO le versioni firmate: una bozza di rettifica
salvata ma non emessa non esce dal portale.

`classificazione` e' un JSON perche' cambia per esame: per l'ECG contiene
`rischio_anestesia`, per l'eco un domani lo stadio ACVIM. Le voci di ogni
tipo stanno in `referti/blocchi.py`, non in colonne: una colonna per esame
vorrebbe dire una migrazione a ogni esame nuovo.
"""

import logging

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from consulti.models import Richiesta

logger = logging.getLogger('referti')

CAMPI_TESTO = ('descrizione', 'conclusioni', 'raccomandazioni', 'classificazione')


class RefertoGiaFirmato(Exception):
    pass


class RefertoNonFirmabile(ValueError):
    """Il messaggio e' pensato per l'utente."""


class Referto(models.Model):
    richiesta = models.OneToOneField(Richiesta, on_delete=models.PROTECT, related_name='referto')
    descrizione = models.TextField(blank=True)
    conclusioni = models.TextField(blank=True)
    raccomandazioni = models.TextField(blank=True)
    classificazione = models.JSONField(default=dict, blank=True,
                                       help_text='Per esame. ECG: {"rischio_anestesia": "BASSO"} ecc.')
    motivo_rettifica = models.TextField(
        blank=True, help_text='Bozza del motivo della prossima rettifica; passa alla versione quando la si emette.')
    # Dati dell'ULTIMA versione firmata (None finche' non si firma).
    firmato_il = models.DateTimeField(null=True, blank=True)
    firmato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='referti_firmati')
    pdf = models.FileField(upload_to='referti/%Y/', blank=True, null=True, max_length=300,
                           help_text='PDF dell\'ultima versione firmata (lo stesso file della versione).')
    versione = models.PositiveIntegerField(default=1, help_text='Numero dell\'ultima versione firmata.')
    creato_il = models.DateTimeField(auto_now_add=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Referto'
        verbose_name_plural = 'Referti'
        ordering = ['-creato_il']

    def __str__(self):
        stato = f'firmato il {self.firmato_il:%d/%m/%Y}' if self.firmato_il else 'bozza'
        return f'Referto {self.richiesta.codice} v{self.versione} ({stato})'

    @property
    def firmato(self):
        return self.firmato_il is not None

    @property
    def ultima_versione(self):
        return self.versioni.order_by('-numero').first()

    def modificato_dopo_la_firma(self):
        """True se la copia di lavoro differisce dall'ultima versione firmata:
        c'e' una rettifica in preparazione."""
        ultima = self.ultima_versione
        if ultima is None:
            return False
        return any(getattr(self, c) != getattr(ultima, c) for c in CAMPI_TESTO)

    def _pretendi_refertatore(self, utente):
        refertatore = getattr(utente, 'refertatore', None)
        if refertatore is None or self.richiesta.refertatore_id != refertatore.id:
            raise PermissionError('Solo il refertatore assegnato firma il referto.')

    def _istantanea(self, utente, numero, motivo=''):
        return VersioneReferto.objects.create(
            referto=self, numero=numero, descrizione=self.descrizione, conclusioni=self.conclusioni,
            raccomandazioni=self.raccomandazioni, classificazione=self.classificazione,
            firmato_il=self.firmato_il, firmato_da=utente, motivo_rettifica=motivo)

    def _genera_pdf(self, versione):
        # Il PDF fuori dalla transazione: se WeasyPrint fallisce il referto
        # e' comunque firmato e il PDF si rigenera dalla view di stampa.
        from . import pdf
        try:
            pdf.genera_e_salva(versione)
        except Exception:
            logger.exception('PDF del referto %s v%s non generato.', self.richiesta.codice, versione.numero)

    def firma(self, utente):
        """Prima firma: stato, audit, registro, versione 1, PDF. Ritorna la versione."""
        from registro.servizi import registra_prestazione

        if self.firmato:
            raise RefertoGiaFirmato(f'Il referto {self.richiesta.codice} e\' gia\' firmato.')
        self._pretendi_refertatore(utente)
        if not (self.conclusioni or '').strip():
            raise RefertoNonFirmabile('Un referto senza conclusioni non si firma.')

        with transaction.atomic():
            self.firmato_il = timezone.now()
            self.firmato_da = utente
            self.versione = 1
            self.save(update_fields=['firmato_il', 'firmato_da', 'versione', 'aggiornato_il'])
            versione = self._istantanea(utente, 1)
            self.richiesta.segna_refertata(utente)
            self.richiesta.registra('REFERTO_FIRMATO', utente, referto=self.id, versione=1)
            registra_prestazione(self.richiesta)
        self._genera_pdf(versione)
        return versione

    def rettifica(self, utente):
        """Emette la versione n+1 dalla copia di lavoro salvata, con il motivo
        salvato in `motivo_rettifica`. Nessuna prestazione nuova."""
        if not self.firmato:
            raise RefertoNonFirmabile('Un referto mai firmato non si rettifica: si firma.')
        self._pretendi_refertatore(utente)
        motivo = (self.motivo_rettifica or '').strip()
        if not motivo:
            raise RefertoNonFirmabile('Per una rettifica serve il motivo: lo legge chi ha chiesto.')
        if not (self.conclusioni or '').strip():
            raise RefertoNonFirmabile('Un referto senza conclusioni non si firma.')
        if not self.modificato_dopo_la_firma():
            raise RefertoNonFirmabile('Il testo e\' identico all\'ultima versione firmata: niente da rettificare.')

        with transaction.atomic():
            numero = self.versione + 1
            self.firmato_il = timezone.now()
            self.firmato_da = utente
            self.versione = numero
            self.motivo_rettifica = ''
            self.save(update_fields=['firmato_il', 'firmato_da', 'versione', 'motivo_rettifica', 'aggiornato_il'])
            versione = self._istantanea(utente, numero, motivo)
            self.richiesta.registra('REFERTO_RETTIFICATO', utente, referto=self.id, versione=numero,
                                    motivo=motivo)
        self._genera_pdf(versione)
        return versione


class VersioneReferto(models.Model):
    """Istantanea firmata di un referto. I testi non si modificano: una
    correzione e' una versione nuova."""

    referto = models.ForeignKey(Referto, on_delete=models.PROTECT, related_name='versioni')
    numero = models.PositiveIntegerField()
    descrizione = models.TextField(blank=True)
    conclusioni = models.TextField()
    raccomandazioni = models.TextField(blank=True)
    classificazione = models.JSONField(default=dict, blank=True)
    firmato_il = models.DateTimeField()
    firmato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='versioni_firmate')
    motivo_rettifica = models.TextField(blank=True, help_text='Vuoto per la versione 1.')
    pdf = models.FileField(upload_to='referti/%Y/', blank=True, null=True, max_length=300)

    CAMPI_FIRMATI = ('numero', 'descrizione', 'conclusioni', 'raccomandazioni', 'classificazione',
                     'firmato_il', 'firmato_da_id', 'motivo_rettifica')

    class Meta:
        verbose_name = 'Versione del referto'
        verbose_name_plural = 'Versioni del referto'
        ordering = ['referto', '-numero']
        constraints = [
            models.UniqueConstraint(fields=['referto', 'numero'], name='versione_unica_per_referto'),
        ]

    def __str__(self):
        return f'{self.referto.richiesta.codice} v{self.numero} ({self.firmato_il:%d/%m/%Y})'

    @property
    def richiesta(self):
        return self.referto.richiesta

    @property
    def e_rettifica(self):
        return self.numero > 1

    def save(self, *args, **kwargs):
        # I testi di una versione firmata non cambiano; solo il PDF puo'
        # arrivare dopo (generazione fallita alla firma e rifatta).
        if self.pk is not None:
            originale = VersioneReferto.objects.filter(pk=self.pk).values(*self.CAMPI_FIRMATI).first()
            if originale and any(originale[k] != getattr(self, k) for k in self.CAMPI_FIRMATI):
                raise ValueError('Una versione firmata non si riscrive: si emette una rettifica.')
        super().save(*args, **kwargs)
