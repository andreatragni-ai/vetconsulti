from django.contrib import admin

from core.admin_sola_lettura import SolaLettura
from .models import InvioEmail


@admin.register(InvioEmail)
class InvioEmailAdmin(SolaLettura, admin.ModelAdmin):
    list_display = ('inviata_il', 'tipo', 'destinatario', 'richiesta', 'esito')
    list_filter = ('tipo', 'esito')
    search_fields = ('destinatario', 'oggetto', 'richiesta__codice')
