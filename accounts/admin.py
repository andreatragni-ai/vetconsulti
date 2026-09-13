from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group

from core.admin_sola_lettura import SolaLettura

from .forms import FotoInput
from .models import (Clinica, CompetenzaRefertatore, Consenso, DatiFatturazione, Refertatore,
                     Richiedente)


class CompetenzaInline(admin.TabularInline):
    model = CompetenzaRefertatore
    extra = 0


class DatiFatturazioneInline(admin.StackedInline):
    model = DatiFatturazione
    extra = 0


class RefertatoreAdminForm(forms.ModelForm):
    class Meta:
        model = Refertatore
        fields = '__all__'
        widgets = {'foto': FotoInput}


@admin.register(Refertatore)
class RefertatoreAdmin(admin.ModelAdmin):
    form = RefertatoreAdminForm
    list_display = ('__str__', 'con_foto', 'attivo', 'soggetto_emittente', 'assente_dal', 'assente_al')
    list_filter = ('attivo', 'soggetto_emittente')
    search_fields = ('user__username', 'user__last_name', 'user__email')
    inlines = [CompetenzaInline]

    @admin.display(description='Foto', boolean=True)
    def con_foto(self, obj):
        return bool(obj.foto)


@admin.register(Clinica)
class ClinicaAdmin(admin.ModelAdmin):
    list_display = ('denominazione', 'comune', 'provincia', 'approvata', 'creata_il')
    list_filter = ('approvata', 'provincia')
    search_fields = ('denominazione', 'comune')
    inlines = [DatiFatturazioneInline]
    actions = ['approva']

    @admin.action(description='Approva le cliniche selezionate')
    def approva(self, request, queryset):
        queryset.update(approvata=True)


@admin.register(Richiedente)
class RichiedenteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'tipo', 'clinica', 'approvato', 'ruolo', 'creato_il')
    list_filter = ('tipo', 'approvato', 'ruolo')
    search_fields = ('user__username', 'user__last_name', 'clinica__denominazione')
    inlines = [DatiFatturazioneInline]
    actions = ['approva']

    @admin.action(description='Approva i liberi professionisti selezionati')
    def approva(self, request, queryset):
        queryset.update(approvato=True)


@admin.register(Consenso)
class ConsensoAdmin(SolaLettura, admin.ModelAdmin):
    """Prova di cosa ha accettato chi e quando: non si modifica."""
    list_display = ('user', 'tipo', 'versione', 'accettato_il')
    list_filter = ('tipo', 'versione')


# Il portale non usa i gruppi di Django: i permessi sono is_staff e i profili.
admin.site.unregister(Group)
