"""
Listino delle prestazioni e supplementi.

Le voci hanno una validita' temporale (valido_dal / valido_al) invece di
essere modificate in posto: cambiare il prezzo dell'ECG non deve cambiare
cio' che risulta per un consulto di tre mesi fa. Per lo stesso motivo il
registro copia i numeri nella Prestazione al momento della firma.
"""

from decimal import Decimal

from django.db import models

from core.tipi import TipoEsame


class VoceListino(models.Model):
    tipo_esame = models.CharField(max_length=10, choices=TipoEsame.choices, db_index=True)
    descrizione = models.CharField(max_length=200)
    prezzo = models.DecimalField(max_digits=8, decimal_places=2, verbose_name='Imponibile')
    aliquota_iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('22.00'))
    valido_dal = models.DateField()
    valido_al = models.DateField(null=True, blank=True, help_text='Vuoto = ancora in vigore.')

    class Meta:
        verbose_name = 'Voce di listino'
        verbose_name_plural = 'Voci di listino'
        ordering = ['tipo_esame', '-valido_dal']

    def __str__(self):
        fine = f' → {self.valido_al}' if self.valido_al else ''
        return f'{self.get_tipo_esame_display()} € {self.prezzo} (dal {self.valido_dal}{fine})'

    def in_vigore(self, giorno):
        return self.valido_dal <= giorno and (self.valido_al is None or giorno <= self.valido_al)


class TipoSupplemento(models.TextChoices):
    URGENZA = 'URGENZA', 'Urgenza'
    ALTRO = 'ALTRO', 'Altro'


class Supplemento(models.Model):
    """Un supplemento e' o un importo fisso o una percentuale sull'imponibile,
    mai entrambi: clean() lo pretende. Le percentuali si applicano
    all'imponibile base, non a supplementi precedenti."""

    codice = models.CharField(max_length=20, unique=True)
    descrizione = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=TipoSupplemento.choices, default=TipoSupplemento.ALTRO)
    importo = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    percentuale = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    valido_dal = models.DateField()
    valido_al = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = 'Supplemento'
        verbose_name_plural = 'Supplementi'
        ordering = ['codice']

    def __str__(self):
        quanto = f'€ {self.importo}' if self.importo is not None else f'{self.percentuale}%'
        return f'{self.codice} — {self.descrizione} ({quanto})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if (self.importo is None) == (self.percentuale is None):
            raise ValidationError('Indica o un importo o una percentuale, non entrambi ne\' nessuno.')

    def in_vigore(self, giorno):
        return self.valido_dal <= giorno and (self.valido_al is None or giorno <= self.valido_al)

    def calcola(self, imponibile):
        if self.importo is not None:
            return self.importo
        return (imponibile * self.percentuale / Decimal('100')).quantize(Decimal('0.01'))
