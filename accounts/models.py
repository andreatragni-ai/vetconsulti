"""
Profili del portale: chi referta, chi chiede, e i dati per fatturare.

## Due profili, un solo User

Un veterinario puo' essere sia refertatore sia richiedente (chiede un
consulto a un collega su un caso che non e' il suo campo). Per questo
Refertatore e Richiedente sono due OneToOne separati sullo stesso User e
non un campo `ruolo`: la navbar guarda quali dei due esistono.

## Chi chiede: una clinica o un singolo veterinario

Un Richiedente e' di tipo CLINICA (lavora per una struttura, che e' anche
l'intestatario della fattura) oppure LIBERO_PROFESSIONISTA (cardiologo o
veterinario senza struttura, che si fa fatturare a proprio nome). I dati di
fatturazione stanno quindi o sulla Clinica o sul Richiedente — mai su
entrambi, mai su nessuno dei due se si vuole inviare una richiesta. Lo
stesso vale per l'approvazione dell'admin: sulla clinica per il tipo
CLINICA, sul richiedente per il libero professionista.

Modello dati, in breve:

    User 1─1 Refertatore ──* CompetenzaRefertatore
         │       └─? DatiFatturazione (se emette in proprio)
         1─1 Richiedente ──? Clinica ──* DatiFatturazione
                  └──* DatiFatturazione (solo LIBERO_PROFESSIONISTA)
         ──* Consenso

## Chi emette la fattura

Ogni refertatore dichiara se le sue prestazioni le fattura la societa'
oppure lui stesso (`soggetto_emittente`). Il registro copia questo valore
nella Prestazione al momento della firma: se il refertatore cambia regime
il mese dopo, le prestazioni gia' fatte restano com'erano.
"""

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.tipi import TipoEsame
from . import fiscale


