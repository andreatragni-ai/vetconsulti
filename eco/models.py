"""
Catalogo delle proiezioni ecocardiografiche e cosa e' stato caricato.

Il catalogo e' dati, non codice: lo scrive Andre in `eco/catalogo/
catalogo_eco.json` (con le immagini di riferimento in `eco/catalogo/img/`)
e lo carica `manage.py carica_catalogo_eco`; si ritocca dall'admin; una
voce si disattiva senza cancellarla (le richieste vecchie la referenziano
ancora). Le regole di invio (consulti/regole.py) chiedono al catalogo quali
sono le obbligatorie: cambiare la lista non richiede un deploy.

## Una riga = un file

Ogni voce del catalogo e' una riga del passo «Carica gli esami» e riceve un
file solo: B-mode e color Doppler, Doppler pulsato e continuo sono voci
separate. I **filmati liberi** (`libera=True`, per esempio LIBERO_1 e
LIBERO_2) sono facoltativi e chiedono a chi carica una nota breve («cosa
mostra / cosa chiedi»), salvata in ProiezioneCaricata.nota.

## Testi di una riga

`istruzioni` (come si acquisisce) e `deve_essere_visibile` li legge chi
carica, sempre in vista; `serve_per` (a cosa serve, con le soglie cliniche)
e' soprattutto per il refertatore e sta in un richiudibile; `nota_riferimento`
e' un appunto per chi cura il catalogo e compare solo nell'admin.

## Ordine

Le righe si raggruppano per finestra acustica (parasternale destra,
sottoxifoidea, parasternale sinistra apicale e craniale, filmati liberi) e
dentro la finestra vengono prima i filmati poi le immagini, poi `ordine`.
`chiave_ordine` e' l'unico posto che lo decide: la usano sia le regole di
invio (l'ordine della lista di cio' che manca) sia il passo 3, cosi' lista e
righe hanno lo stesso ordine.
"""

from django.core.exceptions import ValidationError
from django.db import models

from consulti.models import Allegato, Richiesta


class TipoMedia(models.TextChoices):
    CLIP = 'CLIP', 'Clip'
    STATICA = 'STATICA', 'Immagine statica'
    ENTRAMBI = 'ENTRAMBI', 'Clip o statica'


class Finestra(models.TextChoices):
    PARASTERNALE_DESTRA = 'PARASTERNALE_DESTRA', 'Parasternale destra'
    SOTTOXIFOIDEA = 'SOTTOXIFOIDEA', 'Sottoxifoidea'
    PARASTERNALE_SINISTRA = 'PARASTERNALE_SINISTRA', 'Parasternale sinistra, apicale e craniale'
    ALTRO = 'ALTRO', 'Filmati liberi'


ORDINE_FINESTRE = (Finestra.PARASTERNALE_DESTRA, Finestra.SOTTOXIFOIDEA, Finestra.PARASTERNALE_SINISTRA,
                   Finestra.ALTRO)
# Dentro una finestra: prima i filmati, poi le righe che accettano entrambi, poi le immagini.
ORDINE_MEDIA = (TipoMedia.CLIP, TipoMedia.ENTRAMBI, TipoMedia.STATICA)


class ProiezioneCatalogo(models.Model):
    codice = models.CharField(max_length=30, unique=True)
    nome = models.CharField(max_length=120)
    descrizione = models.TextField(blank=True)
    istruzioni = models.TextField(blank=True, help_text='Come si acquisisce: la legge chi carica.')
    deve_essere_visibile = models.TextField(
        blank=True, help_text='Cosa deve vedersi nel filmato o nell\'immagine: la legge chi carica.')
    serve_per = models.TextField(
        blank=True, help_text='A cosa serve (anche soglie cliniche): nel passo di caricamento sta in un '
                              'richiudibile.')
    nota_riferimento = models.TextField(
        blank=True, help_text='Appunto su immagini di riferimento o contenuti: compare solo qui nell\'admin.')
    scheda_guida = models.CharField(
        max_length=20, blank=True, help_text='Scheda della guida da cui viene la voce (es. DX-1).')
    tipo_media = models.CharField(max_length=10, choices=TipoMedia.choices, default=TipoMedia.CLIP)
    finestra = models.CharField(
        max_length=25, choices=Finestra.choices, default=Finestra.ALTRO,
        help_text='Finestra acustica: raggruppa le righe nel passo «Carica gli esami».')
    libera = models.BooleanField(
        default=False,
        help_text='Filmato libero: facoltativo, con una nota di chi carica («cosa mostra / cosa chiedi»).')
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

    def clean(self):
        if self.libera and self.obbligatoria:
            raise ValidationError({'obbligatoria': 'Un filmato libero e\' sempre facoltativo.'})

    def chiave_ordine(self):
        """Liberi in fondo; poi finestra, filmati prima delle immagini, `ordine`."""
        finestra = ORDINE_FINESTRE.index(self.finestra) if self.finestra in ORDINE_FINESTRE else len(ORDINE_FINESTRE)
        media = ORDINE_MEDIA.index(self.tipo_media) if self.tipo_media in ORDINE_MEDIA else len(ORDINE_MEDIA)
        return (self.libera, finestra, media, self.ordine, self.codice)


def in_ordine(proiezioni):
    """Le proiezioni nell'ordine del passo 3 (vedi chiave_ordine)."""
    return sorted(proiezioni, key=lambda p: p.chiave_ordine())


class ImmagineRiferimento(models.Model):
    """Come deve apparire una proiezione: l'immagine ecografica, lo schema,
    la posizione della sonda, la misura. Da zero a quattro per voce; la
    prima (per `ordine`) e' quella grande nella riga, le altre miniature.
    Stanno sotto MEDIA_ROOT e passano da core.views_media, mai statiche."""

    proiezione = models.ForeignKey(ProiezioneCatalogo, on_delete=models.CASCADE, related_name='immagini')
    immagine = models.ImageField(upload_to='eco_riferimento/')
    didascalia = models.CharField(max_length=120, blank=True)
    ordine = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Immagine di riferimento'
        verbose_name_plural = 'Immagini di riferimento'
        ordering = ['proiezione', 'ordine', 'pk']

    def __str__(self):
        return f'{self.proiezione.codice} — {self.didascalia or self.immagine.name}'


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
