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
        tipo = self.data.get('tipo_esame') or self.initial.get('tipo_esame') or TipoEsame.ECG
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
