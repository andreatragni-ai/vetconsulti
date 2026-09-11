from django.contrib import admin

from .models import Referto, VersioneReferto


class VersioneInline(admin.TabularInline):
    model = VersioneReferto
    extra = 0
    can_delete = False
    fields = ('numero', 'firmato_il', 'firmato_da', 'motivo_rettifica', 'pdf')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Referto)
class RefertoAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'versione', 'firmato_il', 'firmato_da')
    list_filter = ('firmato_il',)
    readonly_fields = ('firmato_il', 'firmato_da', 'pdf', 'versione', 'creato_il', 'aggiornato_il')
    search_fields = ('richiesta__codice',)
    inlines = [VersioneInline]


@admin.register(VersioneReferto)
class VersioneRefertoAdmin(admin.ModelAdmin):
    """Le versioni firmate si guardano, non si toccano."""
    list_display = ('referto', 'numero', 'firmato_il', 'firmato_da')
    search_fields = ('referto__richiesta__codice',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
