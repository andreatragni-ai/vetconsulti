"""
Catalogo delle proiezioni ecocardiografiche e cosa e' stato caricato.

Il catalogo e' dati, non codice: si aggiunge una proiezione dall'admin, si
disattiva senza cancellare (le richieste vecchie la referenziano ancora).
Le regole di invio (consulti/regole.py) chiedono al catalogo quali sono le
obbligatorie: cambiare la lista non richiede un deploy.
"""

from django.db import models

from consulti.models import Allegato, Richiesta


class TipoMedia(models.TextChoices):
    CLIP = 'CLIP', 'Clip'
    STATICA = 'STATICA', 'Immagine statica'
    ENTRAMBI = 'ENTRAMBI', 'Clip e statica'


class ProiezioneCatalogo(models.Model):
    codice = models.CharField(max_length=30, unique=True)
    nome = models.CharField(max_length=120)
    descrizione = models.TextField(blank=True)
    istruzioni_misura = models.TextField(blank=True, help_text='Cosa misurare e come, in breve.')
    immagine_riferimento = models.ImageField(upload_to='eco_riferimento/', blank=True, null=True)
    tipo_media = models.CharField(max_length=10, choices=TipoMedia.choices, default=TipoMedia.CLIP)
    obbligatoria = models.BooleanField(default=False)
    ordine = models.PositiveIntegerField(default=0)
    attiva = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Proiezione (catalogo)'
        verbose_name_plural = 'Proiezioni (catalogo)'
        ordering = ['ordine', 'codice']

    def __str__(self):
        obbl = ' *' if self.obbligatoria else ''
        return f'{self.nome}{obbl}'


class ProiezioneCaricata(models.Model):
    """Lega un allegato di una richiesta a una voce del catalogo."""

    richiesta = models.ForeignKey(Richiesta, on_delete=models.CASCADE, related_name='proiezioni')
    proiezione = models.ForeignKey(ProiezioneCatalogo, on_delete=models.PROTECT)
    allegato = models.ForeignKey(Allegato, on_delete=models.CASCADE, related_name='proiezioni')
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = 'Proiezione caricata'
        verbose_name_plural = 'Proiezioni caricate'
        ordering = ['proiezione__ordine']

    def __str__(self):
        return f'{self.richiesta.codice} — {self.proiezione.nome}'
