from django.contrib import admin

from .models import Allegato, Commento, ContatoreAnno, EventoAudit, Paziente, Richiesta


class PazienteInline(admin.StackedInline):
    model = Paziente
    extra = 0


class AllegatoInline(admin.TabularInline):
    model = Allegato
    extra = 0
    readonly_fields = ('dimensione', 'sha256', 'mime', 'caricato_da', 'caricato_il')


class AuditInline(admin.TabularInline):
    model = EventoAudit
    extra = 0
    can_delete = False
    readonly_fields = ('utente', 'azione', 'dettaglio', 'quando')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Richiesta)
class RichiestaAdmin(admin.ModelAdmin):
    list_display = ('codice', 'tipo_esame', 'stato', 'richiedente', 'clinica', 'refertatore', 'urgenza', 'creata_il')
    list_filter = ('stato', 'tipo_esame', 'urgenza')
    search_fields = ('codice', 'paziente__nome', 'clinica__denominazione')
    readonly_fields = ('codice', 'creata_il', 'inviata_il', 'presa_in_carico_il', 'chiusa_il')
    inlines = [PazienteInline, AllegatoInline, AuditInline]


@admin.register(Allegato)
class AllegatoAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'categoria', 'nome_originale', 'dimensione', 'stato', 'caricato_il')
    list_filter = ('categoria', 'stato')
    readonly_fields = ('sha256', 'dimensione', 'mime', 'caricato_il')


@admin.register(EventoAudit)
class EventoAuditAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'azione', 'utente', 'quando')
    list_filter = ('azione',)
    readonly_fields = ('richiesta', 'utente', 'azione', 'dettaglio', 'quando')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(Commento)
admin.site.register(ContatoreAnno)
