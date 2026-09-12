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


# ── Smistamento automatico (eco/smistamento/) ────────────────────────────────

class StatoSmistamento(models.TextChoices):
    IN_CORSO = 'IN_CORSO', 'In corso'
    FATTO = 'FATTO', 'Fatto'
    ERRORE = 'ERRORE', 'Non riuscito'


class Smistamento(models.Model):
    """Un giro di smistamento automatico dei file di un'eco (formato, pixel,
    lettura AI, ordine di acquisizione). Gira in un thread dopo il commit; la
    pagina legge `stato` finche' non e' FATTO. `messaggio` e' la frase per chi
    carica (es. «lettura automatica non disponibile: smista a mano»);
    `telemetria` tiene token, durata, costo stimato e errori della lettura AI."""

    richiesta = models.ForeignKey(Richiesta, on_delete=models.CASCADE, related_name='smistamenti')
    stato = models.CharField(max_length=10, choices=StatoSmistamento.choices, default=StatoSmistamento.IN_CORSO)
    avviato_il = models.DateTimeField(auto_now_add=True)
    finito_il = models.DateTimeField(null=True, blank=True)
    avviato_da = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    n_file = models.PositiveIntegerField(default=0)
    modello = models.CharField(max_length=60, blank=True)
    lettura_ai = models.BooleanField(default=False, help_text='La lettura AI ha risposto per almeno un file.')
    messaggio = models.TextField(blank=True)
    telemetria = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Smistamento automatico'
        verbose_name_plural = 'Smistamenti automatici'
        ordering = ['-avviato_il', '-pk']

    def __str__(self):
        return f'{self.richiesta.codice} — {self.get_stato_display()} ({self.avviato_il:%d/%m/%Y %H:%M})'


class FonteProposta(models.TextChoices):
    DA_SMISTARE = '', 'Da smistare'
    FORMATO = 'FORMATO', 'Dal formato del file'
    AI = 'AI', 'Lettura automatica'
    ORDINE = 'ORDINE', 'Dall\'ordine di acquisizione'
    MANUALE = 'MANUALE', 'Scelta di chi carica'
    RIGA = 'RIGA', 'Caricato nella riga'


