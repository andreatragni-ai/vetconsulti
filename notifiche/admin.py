from django.contrib import admin

from .models import InvioEmail


@admin.register(InvioEmail)
class InvioEmailAdmin(admin.ModelAdmin):
    list_display = ('inviata_il', 'tipo', 'destinatario', 'richiesta', 'esito')
    list_filter = ('tipo', 'esito')
    search_fields = ('destinatario', 'oggetto', 'richiesta__codice')
    readonly_fields = ('inviata_il',)
