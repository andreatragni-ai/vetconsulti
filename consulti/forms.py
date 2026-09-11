import re
from decimal import Decimal

from django import forms

from accounts.models import Refertatore
from core.tipi import TipoEsame
from . import razze
from .models import Paziente, Richiesta, Sesso, Specie


def _bootstrap(form):
    for campo in form.fields.values():
        w = campo.widget
        # CheckboxSelectMultiple e RadioSelect NON discendono da Select:
        # senza questo ramo prendevano form-control e le caselle sparivano.
        if isinstance(w, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            w.attrs.setdefault('class', 'form-check-input')
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            w.attrs.setdefault('class', 'form-select')
        else:
            w.attrs.setdefault('class', 'form-control')


# ── Richiesta guidata: passo 1 (paziente) e passo 2 (esame ed esperto) ──────
# I form sono senza prefisso: un form per pagina. Il prefisso 'r' del vecchio
# form unico e' quello che faceva leggere sempre ECG come tipo di esame.

ETA_IN_ANNI = re.compile(r'^\s*(\d{1,2})\s*ann[oi]\s*$')

# Data di nascita scritta a mano: il campo e' di TESTO, non type="date",
# perche' Safari (Mac e iPad) mostra la data di oggi in grigio nel campo
# data vuoto e sembra gia' compilato. Si accettano 15/03/2019, 15-3-2019,
# 15.03.19, 15032019 e il formato ISO (2019-03-15: dati in sessione di
# prima e test). Il JS del passo 1 aggiunge le barre mentre si scrive.
FORMATI_DATA = ['%d/%m/%Y', '%d/%m/%y', '%d-%m-%Y', '%d-%m-%y', '%d.%m.%Y', '%d.%m.%y', '%d%m%Y', '%Y-%m-%d']


def _eta_testo(anni):
    return '1 anno' if anni == 1 else f'{anni} anni'


class PazienteForm(forms.ModelForm):
    """Solo nome, specie e sesso sono obbligatori. L'eta' si da' come data di
    nascita oppure come anni (in `eta_testo`, «8 anni»), non entrambe. La
    razza si sceglie dall'elenco della specie (consulti/razze.py) scrivendo
    per filtrare; una razza fuori elenco si accetta com'e'."""

    # Gli elenchi per il JS del campo razza: {{ form.elenchi_razze|json_script:... }}.
    elenchi_razze = razze.RAZZE

    specie = forms.ChoiceField(
        label='Specie', choices=Specie.choices, widget=forms.RadioSelect,
        error_messages={'required': 'Scegli la specie.', 'invalid_choice': 'Il portale referta cani e gatti: '
                                                                             'scegli una delle due specie.'})
    sesso = forms.ChoiceField(
        label='Sesso', choices=[('', 'Scegli...')] + list(Sesso.choices),
        error_messages={'required': 'Scegli il sesso (anche «Non noto»).'})
    eta_anni = forms.IntegerField(
        label='Eta\' in anni', required=False, min_value=0, max_value=40,
        widget=forms.NumberInput(attrs={'inputmode': 'numeric'}))
    data_nascita = forms.DateField(
        label='Data di nascita', required=False, input_formats=FORMATI_DATA,
        error_messages={'invalid': 'Scrivi la data come giorno/mese/anno, es. 15/03/2019.'},
        widget=forms.DateInput(format='%d/%m/%Y', attrs={
            'placeholder': 'gg/mm/aaaa', 'inputmode': 'numeric', 'autocomplete': 'off', 'maxlength': '10',
            'data-data-a-mano': ''}))
    peso_kg = forms.DecimalField(
        label='Peso (kg)', required=False, max_digits=5, decimal_places=2, min_value=Decimal('0.01'),
        localize=True, widget=forms.TextInput(attrs={'inputmode': 'decimal', 'placeholder': 'es. 12,5'}))

    class Meta:
        model = Paziente
        fields = ['nome', 'specie', 'razza', 'sesso', 'data_nascita', 'peso_kg', 'cognome_proprietario']
        labels = {
            'nome': 'Nome del paziente',
            'razza': 'Razza',
            'cognome_proprietario': 'Cognome del proprietario',
        }
        help_texts = {
            'cognome_proprietario': 'Basta il cognome: serve a te e al collega per riconoscere il caso, '
                                    'senza portare sul portale i dati del cliente.',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'autocomplete': 'off'}),
            # Combobox ARIA 1.2 (static/consulti/js/elenco_filtrato.js): l'elenco
            # e' quello della specie scelta, id dei dati e dei radio qui.
            'razza': forms.TextInput(attrs={
                'autocomplete': 'off', 'spellcheck': 'false', 'role': 'combobox', 'aria-autocomplete': 'list',
                'aria-expanded': 'false', 'aria-controls': 'razza-elenco', 'data-elenco-filtrato': 'razze-per-specie',
                'data-chiave-da': 'specie', 'data-avviso': 'razza-avviso'}),
        }
        error_messages = {'nome': {'required': 'Scrivi il nome del paziente.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        self.fields['specie'].widget.attrs['class'] = 'btn-check'
        self.fields['nome'].widget.attrs['autofocus'] = True
        if self.instance and self.instance.pk and not self.is_bound:
            corrisponde = ETA_IN_ANNI.match(self.instance.eta_testo or '')
            if corrisponde:
                self.initial['eta_anni'] = int(corrisponde.group(1))

    def clean_data_nascita(self):
        from datetime import date
        giorno = self.cleaned_data.get('data_nascita')
        if giorno and giorno > date.today():
            raise forms.ValidationError('La data di nascita e\' nel futuro.')
        return giorno

    def clean(self):
        dati = super().clean()
        if dati.get('data_nascita') and dati.get('eta_anni') is not None:
            self.add_error('eta_anni', 'Basta una delle due: la data di nascita oppure l\'eta\'.')
        # Scritta come nell'elenco della specie se c'e' («maine coon» -> «Maine Coon»), altrimenti com'e'.
        dati['razza'] = razze.normalizza(dati.get('specie'), dati.get('razza'))
        return dati

    def save(self, commit=True):
        paziente = super().save(commit=False)
        anni = self.cleaned_data.get('eta_anni')
        paziente.eta_testo = _eta_testo(anni) if anni is not None else ''
        if commit:
            paziente.save()
        return paziente


class EsameForm(forms.ModelForm):
    """Tipo di esame, esperto, urgenza e i testi per il collega. L'esperto
    si sceglie fra i referenti del tipo scelto; chi e' assente si vede ma non
    si sceglie."""

    tipo_esame = forms.ChoiceField(
        label='Tipo di esame', choices=TipoEsame.choices, widget=forms.RadioSelect,
        error_messages={'required': 'Scegli il tipo di esame.'})
    refertatore = forms.ModelChoiceField(
        label='Esperto', queryset=Refertatore.objects.none(),
        error_messages={'required': 'Scegli l\'esperto a cui mandare il caso.',
                        'invalid_choice': 'Questo esperto non referta il tipo di esame scelto: '
                                          'scegline uno dall\'elenco.'})

    class Meta:
        model = Richiesta
        fields = ['tipo_esame', 'refertatore', 'urgenza', 'quesito', 'anamnesi', 'terapia']
        labels = {
            'urgenza': 'Urgente',
            'quesito': 'Quesito per il collega',
            'anamnesi': 'Anamnesi',
            'terapia': 'Terapia in corso',
        }
        help_texts = {
            'urgenza': 'Il collega lo trova in cima alla sua lista; costa un supplemento (i prezzi qui sotto '
                       'si aggiornano).',
            'quesito': 'Cosa vuoi sapere. Es. «Aritmia all\'auscultazione prima di una TPLO: '
                       'e\' idoneo all\'anestesia?»',
            'anamnesi': 'Sintomi, visita, esami gia\' fatti. Facoltativa.',
            'terapia': 'Farmaci e dosi, se ne prende. Facoltativa.',
        }
        widgets = {
            'quesito': forms.Textarea(attrs={'rows': 3}),
            'anamnesi': forms.Textarea(attrs={'rows': 3}),
            'terapia': forms.Textarea(attrs={'rows': 2}),
        }
        error_messages = {'quesito': {'required': 'Scrivi il quesito: e\' la domanda a cui il collega risponde.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['quesito'].required = True
        _bootstrap(self)
        self.fields['tipo_esame'].widget.attrs['class'] = 'btn-check'
        self.fields['urgenza'].widget.attrs.update({'role': 'switch'})
        tipo = self.data.get('tipo_esame') if self.is_bound else None
        tipo = tipo or self.initial.get('tipo_esame') or getattr(self.instance, 'tipo_esame', None)
        self.fields['refertatore'].queryset = Refertatore.referenti_per(tipo) if tipo else Refertatore.objects.none()

    def clean_tipo_esame(self):
        tipo = self.cleaned_data['tipo_esame']
        richiesta = self.instance
        if richiesta.pk and tipo != richiesta.tipo_esame:
            quanti = richiesta.allegati.count()
            if quanti:
                raise forms.ValidationError(
                    f'Hai gia\' caricato {quanti} file per {richiesta.get_tipo_esame_display().lower()}: '
                    f'per cambiare tipo di esame rimuovili dal passo «Carica gli esami», '
                    f'oppure apri una nuova richiesta.')
        return tipo

    def clean_refertatore(self):
        refertatore = self.cleaned_data['refertatore']
        if refertatore is not None and not refertatore.disponibile_oggi:
            rientro = f' fino al {refertatore.assente_al:%d/%m/%Y}' if refertatore.assente_al else ''
            raise forms.ValidationError(f'{refertatore} e\' assente{rientro}: scegli un altro collega.')
        return refertatore


# ── Decisioni del refertatore ────────────────────────────────────────────────

class DeclinaForm(forms.Form):
    motivo = forms.CharField(
        label='Motivo', widget=forms.Textarea(attrs={'rows': 3}), max_length=1000,
        help_text='Lo legge il collega che ha chiesto: deve bastare per scegliere un altro esperto.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def clean_motivo(self):
        motivo = self.cleaned_data['motivo'].strip()
        if len(motivo) < 3:
            raise forms.ValidationError('Scrivi il motivo: lo legge chi ha chiesto.')
        return motivo


class NonRefertabileForm(forms.Form):
    voce = forms.ChoiceField(label='Perche\' non e\' refertabile')
    dettaglio = forms.CharField(
        label='Dettaglio', required=False, widget=forms.Textarea(attrs={'rows': 3}), max_length=1000,
        help_text='Cosa manca o cosa rifare: aiuta il collega a ripetere l\'esame.')

    def __init__(self, *args, tipo_esame=None, **kwargs):
        from .motivi import voci_non_refertabile
        super().__init__(*args, **kwargs)
        self.fields['voce'].choices = [('', '— scegli —')] + [(v, v) for v in voci_non_refertabile(tipo_esame)]
        _bootstrap(self)

    def clean(self):
        from .motivi import ALTRO, motivo_non_refertabile
        dati = super().clean()
        voce = dati.get('voce')
        if voce == ALTRO and not (dati.get('dettaglio') or '').strip():
            self.add_error('dettaglio', 'Con «Altro» serve una frase di spiegazione.')
        if voce:
            dati['motivo'] = motivo_non_refertabile(voce, dati.get('dettaglio'))
        return dati
