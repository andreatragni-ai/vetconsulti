from django.contrib import admin

from .models import ImmagineRiferimento, ProiezioneCaricata, ProiezioneCatalogo


class ImmagineRiferimentoInline(admin.TabularInline):
    model = ImmagineRiferimento
    extra = 0
    fields = ('ordine', 'immagine', 'didascalia')


@admin.register(ProiezioneCatalogo)
class ProiezioneCatalogoAdmin(admin.ModelAdmin):
    list_display = ('ordine', 'codice', 'nome', 'finestra', 'tipo_media', 'obbligatoria', 'libera', 'attiva',
                    'n_immagini')
    list_display_links = ('codice', 'nome')
    list_filter = ('finestra', 'tipo_media', 'obbligatoria', 'libera', 'attiva')
    list_editable = ('ordine', 'obbligatoria', 'attiva')
    ordering = ('finestra', 'ordine')
    search_fields = ('codice', 'nome')
    inlines = [ImmagineRiferimentoInline]
    fieldsets = (
        (None, {'fields': ('codice', 'nome', 'finestra', 'tipo_media', 'obbligatoria', 'libera', 'ordine',
                           'attiva', 'scheda_guida')}),
        ('Per chi carica', {'fields': ('istruzioni', 'deve_essere_visibile')}),
        ('Per il refertatore', {'fields': ('serve_per', 'descrizione')}),
        ('Appunti sul catalogo', {'fields': ('nota_riferimento',)}),
    )

    @admin.display(description='Immagini')
    def n_immagini(self, obj):
        return obj.immagini.count()


@admin.register(ProiezioneCaricata)
class ProiezioneCaricataAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'proiezione', 'allegato', 'nota')
    list_select_related = ('richiesta', 'proiezione', 'allegato')
