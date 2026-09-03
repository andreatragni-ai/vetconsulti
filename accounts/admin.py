from django.contrib import admin

from .models import (Clinica, CompetenzaRefertatore, Consenso, DatiFatturazione, Refertatore,
                     Richiedente)


class CompetenzaInline(admin.TabularInline):
    model = CompetenzaRefertatore
    extra = 0


class DatiFatturazioneInline(admin.StackedInline):
    model = DatiFatturazione
    extra = 0


@admin.register(Refertatore)
class RefertatoreAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'attivo', 'soggetto_emittente', 'assente_dal', 'assente_al')
    list_filter = ('attivo', 'soggetto_emittente')
    search_fields = ('user__username', 'user__last_name', 'user__email')
    inlines = [CompetenzaInline]


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


@admin.register(DatiFatturazione)
class DatiFatturazioneAdmin(admin.ModelAdmin):
    list_display = ('intestatario', 'partita_iva', 'clinica', 'richiedente', 'predefinita', 'codice_sdi')
    search_fields = ('intestatario', 'partita_iva')


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
class ConsensoAdmin(admin.ModelAdmin):
    list_display = ('user', 'tipo', 'versione', 'accettato_il')
    list_filter = ('tipo', 'versione')


admin.site.register(CompetenzaRefertatore)
