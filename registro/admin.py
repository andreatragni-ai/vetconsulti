from django.contrib import admin

from core.admin_sola_lettura import SolaLettura
from .models import Prestazione, StatoFatturazione


class StatoFatturazioneInline(SolaLettura, admin.StackedInline):
    model = StatoFatturazione
    extra = 0


@admin.register(Prestazione)
class PrestazioneAdmin(SolaLettura, admin.ModelAdmin):
    """Lo stato della fatturazione si cambia da Gestione → Prestazioni."""
    list_display = ('richiesta', 'data', 'tipo_esame', 'intestazione', 'refertatore', 'totale', 'stato_fatt')
    list_filter = ('tipo_esame', 'soggetto_emittente', 'fatturazione__stato')
    inlines = [StatoFatturazioneInline]

    @admin.display(description='Intestatario')
    def intestazione(self, obj):
        return obj.intestatario().denominazione

    @admin.display(description='Fatturazione')
    def stato_fatt(self, obj):
        return obj.fatturazione.get_stato_display() if hasattr(obj, 'fatturazione') else '—'
