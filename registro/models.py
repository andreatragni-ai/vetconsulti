"""
Registro delle prestazioni eseguite: la base per fatturare.

## La Prestazione e' un fatto, non un'opinione

Alla firma del referto si scrive UNA riga con i numeri di quel momento:
chi, per chi, quanto, chi fattura. Se il mese dopo il listino cambia o il
refertatore passa a fatturare in proprio, quella riga non si muove. Per
questo save() rifiuta di riscrivere i campi del fatto: un errore va
corretto con uno storno (StatoFatturazione.STORNATA) e una riga nuova, non
con un UPDATE che cancella la storia.

`clinica` e' nulla quando chiede un libero professionista: `intestatario()`
ritorna a chi si fattura senza che l'export debba distinguere.

Lo stato della fatturazione invece cambia (da fatturare -> fatturata ->
pagata), e sta in un modello separato proprio perche' cambia.
"""

from decimal import Decimal

from django.db import models

from accounts.models import Clinica, Refertatore, Richiedente, SoggettoEmittente
from consulti.models import Richiesta
from core.tipi import TipoEsame


class PrestazioneImmutabile(Exception):
    pass


class Prestazione(models.Model):
    CAMPI_DEL_FATTO = ('richiesta_id', 'richiedente_id', 'clinica_id', 'refertatore_id', 'tipo_esame',
                       'data', 'soggetto_emittente', 'imponibile', 'supplementi', 'aliquota_iva',
                       'totale', 'origine_prezzo')

    richiesta = models.OneToOneField(Richiesta, on_delete=models.PROTECT, related_name='prestazione')
    richiedente = models.ForeignKey(Richiedente, on_delete=models.PROTECT, related_name='prestazioni')
    clinica = models.ForeignKey(
        Clinica, on_delete=models.PROTECT, null=True, blank=True, related_name='prestazioni',
        help_text='Vuota se la fattura va al richiedente (libero professionista).')
    refertatore = models.ForeignKey(Refertatore, on_delete=models.PROTECT, related_name='prestazioni')
    tipo_esame = models.CharField(max_length=10, choices=TipoEsame.choices)
    data = models.DateField(db_index=True)
    soggetto_emittente = models.CharField(max_length=20, choices=SoggettoEmittente.choices)
    imponibile = models.DecimalField(max_digits=8, decimal_places=2)
    supplementi = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    aliquota_iva = models.DecimalField(max_digits=5, decimal_places=2)
    totale = models.DecimalField(max_digits=8, decimal_places=2)
    origine_prezzo = models.CharField(max_length=20)
    registrata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Prestazione'
        verbose_name_plural = 'Prestazioni'
        ordering = ['-data', '-id']

    def __str__(self):
        return f'{self.richiesta.codice} — {self.get_tipo_esame_display()} — € {self.totale}'

    def intestatario(self):
        """A chi si fattura: la clinica, oppure il richiedente libero professionista."""
        return self.clinica if self.clinica_id else self.richiedente

    def save(self, *args, **kwargs):
        if self.pk is not None:
            originale = Prestazione.objects.filter(pk=self.pk).values(*self.CAMPI_DEL_FATTO).first()
            if originale:
                cambiati = [c for c in self.CAMPI_DEL_FATTO if originale[c] != getattr(self, c)]
                if cambiati:
                    raise PrestazioneImmutabile(
                        f'La prestazione {self.pk} non si riscrive (campi: {", ".join(cambiati)}). '
                        f'Storna e registra una riga nuova.')
        super().save(*args, **kwargs)


class StatoFatturazioneScelte(models.TextChoices):
    DA_FATTURARE = 'DA_FATTURARE', 'Da fatturare'
    FATTURATA = 'FATTURATA', 'Fatturata'
    PAGATA = 'PAGATA', 'Pagata'
    STORNATA = 'STORNATA', 'Stornata'


class StatoFatturazione(models.Model):
    prestazione = models.OneToOneField(Prestazione, on_delete=models.CASCADE, related_name='fatturazione')
    stato = models.CharField(max_length=20, choices=StatoFatturazioneScelte.choices,
                             default=StatoFatturazioneScelte.DA_FATTURARE, db_index=True)
    numero_fattura = models.CharField(max_length=50, blank=True)
    data_fattura = models.DateField(null=True, blank=True)
    riferimento_esterno = models.CharField(max_length=100, blank=True, help_text='Id nel gestionale.')
    note = models.TextField(blank=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Stato fatturazione'
        verbose_name_plural = 'Stati fatturazione'

    def __str__(self):
        return f'{self.prestazione.richiesta.codice} — {self.get_stato_display()}'
