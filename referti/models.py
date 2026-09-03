"""
Il referto del consulto.

Un referto per richiesta. La firma e' il momento in cui succede tutto:
la richiesta passa a REFERTATA, si scrive l'audit, si registra la
prestazione nel registro (con i prezzi di quel giorno) e si genera il PDF.
Prima della firma il referto e' una bozza che il refertatore puo' rifare
quante volte vuole; dopo, non si tocca — se serve correggere, si alza la
versione con un referto nuovo (fase successiva).

`classificazione` e' un JSON perche' cambia per esame: per l'ECG contiene
per esempio `rischio_anestesia`, per l'eco lo stadio ACVIM. Metterli come
colonne vorrebbe dire una migrazione a ogni esame nuovo.
"""

import logging

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from consulti.models import Richiesta

logger = logging.getLogger('referti')


class RefertoGiaFirmato(Exception):
    pass


class Referto(models.Model):
    richiesta = models.OneToOneField(Richiesta, on_delete=models.PROTECT, related_name='referto')
    descrizione = models.TextField(blank=True)
    conclusioni = models.TextField(blank=True)
    raccomandazioni = models.TextField(blank=True)
    classificazione = models.JSONField(default=dict, blank=True,
                                       help_text='Per esame. ECG: {"rischio_anestesia": "basso"} ecc.')
    firmato_il = models.DateTimeField(null=True, blank=True)
    firmato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name='referti_firmati')
    pdf = models.FileField(upload_to='referti/%Y/', blank=True, null=True, max_length=300)
    versione = models.PositiveIntegerField(default=1)
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

    def firma(self, utente):
        """Firma il referto e chiude il cerchio: stato, audit, registro, PDF."""
        from registro.servizi import registra_prestazione
        from . import pdf

        if self.firmato:
            raise RefertoGiaFirmato(f'Il referto {self.richiesta.codice} e\' gia\' firmato.')
        refertatore = getattr(utente, 'refertatore', None)
        if refertatore is None or self.richiesta.refertatore_id != refertatore.id:
            raise PermissionError('Solo il refertatore assegnato firma il referto.')
        if not (self.conclusioni or '').strip():
            raise ValueError('Un referto senza conclusioni non si firma.')

        with transaction.atomic():
            self.firmato_il = timezone.now()
            self.firmato_da = utente
            self.save(update_fields=['firmato_il', 'firmato_da', 'aggiornato_il'])
            self.richiesta.segna_refertata(utente)
            self.richiesta.registra('REFERTO_FIRMATO', utente, referto=self.id, versione=self.versione)
            registra_prestazione(self.richiesta)
        # Il PDF fuori dalla transazione: se WeasyPrint fallisce il referto
        # e' comunque firmato e il PDF si rigenera dalla view di stampa.
        try:
            pdf.genera_e_salva(self)
        except Exception:
            logger.exception('PDF del referto %s non generato alla firma.', self.richiesta.codice)
        return self
