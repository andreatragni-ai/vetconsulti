from django.contrib import admin

from core.admin_sola_lettura import SolaLettura
from .models import Referto, VersioneReferto


class VersioneInline(SolaLettura, admin.TabularInline):
    model = VersioneReferto
    extra = 0
    fields = ('numero', 'firmato_il', 'firmato_da', 'motivo_rettifica', 'pdf')


@admin.register(Referto)
class RefertoAdmin(SolaLettura, admin.ModelAdmin):
    """Le versioni firmate si guardano, non si toccano."""
    list_display = ('richiesta', 'versione', 'firmato_il', 'firmato_da')
    search_fields = ('richiesta__codice',)
    inlines = [VersioneInline]
