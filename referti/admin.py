from django.contrib import admin

from .models import Referto


@admin.register(Referto)
class RefertoAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'versione', 'firmato_il', 'firmato_da')
    list_filter = ('firmato_il',)
    readonly_fields = ('firmato_il', 'firmato_da', 'pdf', 'creato_il', 'aggiornato_il')
    search_fields = ('richiesta__codice',)
