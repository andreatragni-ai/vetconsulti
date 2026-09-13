"""Form dell'app accounts. Le validazioni fiscali stanno nel modello
(DatiFatturazione.clean), cosi' valgono anche fuori dal form."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.html import format_html

from core.tipi import TipoEsame
from . import fiscale
from .models import (Clinica, CompetenzaRefertatore, DatiFatturazione, Refertatore, RegimeIva,
                     Richiedente, RuoloRichiedente, TipoRichiedente)

User = get_user_model()


def _bootstrap(form):
    """Classi Bootstrap sui widget senza ripeterle campo per campo."""
    for nome, campo in form.fields.items():
        w = campo.widget
        # CheckboxSelectMultiple e RadioSelect NON discendono da Select:
        # senza questo ramo prendevano form-control e le caselle sparivano.
        if isinstance(w, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            w.attrs.setdefault('class', 'form-check-input')
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            w.attrs.setdefault('class', 'form-select')
        else:
            w.attrs.setdefault('class', 'form-control')


# I campi che dicono «l'utente ha deciso di compilare la fatturazione», e
# quindi che il blocco va validato invece di essere rimandato al profilo.
# Fuori restano i tre che arrivano compilati senza che nessuno li tocchi:
# `codice_sdi` e `regime_iva` hanno un valore iniziale, e `intestatario` lo
# scrive il JavaScript della pagina appena si digita nome e cognome. Contarli
# renderebbe il blocco «compilato» sempre, e saltarlo impossibile.
CAMPI_FATTURAZIONE_DIGITATI = ('partita_iva', 'codice_fiscale', 'indirizzo_sede', 'cap',
                               'comune', 'provincia', 'pec_fatturazione')


class RegistrazioneForm(UserCreationForm):
    """Registrazione di un richiedente: account, dati professionali e —
    se li ha sotto mano — la fatturazione.

    Il tipo arriva dal primo passo (URL), non da un campo: per una clinica si
    sceglie fra quelle esistenti oppure se ne propone una nuova (che nasce
    non approvata); per un libero professionista la clinica non c'e' e
    l'approvazione e' sul richiedente. Con un invito (`clinica_invito`) la
    clinica e' decisa dal link e i suoi campi non compaiono.

    ## Il blocco fiscale si puo' saltare (decisione del 12/09/2026)

    Chiedere P.IVA, SDI e PEC a chi sta solo aprendo un account allunga
    l'iscrizione e fa abbandonare chi non ha i dati a portata di mano. Ora
    il blocco lasciato del tutto vuoto vale «dopo»: `dati_fatturazione`
    resta None e l'invio della prima richiesta e' bloccato da
    `Richiedente.puo_richiedere` (consulti.regole), che rimanda al profilo.
    Compilato a meta', invece, si valida subito con le stesse regole di
    DatiFatturazione (clean() del modello, che usa accounts/fiscale.py):
    meglio un errore adesso che una fattura sbagliata fra un mese.
    """

    first_name = forms.CharField(label='Nome', max_length=150)
    last_name = forms.CharField(label='Cognome', max_length=150)
    email = forms.EmailField(label='Email')
    telefono = forms.CharField(label='Telefono', max_length=30, required=False)
    ruolo = forms.ChoiceField(label='Ruolo', choices=RuoloRichiedente.choices)
    numero_iscrizione = forms.CharField(
        label='N. iscrizione all\'Ordine', max_length=30, required=False,
        help_text='Se sei iscritto. Un tecnico puo\' lasciarlo vuoto.')
    ordine_provinciale = forms.CharField(label='Ordine provinciale', max_length=100, required=False)
    clinica = forms.ModelChoiceField(
        label='Clinica', queryset=Clinica.objects.filter(approvata=True), required=False,
        empty_label='— nuova clinica (compila sotto) —')
    nuova_clinica = forms.CharField(label='Denominazione nuova clinica', max_length=200, required=False)
    nuova_clinica_comune = forms.CharField(label='Comune', max_length=100, required=False)
    nuova_clinica_provincia = forms.CharField(label='Provincia', max_length=2, required=False)

    # Fatturazione elettronica
    intestatario = forms.CharField(
        label='Intestatario della fattura', max_length=200, required=False,
        help_text='Se vuoto: nome e cognome per il libero professionista, denominazione per la clinica.')
    partita_iva = forms.CharField(label='Partita IVA', max_length=11, required=False)
    codice_fiscale = forms.CharField(label='Codice fiscale', max_length=16, required=False)
    indirizzo_sede = forms.CharField(label='Indirizzo della sede', max_length=200, required=False)
    cap = forms.CharField(label='CAP', max_length=5, required=False)
    comune = forms.CharField(label='Comune', max_length=100, required=False)
    provincia = forms.CharField(label='Provincia', max_length=2, required=False)
    codice_sdi = forms.CharField(
        label='Codice destinatario SDI', max_length=7, required=False, initial=fiscale.SDI_NULLO,
        help_text='7 caratteri. Lascia 0000000 se ricevi le fatture via PEC.')
    pec_fatturazione = forms.EmailField(label='PEC per la fattura', required=False)
    regime_iva = forms.ChoiceField(label='Regime IVA', choices=RegimeIva.choices, initial=RegimeIva.ORDINARIO)

    accetto_privacy = forms.BooleanField()
    accetto_termini = forms.BooleanField()

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')

    def __init__(self, *args, tipo=TipoRichiedente.CLINICA, clinica_invito=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = tipo
        # Con un invito la clinica e' quella del link: i campi per scegliere o
        # proporne una non compaiono, cosi' il collega non puo' finire per
        # sbaglio in un'altra struttura (ne' crearne un doppione).
        self.clinica_invito = clinica_invito
        if tipo == TipoRichiedente.LIBERO_PROFESSIONISTA or clinica_invito is not None:
            for nome in ('clinica', 'nuova_clinica', 'nuova_clinica_comune', 'nuova_clinica_provincia'):
                self.fields.pop(nome, None)
            # Il ruolo piu' probabile, non un obbligo: il numero e l'Ordine
            # restano facoltativi anche qui (decisione del 12/09). Chi carica
            # gli esami puo' essere un tecnico, che all'Ordine non e' iscritto,
            # e il referto lo firma comunque il veterinario che lo supervisiona.
            self.fields['ruolo'].initial = RuoloRichiedente.VETERINARIO
        # Le label delle caselle portano ai testi, in una scheda nuova: chi
        # si registra deve poterli leggere senza perdere il form compilato.
        self.fields['accetto_privacy'].label = format_html(
            'Ho letto l\'<a href="{}" target="_blank" rel="noopener">informativa privacy</a>',
            reverse_lazy('core:privacy'))
        self.fields['accetto_termini'].label = format_html(
            'Accetto i <a href="{}" target="_blank" rel="noopener">termini del servizio</a>',
            reverse_lazy('core:termini'))
        _bootstrap(self)

    @property
    def e_libero_professionista(self):
        return self.tipo == TipoRichiedente.LIBERO_PROFESSIONISTA

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Esiste gia\' un account con questa email.')
        return email

    def _fatturazione_compilata(self, dati):
        return any((dati.get(c) or '').strip() for c in CAMPI_FATTURAZIONE_DIGITATI)

    def clean(self):
        dati = super().clean()
        clinica = None
        if not self.e_libero_professionista:
            clinica = self.clinica_invito or dati.get('clinica')
            if self.clinica_invito is None and not clinica and not dati.get('nuova_clinica'):
                self.add_error('clinica', 'Scegli una clinica o indicane una nuova.')

        # Blocco vuoto = «dopo, dal profilo»: si decide PRIMA di proporre
        # l'intestatario, altrimenti il default farebbe sembrare compilato un
        # blocco vuoto e l'iscrizione si fermerebbe sui campi dell'indirizzo.
        if not self._fatturazione_compilata(dati):
            self.dati_fatturazione = None
            return dati

        # Intestatario di default, se non indicato.
        if not (dati.get('intestatario') or '').strip():
            if self.e_libero_professionista:
                dati['intestatario'] = f"{dati.get('first_name', '')} {dati.get('last_name', '')}".strip()
            elif clinica is not None:
                dati['intestatario'] = clinica.denominazione
            else:
                dati['intestatario'] = (dati.get('nuova_clinica') or '').strip()

        for campo in ('indirizzo_sede', 'cap', 'comune', 'provincia'):
            if not (dati.get(campo) or '').strip():
                self.add_error(campo, 'Campo obbligatorio per la fatturazione.')
        istanza = DatiFatturazione(
            intestatario=dati.get('intestatario', ''),
            partita_iva=dati.get('partita_iva', ''), codice_fiscale=dati.get('codice_fiscale', ''),
            indirizzo_sede=dati.get('indirizzo_sede', ''), cap=dati.get('cap', ''),
            comune=dati.get('comune', ''), provincia=(dati.get('provincia') or '').upper(),
            codice_sdi=dati.get('codice_sdi') or fiscale.SDI_NULLO,
            pec_fatturazione=dati.get('pec_fatturazione', ''),
            regime_iva=dati.get('regime_iva') or RegimeIva.ORDINARIO, predefinita=True)
        try:
            istanza.clean()
        except ValidationError as e:
            for campo, errori in e.error_dict.items():
                for errore in errori:
                    self.add_error(campo if campo in self.fields else None, errore)
        self.dati_fatturazione = istanza
        return dati


class RichiedenteForm(forms.ModelForm):
    class Meta:
        model = Richiedente
        fields = ['telefono', 'ruolo', 'numero_iscrizione', 'ordine_provinciale']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class ClinicaForm(forms.ModelForm):
    class Meta:
        model = Clinica
        fields = ['denominazione', 'indirizzo', 'cap', 'comune', 'provincia', 'telefono', 'email', 'pec']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class DatiFatturazioneForm(forms.ModelForm):
    class Meta:
        model = DatiFatturazione
        fields = ['intestatario', 'partita_iva', 'codice_fiscale', 'indirizzo_sede', 'cap',
                  'comune', 'provincia', 'nazione', 'codice_sdi', 'pec_fatturazione',
                  'regime_iva', 'split_payment', 'note']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class FotoInput(forms.ClearableFileInput):
    """Il campo foto dell'esperto: l'anteprima dalla consegna protetta
    (Refertatore.url_foto) al posto del link «Attualmente» di Django, che
    punterebbe a /media/, mai servito. Lo usano il profilo e l'admin."""

    template_name = 'accounts/_widget_foto.html'
    clear_checkbox_label = 'Togli la foto'


