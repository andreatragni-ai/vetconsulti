from django.contrib import admin

from .models import Prestazione, StatoFatturazione


class StatoFatturazioneInline(admin.StackedInline):
    model = StatoFatturazione
    extra = 0


@admin.register(Prestazione)
class PrestazioneAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'data', 'tipo_esame', 'intestazione', 'refertatore', 'soggetto_emittente',
                    'totale', 'stato_fatt')
    list_filter = ('tipo_esame', 'soggetto_emittente', 'fatturazione__stato')
    readonly_fields = Prestazione.CAMPI_DEL_FATTO + ('registrata_il',)
    inlines = [StatoFatturazioneInline]

    @admin.display(description='Intestatario')
    def intestazione(self, obj):
        return obj.intestatario().denominazione

    @admin.display(description='Fatturazione')
    def stato_fatt(self, obj):
        return obj.fatturazione.get_stato_display() if hasattr(obj, 'fatturazione') else '—'

    def has_add_permission(self, request):
        return False


@admin.register(StatoFatturazione)
class StatoFatturazioneAdmin(admin.ModelAdmin):
    list_display = ('prestazione', 'stato', 'numero_fattura', 'data_fattura')
    list_filter = ('stato',)
