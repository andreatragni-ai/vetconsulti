"""Form della Gestione. Riusano quelli di accounts dove il campo e' lo
stesso (competenze, dati di fatturazione, nuovo refertatore) e aggiungono
solo cio' che decide lo staff e non l'esperto stesso: se riceve casi,
chi emette la fattura, nome ed email dell'account."""

from django import forms
from django.contrib.auth import get_user_model

from accounts.forms import FotoInput, _bootstrap
from accounts.models import Refertatore, SoggettoEmittente

User = get_user_model()


class UtenteForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'Nome', 'last_name': 'Cognome', 'email': 'Email'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.required = True
        _bootstrap(self)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Un altro account usa gia\' questa email.')
        return email


class RefertatoreGestioneForm(forms.ModelForm):
    class Meta:
        model = Refertatore
        fields = ['titolo', 'specializzazione', 'numero_iscrizione', 'ordine_provinciale', 'messaggio',
                  'foto', 'firma', 'attivo', 'assente_dal', 'assente_al', 'soggetto_emittente']
        labels = {
            'attivo': 'Riceve casi',
            'firma': 'Firma per il referto',
            'messaggio': 'Messaggio accanto al nome',
            'soggetto_emittente': 'Chi emette la fattura',
            'numero_iscrizione': 'N. iscrizione all\'Ordine',
        }
        help_texts = {
            'attivo': 'Spento: sparisce dall\'elenco degli esperti. I casi che ha gia\' restano suoi.',
            'firma': 'Immagine della firma, stampata in fondo al PDF del referto.',
            'foto': 'La vedono i colleghi quando scelgono l\'esperto.',
            'soggetto_emittente': '',
            'titolo': '',
        }
        widgets = {
            'foto': FotoInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
            'assente_dal': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'assente_al': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'soggetto_emittente': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self)

    def _update_errors(self, errors):
        """Refertatore.clean() segna l'errore su `dati_fatturazione`, che qui
        non e' un campo (i dati hanno un form loro): Django solleverebbe
        ValueError. Lo si sposta sulla scelta «Chi emette la fattura»."""
        dizionario = getattr(errors, 'error_dict', None)
        if dizionario and 'dati_fatturazione' in dizionario:
            dizionario.setdefault('soggetto_emittente', []).extend(dizionario.pop('dati_fatturazione'))
        super()._update_errors(errors)

    @property
    def in_proprio(self):
        valore = self.data.get(self.add_prefix('soggetto_emittente')) if self.is_bound \
            else self.instance.soggetto_emittente
        return valore == SoggettoEmittente.REFERTATORE