class RefertatoreProfiloForm(forms.ModelForm):
    class Meta:
        model = Refertatore
        fields = ['titolo', 'specializzazione', 'numero_iscrizione', 'ordine_provinciale',
                  'foto', 'firma', 'assente_dal', 'assente_al', 'messaggio']
        labels = {'foto': 'Foto'}
        help_texts = {'foto': 'La vedono i colleghi quando scelgono a chi mandare il caso. JPG o PNG.'}
        widgets = {
            'foto': FotoInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
            'assente_dal': forms.DateInput(attrs={'type': 'date'}),
            'assente_al': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class CompetenzaForm(forms.ModelForm):
    class Meta:
        model = CompetenzaRefertatore
        fields = ['tipo_esame', 'referente', 'prezzo_personalizzato', 'tempo_risposta_ore', 'accetta_urgenze']
        widgets = {'tipo_esame': forms.HiddenInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


def competenze_complete(refertatore):
    """Garantisce una riga per ogni tipo di esame, cosi' il profilo mostra
    sempre tre righe e non serve un bottone «aggiungi»."""
    for tipo in TipoEsame.values:
        CompetenzaRefertatore.objects.get_or_create(refertatore=refertatore, tipo_esame=tipo)
    return refertatore.competenze.order_by('tipo_esame')


class NuovoRefertatoreForm(forms.Form):
    """Usato dall'admin per creare User + Refertatore e mandare l'invito."""

    username = forms.CharField(label='Username', max_length=150)
    first_name = forms.CharField(label='Nome', max_length=150)
    last_name = forms.CharField(label='Cognome', max_length=150)
    email = forms.EmailField(label='Email')
    titolo = forms.CharField(label='Titolo', max_length=50, required=False, initial='Dott.')
    specializzazione = forms.CharField(label='Specializzazione', max_length=200, required=False)
    numero_iscrizione = forms.CharField(label='N. iscrizione', max_length=30, required=False)
    ordine_provinciale = forms.CharField(label='Ordine provinciale', max_length=100, required=False)
    tipi_referente = forms.MultipleChoiceField(
        label='Referente per', choices=TipoEsame.choices, required=False,
        widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def clean_username(self):
        u = self.cleaned_data['username']
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError('Username gia\' in uso.')
        return u

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Esiste gia\' un account con questa email.')
        return email