class PropostaSmistamento(models.Model):
    """Dove sta un file dell'eco sul «tavolo di smistamento»: una riga del
    catalogo, il referto dell'ecografo, o nessuna («da smistare»). E' una
    PROPOSTA: le ProiezioneCaricata (cio' che conta per inviare) nascono solo
    quando chi carica preme «Confermo lo smistamento» (eco/smistamento/
    tavolo.py:conferma). Una riga ha al piu' un file, un file al piu' una riga.

    `fonte` dice chi l'ha messo li': il formato (il PDF e' il referto), la
    lettura automatica, l'ordine di acquisizione, chi carica (spostandolo a
    mano) o il caricamento diretto nella riga. Uno smistamento automatico
    nuovo non tocca MANUALE e RIGA."""

    richiesta = models.ForeignKey(Richiesta, on_delete=models.CASCADE, related_name='proposte_smistamento')
    allegato = models.OneToOneField(Allegato, on_delete=models.CASCADE, related_name='proposta_smistamento')
    proiezione = models.ForeignKey(ProiezioneCatalogo, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    referto = models.BooleanField(default=False, help_text='Proposto come referto dell\'ecografo (PDF).')
    nota = models.CharField(max_length=200, blank=True, help_text='Per i filmati liberi: cosa mostra / cosa chiedi.')
    fonte = models.CharField(max_length=10, choices=FonteProposta.choices, default=FonteProposta.DA_SMISTARE,
                             blank=True)
    confidenza = models.FloatField(null=True, blank=True)
    sicura = models.BooleanField(default=False)
    motivo = models.CharField(max_length=300, blank=True)
    seconda_scelta = models.ForeignKey(ProiezioneCatalogo, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    tracciato = models.CharField(max_length=20, blank=True, help_text='Tipo di tracciato letto dalla AI.')
    colore = models.CharField(max_length=10, blank=True, help_text='color / bmode / incerto, dai pixel.')
    percorso_originale = models.CharField(max_length=500, blank=True,
                                          help_text='Percorso nella cartella caricata (ordine di acquisizione).')
    modificato_il = models.BigIntegerField(null=True, blank=True,
                                           help_text='Data di modifica del file (ms), dal browser.')
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Proposta di smistamento'
        verbose_name_plural = 'Proposte di smistamento'
        constraints = [
            models.UniqueConstraint(fields=['richiesta', 'proiezione'], condition=models.Q(proiezione__isnull=False),
                                    name='una_proposta_per_riga'),
        ]

    def __str__(self):
        dove = self.proiezione.codice if self.proiezione_id else ('referto' if self.referto else 'da smistare')
        return f'{self.richiesta.codice} — {self.allegato.nome_originale} → {dove}'

    @property
    def da_smistare(self):
        return self.proiezione_id is None and not self.referto


class EsitoSmistamento(models.Model):
    """Cosa aveva proposto lo smistamento automatico e cosa ha confermato
    l'umano, per un file di un esame vero.

    ## Perche' esiste

    Il banco di prova di `manage.py valuta_smistamento` e' fatto con le
    immagini di riferimento del catalogo, che vengono da una presentazione:
    sono piu' pulite e meglio intitolate dei file di un esame vero. La
    domanda di Andre — «con file veri, senza un'intestazione coerente,
    quanti ne prende?» — a quel banco non si puo' chiedere.

    Ma ogni «Confermo lo smistamento» e' **una correzione umana**, cioe' la
    verita': chi ha caricato i file sa dove vanno. Qui si tiene traccia
    della proposta e della conferma, e `manage.py accuratezza_smistamento`
    legge questa tabella.

    ## Sopravvivenza

    Le PropostaSmistamento vengono consumate (uno spostamento a mano
    riscrive `fonte` e `proiezione`, e la conferma successiva le supera):
    per questo la **proposta si fotografa qui appena lo smistamento
    finisce** (eco/smistamento/esiti.py), e la conferma riempie i campi
    `finale_*`. Una riga per file e per richiesta: un secondo giro di
    smistamento la riscrive, una seconda conferma aggiorna l'esito.

    ## Niente dati del paziente

    Solo identificativi interni (codice della richiesta, id dell'allegato) e
    codici del catalogo: niente nomi, niente file, niente testo del caso.
    """

    richiesta = models.ForeignKey(Richiesta, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='esiti_smistamento')
    codice_richiesta = models.CharField(max_length=15, blank=True,
                                        help_text='Identificativo interno del caso: resta se la richiesta sparisce.')
    smistamento = models.ForeignKey(Smistamento, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='esiti')
    # Non e' una chiave esterna: cosi' l'esito resta anche se il file sparisce.
    allegato_interno = models.BigIntegerField(help_text='id interno dell\'allegato.')
    modello = models.CharField(max_length=60, blank=True)
    # ── Cosa proponeva lo smistamento automatico ──
    proposta = models.CharField(max_length=30, blank=True, help_text='Codice della riga proposta; vuoto = nessuna.')
    proposta_referto = models.BooleanField(default=False)
    fonte = models.CharField(max_length=10, blank=True, help_text='FORMATO / AI / ORDINE (FonteProposta).')
    confidenza = models.FloatField(null=True, blank=True)
    sicura = models.BooleanField(default=False)
    tracciato = models.CharField(max_length=20, blank=True, help_text='Tipo di tracciato letto dalla AI.')
    seconda_scelta = models.CharField(max_length=30, blank=True)
    proposto_il = models.DateTimeField(auto_now_add=True)
    # ── Cosa ha confermato l'umano ──
    confermato_il = models.DateTimeField(null=True, blank=True)
    finale = models.CharField(max_length=30, blank=True, help_text='Codice della riga confermata; vuoto = nessuna.')
    finale_referto = models.BooleanField(default=False)
    corretto = models.BooleanField(default=False, help_text='L\'umano ha spostato il file altrove.')

    class Meta:
        verbose_name = 'Esito dello smistamento'
        verbose_name_plural = 'Esiti dello smistamento'
        ordering = ['-proposto_il', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['richiesta', 'allegato_interno'], name='un_esito_per_file'),
        ]

    def __str__(self):
        return f'{self.codice_richiesta} — {self.proposta or "nessuna"} -> {self.finale or "nessuna"}'

    @property
    def confermato(self):
        return self.confermato_il is not None

    @property
    def dove_proponeva(self):
        """La destinazione proposta in una parola sola, per i conti."""
        return self.proposta or ('referto' if self.proposta_referto else '')

    @property
    def dove_e_finito(self):
        return self.finale or ('referto' if self.finale_referto else '')