class Clinica(models.Model):
    """La struttura da cui parte una richiesta.

    `approvata` parte a False: la prima richiesta di una clinica mai vista
    aspetta l'ok dell'admin. Non e' burocrazia: e' l'unico momento in cui
    qualcuno guarda che la struttura esista davvero prima che le si mandi un
    referto firmato e una fattura.
    """

    denominazione = models.CharField(max_length=200)
    indirizzo = models.CharField(max_length=200, blank=True)
    cap = models.CharField(max_length=5, blank=True)
    comune = models.CharField(max_length=100, blank=True)
    provincia = models.CharField(max_length=2, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    pec = models.EmailField(blank=True)
    approvata = models.BooleanField(
        default=False, db_index=True,
        help_text='Finche\' non e\' approvata, le sue richieste non partono.')
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Clinica'
        verbose_name_plural = 'Cliniche'
        ordering = ['denominazione']

    def __str__(self):
        luogo = f' ({self.comune})' if self.comune else ''
        return f'{self.denominazione}{luogo}'

    @property
    def dati_fatturazione_predefiniti(self):
        return self.dati_fatturazione.filter(predefinita=True).first()


class RegimeIva(models.TextChoices):
    ORDINARIO = 'ORDINARIO', 'Ordinario'
    FORFETTARIO = 'FORFETTARIO', 'Forfettario (art. 1 c. 54-89 L. 190/2014)'
    ESENTE = 'ESENTE', 'Esente / non imponibile'


class DatiFatturazione(models.Model):
    """Intestazione fiscale di una fattura.

    Appartiene a UN soggetto: una Clinica, oppure un Richiedente libero
    professionista. Con entrambe le FK nulle sono i dati di un refertatore
    che emette in proprio (collegato da Refertatore.dati_fatturazione); un
    refertatore che chiede anche consulti riusa la stessa riga impostando
    `richiedente`, senza duplicarla. Le validazioni stanno in clean() e non
    in save() perche' devono arrivare al form come errori di campo; chi
    salva da shell le puo' scavalcare, e se lo fa e' un problema suo — il
    CheckConstraint sul database lo ferma comunque se prova a mettere due
    soggetti.
    """

    clinica = models.ForeignKey(
        Clinica, on_delete=models.CASCADE, null=True, blank=True,
        related_name='dati_fatturazione')
    richiedente = models.ForeignKey(
        'Richiedente', on_delete=models.CASCADE, null=True, blank=True,
        related_name='dati_fatturazione',
        help_text='Solo per un libero professionista che si fa fatturare a proprio nome.')
    intestatario = models.CharField(max_length=200)
    partita_iva = models.CharField(max_length=11, blank=True)
    codice_fiscale = models.CharField(max_length=16, blank=True)
    indirizzo_sede = models.CharField(max_length=200)
    cap = models.CharField(max_length=5)
    comune = models.CharField(max_length=100)
    provincia = models.CharField(max_length=2)
    nazione = models.CharField(max_length=2, default='IT')
    codice_sdi = models.CharField(
        max_length=7, default=fiscale.SDI_NULLO,
        verbose_name='Codice destinatario SDI')
    pec_fatturazione = models.EmailField(blank=True)
    regime_iva = models.CharField(
        max_length=20, choices=RegimeIva.choices, default=RegimeIva.ORDINARIO)
    split_payment = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    predefinita = models.BooleanField(
        default=False,
        help_text='Usata per le nuove richieste. Una sola per clinica.')
    aggiornata_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dati di fatturazione'
        verbose_name_plural = 'Dati di fatturazione'
        constraints = [
            # Un soggetto solo: clinica O richiedente, mai entrambi.
            models.CheckConstraint(
                condition=models.Q(clinica__isnull=True) | models.Q(richiedente__isnull=True),
                name='dati_fatturazione_un_solo_soggetto'),
            # Una sola predefinita per soggetto: se ce ne fossero due, la
            # richiesta ne prenderebbe una a caso.
            models.UniqueConstraint(
                fields=['clinica'], condition=models.Q(predefinita=True),
                name='una_sola_predefinita_per_clinica'),
            models.UniqueConstraint(
                fields=['richiedente'], condition=models.Q(predefinita=True),
                name='una_sola_predefinita_per_richiedente'),
        ]

    def __str__(self):
        return f'{self.intestatario} — P.IVA {self.partita_iva or "n.d."}'

    def clean(self):
        errori = {}
        if self.clinica_id and self.richiedente_id:
            errori['richiedente'] = 'I dati appartengono o a una clinica o a un richiedente, non a entrambi.'
        if self.partita_iva:
            try:
                self.partita_iva = fiscale.valida_partita_iva(self.partita_iva)
            except ValueError as e:
                errori['partita_iva'] = str(e)
        if self.codice_fiscale:
            try:
                self.codice_fiscale = fiscale.valida_codice_fiscale(self.codice_fiscale)
            except ValueError as e:
                errori['codice_fiscale'] = str(e)
        if not self.partita_iva and not self.codice_fiscale:
            errori['partita_iva'] = 'Serve almeno uno fra partita IVA e codice fiscale.'
        try:
            self.codice_sdi = fiscale.valida_codice_sdi(self.codice_sdi)
        except ValueError as e:
            errori['codice_sdi'] = str(e)
        if 'codice_sdi' not in errori and not fiscale.recapito_fattura_valido(
                self.codice_sdi, self.pec_fatturazione):
            errori['pec_fatturazione'] = (
                'Con codice SDI 0000000 serve una PEC per la fattura elettronica.')
        if errori:
            raise ValidationError(errori)

    @property
    def valida(self):
        """True se passa le stesse regole del form: la usa Richiedente.puo_richiedere."""
        try:
            self.clean()
        except ValidationError:
            return False
        return True


class SoggettoEmittente(models.TextChoices):
    SOCIETA = 'SOCIETA', 'La societa\' (VetWay)'
    REFERTATORE = 'REFERTATORE', 'Il refertatore in proprio'


class Refertatore(models.Model):
    """Chi firma i referti.

    ## L'assenza si mostra, non si nasconde

    Un refertatore in ferie che sparisce dall'elenco lascia il collega a
    chiedersi se ha sbagliato pagina; uno che compare con «assente fino al
    24» ha risposto a una domanda prima che venisse posta. `assente_al` e'
    una data e `disponibile_oggi` la confronta con oggi: nessun job notturno
    che rimette attivi i rientrati, perche' un job cosi' si rompe in silenzio.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='refertatore')
    titolo = models.CharField(max_length=50, blank=True, help_text='Es. Dott., Dott.ssa, Prof.')
    specializzazione = models.CharField(max_length=200, blank=True)
    numero_iscrizione = models.CharField(max_length=30, blank=True)
    ordine_provinciale = models.CharField(max_length=100, blank=True)
    firma = models.ImageField(upload_to='firme/', blank=True, null=True)
    attivo = models.BooleanField(default=True, db_index=True)
    assente_dal = models.DateField(null=True, blank=True)
    assente_al = models.DateField(null=True, blank=True)
    messaggio = models.CharField(
        max_length=200, blank=True,
        help_text='Compare accanto al nome nell\'elenco. Es. tempi di risposta.')
    soggetto_emittente = models.CharField(
        max_length=20, choices=SoggettoEmittente.choices, default=SoggettoEmittente.SOCIETA,
        help_text='Chi emette la fattura per le sue prestazioni.')
    dati_fatturazione = models.ForeignKey(
        DatiFatturazione, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='refertatori',
        help_text='Necessari solo se emette in proprio.')
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Refertatore'
        verbose_name_plural = 'Refertatori'
        ordering = ['user__last_name', 'user__first_name']

    def __str__(self):
        return self.nome_completo

    @property
    def nome_completo(self):
        nome = self.user.get_full_name() or self.user.username
        return f'{self.titolo} {nome}'.strip()

    def clean(self):
        if self.assente_dal and self.assente_al and self.assente_al < self.assente_dal:
            raise ValidationError({'assente_al': 'La fine dell\'assenza viene prima dell\'inizio.'})
        if self.soggetto_emittente == SoggettoEmittente.REFERTATORE and not self.dati_fatturazione_id:
            raise ValidationError(
                {'dati_fatturazione': 'Chi emette in proprio deve indicare i propri dati di fatturazione.'})

    def assente_il(self, giorno=None):
        """Estremi inclusi: «assente dal 3 al 24» vuol dire che il 24 e' ancora assente."""
        giorno = giorno or date.today()
        if not (self.assente_dal or self.assente_al):
            return False
        if self.assente_dal and giorno < self.assente_dal:
            return False
        if self.assente_al and giorno > self.assente_al:
            return False
        return True

    @property
    def disponibile_oggi(self):
        return self.attivo and not self.assente_il()

    def competenza_per(self, tipo_esame):
        return self.competenze.filter(tipo_esame=tipo_esame).first()

    def referta(self, tipo_esame):
        """True se e' referente attivo per quel tipo."""
        return self.attivo and self.competenze.filter(tipo_esame=tipo_esame, referente=True).exists()

    @classmethod
    def referenti_per(cls, tipo_esame):
        """Refertatori attivi e referenti per un tipo di esame, ordinati per nome.

        Non filtra l'assenza: l'elenco mostra anche chi e' assente, con la
        data di rientro, perche' il collega possa scegliere se aspettarlo.
        """
        return (cls.objects.filter(attivo=True, competenze__tipo_esame=tipo_esame,
                                   competenze__referente=True)
                .select_related('user').distinct())


class CompetenzaRefertatore(models.Model):
    """Cosa referta un refertatore e a che condizioni.

    `referente` = compare nell'elenco per quel tipo. `prezzo_personalizzato`
    scavalca il listino (listino.prezzo_effettivo lo dice nell'origine).
    `tempo_risposta_ore` e' una promessa mostrata accanto al nome, non un SLA
    che il sistema fa rispettare.
    """

    refertatore = models.ForeignKey(
        Refertatore, on_delete=models.CASCADE, related_name='competenze')
    tipo_esame = models.CharField(max_length=10, choices=TipoEsame.choices)
    referente = models.BooleanField(default=False)
    prezzo_personalizzato = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text='Imponibile. Vuoto = listino.')
    tempo_risposta_ore = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Competenza refertatore'
        verbose_name_plural = 'Competenze refertatori'
        unique_together = [('refertatore', 'tipo_esame')]
        ordering = ['refertatore', 'tipo_esame']

    def __str__(self):
        stato = 'referente' if self.referente else 'non referente'
        return f'{self.refertatore} — {self.get_tipo_esame_display()} ({stato})'


