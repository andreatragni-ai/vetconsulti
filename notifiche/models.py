"""Registro di ogni email che l'app prova a mandare. L'invio e' best-effort:
se l'SMTP e' giu' il consulto va avanti, ma qui resta scritto che l'avviso
non e' partito, cosi' qualcuno puo' chiamare."""

from django.db import models

from consulti.models import Richiesta


class TipoInvio(models.TextChoices):
    CASO_ARRIVATO = 'CASO_ARRIVATO', 'Nuovo caso per il refertatore'
    REFERTO_PRONTO = 'REFERTO_PRONTO', 'Referto pronto per il richiedente'
    REFERTO_RETTIFICATO = 'REFERTO_RETTIFICATO', 'Referto rettificato per il richiedente'
    CASO_DECLINATO = 'CASO_DECLINATO', 'Caso declinato: il richiedente deve sceglierne un altro'
    NON_REFERTABILE = 'NON_REFERTABILE', 'Caso non refertabile per il richiedente'
    SOLLECITO = 'SOLLECITO', 'Sollecito al refertatore a meta\' tempo'
    RILASCIO = 'RILASCIO', 'Presa in carico rilasciata per inattivita\''
    ALTRO = 'ALTRO', 'Altro'


class EsitoInvio(models.TextChoices):
    OK = 'OK', 'Inviata'
    ERRORE = 'ERRORE', 'Errore'


class InvioEmail(models.Model):
    destinatario = models.EmailField()
    oggetto = models.CharField(max_length=200)
    tipo = models.CharField(max_length=20, choices=TipoInvio.choices, default=TipoInvio.ALTRO)
    richiesta = models.ForeignKey(Richiesta, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='invii_email')
    inviata_il = models.DateTimeField(auto_now_add=True)
    esito = models.CharField(max_length=10, choices=EsitoInvio.choices)
    errore = models.TextField(blank=True)
    allegati = models.CharField(max_length=300, blank=True, help_text='Nomi dei file allegati, separati da virgola.')

    class Meta:
        verbose_name = 'Invio email'
        verbose_name_plural = 'Invii email'
        ordering = ['-inviata_il']

    def __str__(self):
        return f'{self.inviata_il:%d/%m/%Y %H:%M} {self.get_tipo_display()} → {self.destinatario} [{self.esito}]'
