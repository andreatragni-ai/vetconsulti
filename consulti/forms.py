from django import forms

from accounts.models import Refertatore
from core.tipi import TipoEsame
from .models import Allegato, CategoriaAllegato, Paziente, Richiesta


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


class NuovaRichiestaForm(forms.ModelForm):
    tipo_esame = forms.ChoiceField(label='Tipo di esame', choices=TipoEsame.choices)
    refertatore = forms.ModelChoiceField(
        label='Esperto', queryset=Refertatore.objects.none(), required=False,
        help_text='Solo chi e\' referente per il tipo scelto.')

    class Meta:
        model = Richiesta
        fields = ['tipo_esame', 'refertatore', 'urgenza', 'motivo_esame', 'quesito', 'anamnesi', 'terapia']
        widgets = {
            'quesito': forms.Textarea(attrs={'rows': 3}),
            'anamnesi': forms.Textarea(attrs={'rows': 3}),
            'terapia': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        # htmx ricarica il select degli esperti quando cambia il tipo.
        self.fields['tipo_esame'].widget.attrs.update({
            'hx-get': '/consulti/esperti/', 'hx-target': '#esperti', 'hx-trigger': 'change'})
        # Il form vive con un prefisso ('r' in nuova_richiesta): la chiave nel
        # POST e' 'r-tipo_esame'. Leggendo 'tipo_esame' il tipo risultava sempre
        # ECG e un esperto dell'eco veniva rifiutato come scelta non valida.
        tipo = (self.data.get(self.add_prefix('tipo_esame'))
                or self.initial.get('tipo_esame') or TipoEsame.ECG)
        self.fields['refertatore'].queryset = Refertatore.referenti_per(tipo)


class PazienteForm(forms.ModelForm):
    class Meta:
        model = Paziente
        fields = ['nome', 'specie', 'specie_altro', 'razza', 'sesso', 'data_nascita', 'eta_testo',
                  'peso_kg', 'cognome_proprietario']
        widgets = {'data_nascita': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)


class AllegatoForm(forms.Form):
    categoria = forms.ChoiceField(label='Categoria', choices=CategoriaAllegato.choices)
    file = forms.FileField(label='File')

    def __init__(self, *args, tipo_esame=None, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)
        if tipo_esame:
            prefisso = {TipoEsame.ECG: 'ECG_', TipoEsame.HOLTER: 'HOLTER_', TipoEsame.ECO: 'ECO_'}[tipo_esame]
            self.fields['categoria'].choices = [
                (v, l) for v, l in CategoriaAllegato.choices if v.startswith(prefisso) or v == 'ALTRO']

    def clean_file(self):
        from django.conf import settings
        f = self.cleaned_data['file']
        if f.size > settings.ALLEGATO_MAX_BYTE:
            raise forms.ValidationError(
                f'Il file supera {settings.ALLEGATO_MAX_BYTE // (1024 * 1024)} MB: '
                f'usa il caricamento a pezzi.')
        return f


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