class RuoloRichiedente(models.TextChoices):
    VETERINARIO = 'VETERINARIO', 'Medico veterinario'
    TECNICO = 'TECNICO', 'Tecnico veterinario'


class TipoRichiedente(models.TextChoices):
    CLINICA = 'CLINICA', 'Clinica / struttura veterinaria'
    LIBERO_PROFESSIONISTA = 'LIBERO_PROFESSIONISTA', 'Libero professionista'


class Richiedente(models.Model):
    """Chi chiede un consulto: per conto di una clinica o a proprio nome.

    `approvato` conta solo per il libero professionista: per una clinica
    l'approvazione sta sulla Clinica (una struttura, tanti richiedenti).
    `approvazione_ok()` nasconde questa differenza a chi deve solo sapere se
    la richiesta puo' partire.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='richiedente')
    tipo = models.CharField(
        max_length=25, choices=TipoRichiedente.choices, default=TipoRichiedente.CLINICA, db_index=True)
    clinica = models.ForeignKey(
        Clinica, on_delete=models.PROTECT, null=True, blank=True, related_name='richiedenti',
        help_text='Obbligatoria per il tipo CLINICA.')
    approvato = models.BooleanField(
        default=False, db_index=True,
        help_text='Solo per il libero professionista: finche\' non e\' approvato, le sue richieste non partono.')
    telefono = models.CharField(max_length=30, blank=True)
    numero_iscrizione = models.CharField(max_length=30, blank=True)
    ordine_provinciale = models.CharField(max_length=100, blank=True)
    ruolo = models.CharField(
        max_length=20, choices=RuoloRichiedente.choices, default=RuoloRichiedente.VETERINARIO)
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Richiedente'
        verbose_name_plural = 'Richiedenti'
        ordering = ['user__last_name', 'user__first_name']

    def __str__(self):
        if self.tipo == TipoRichiedente.CLINICA:
            return f'{self.denominazione} — {self.clinica or "senza clinica"}'
        return f'{self.denominazione} — libero professionista'

    def clean(self):
        if self.tipo == TipoRichiedente.CLINICA and not self.clinica_id:
            raise ValidationError({'clinica': 'Un richiedente di tipo clinica deve indicare la clinica.'})

    # ── Intestazione ────────────────────────────────────────────────

    @property
    def denominazione(self):
        """Stesso nome dell'attributo di Clinica: cosi' chi ha in mano un
        intestatario non deve sapere se e' una struttura o una persona."""
        return self.user.get_full_name() or self.user.username

    @property
    def email(self):
        return self.user.email

    @property
    def e_libero_professionista(self):
        return self.tipo == TipoRichiedente.LIBERO_PROFESSIONISTA

    @property
    def soggetto_fatturazione(self):
        """A chi si intesta la fattura: la clinica, oppure il richiedente stesso."""
        return self.clinica if self.tipo == TipoRichiedente.CLINICA else self

    @property
    def dati_fatturazione_predefiniti(self):
        soggetto = self.soggetto_fatturazione
        if soggetto is None:
            return None
        return soggetto.dati_fatturazione.filter(predefinita=True).first()

    def approvazione_ok(self):
        """Approvato dall'admin: la clinica se c'e', altrimenti il richiedente."""
        if self.tipo == TipoRichiedente.CLINICA:
            return bool(self.clinica_id and self.clinica.approvata)
        return self.approvato

    @property
    def puo_richiedere(self):
        """Ha dati di fatturazione predefiniti e validi sul soggetto giusto.

        Non si guarda l'approvazione: blocca l'invio (consulti.regole), non
        la compilazione della bozza.
        """
        dati = self.dati_fatturazione_predefiniti
        return bool(dati and dati.valida)


class TipoConsenso(models.TextChoices):
    PRIVACY = 'PRIVACY', 'Informativa privacy'
    TERMINI = 'TERMINI', 'Termini del servizio'


class Consenso(models.Model):
    """Traccia di cosa ha accettato l'utente e quando.

    Una riga per (utente, tipo, versione): se cambia la versione
    dell'informativa si registra un nuovo consenso, il vecchio resta.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='consensi')
    tipo = models.CharField(max_length=10, choices=TipoConsenso.choices)
    versione = models.CharField(max_length=20)
    accettato_il = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Consenso'
        verbose_name_plural = 'Consensi'
        unique_together = [('user', 'tipo', 'versione')]
        ordering = ['-accettato_il']

    def __str__(self):
        return f'{self.user} — {self.get_tipo_display()} v{self.versione}'


def versione_consenso(tipo):
    """Versione corrente del testo: vive in settings (VERSIONE_PRIVACY /
    VERSIONE_TERMINI) accanto ai template, cosi' chi cambia il testo cambia
    anche la data e il consenso viene richiesto di nuovo."""
    return {
        TipoConsenso.PRIVACY: settings.VERSIONE_PRIVACY,
        TipoConsenso.TERMINI: settings.VERSIONE_TERMINI,
    }[tipo]
