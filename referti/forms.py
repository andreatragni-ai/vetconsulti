"""Il form della copia di lavoro del referto: le tre caselle comuni, le voci
del blocco del tipo di esame (in `classificazione`) e, dopo la firma, il
motivo della prossima rettifica. Salvare questo form non firma mai."""

from django import forms

from .blocchi import blocco_per
from .models import Referto

PREFISSO_VOCE = 'cl_'


class RefertoForm(forms.ModelForm):
    class Meta:
        model = Referto
        fields = ['descrizione', 'conclusioni', 'raccomandazioni', 'motivo_rettifica']
        labels = {
            'descrizione': 'Descrizione',
            'conclusioni': 'Conclusioni',
            'raccomandazioni': 'Raccomandazioni',
            'motivo_rettifica': 'Motivo della rettifica',
        }
        help_texts = {
            'conclusioni': 'Obbligatorie per firmare.',
            'motivo_rettifica': 'Obbligatorio per emettere la rettifica: lo legge chi ha chiesto.',
        }
        widgets = {
            'descrizione': forms.Textarea(attrs={'rows': 8}),
            'conclusioni': forms.Textarea(attrs={'rows': 5}),
            'raccomandazioni': forms.Textarea(attrs={'rows': 3}),
            'motivo_rettifica': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        referto = self.instance
        self.blocco = blocco_per(referto.richiesta.tipo_esame)
        if not referto.firmato:
            del self.fields['motivo_rettifica']
        classificazione = referto.classificazione or {}
        for voce in self.blocco.voci:
            nome = PREFISSO_VOCE + voce.chiave
            if voce.scelte:
                campo = forms.ChoiceField(label=voce.etichetta, required=False,
                                          choices=[('', '— non indicato —')] + list(voce.scelte),
                                          help_text=voce.aiuto)
            else:
                campo = forms.CharField(label=voce.etichetta, required=False, max_length=500,
                                        help_text=voce.aiuto)
            campo.initial = classificazione.get(voce.chiave, '')
            self.fields[nome] = campo
        for campo in self.fields.values():
            campo.widget.attrs.setdefault('class', 'form-select' if isinstance(campo.widget, forms.Select)
                                          else 'form-control')

    def campi_blocco(self):
        """I BoundField delle voci del blocco, per il partial del tipo."""
        return [self[PREFISSO_VOCE + v.chiave] for v in self.blocco.voci]

    def save(self, commit=True):
        referto = super().save(commit=False)
        classificazione = dict(referto.classificazione or {})
        for voce in self.blocco.voci:
            valore = self.cleaned_data.get(PREFISSO_VOCE + voce.chiave, '')
            if valore:
                classificazione[voce.chiave] = valore
            else:
                classificazione.pop(voce.chiave, None)
        referto.classificazione = classificazione
        if commit:
            referto.save()
        return referto
