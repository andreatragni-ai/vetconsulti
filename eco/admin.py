from django.contrib import admin

from .models import (EsitoSmistamento, ImmagineRiferimento, ProiezioneCaricata, ProiezioneCatalogo,
                     PropostaSmistamento, Smistamento)


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


@admin.register(Smistamento)
class SmistamentoAdmin(admin.ModelAdmin):
    """Per guardare com'e' andato uno smistamento: stato, messaggio e
    telemetria (token, costo, errori). Sola lettura: lo scrive il portale."""

    list_display = ('richiesta', 'stato', 'avviato_il', 'finito_il', 'n_file', 'modello', 'lettura_ai')
    list_filter = ('stato', 'lettura_ai', 'modello')
    search_fields = ('richiesta__codice',)
    readonly_fields = [c.name for c in Smistamento._meta.fields]


@admin.register(PropostaSmistamento)
class PropostaSmistamentoAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'allegato', 'proiezione', 'referto', 'fonte', 'confidenza', 'sicura', 'colore')
    list_filter = ('fonte', 'sicura', 'colore')
    list_select_related = ('richiesta', 'proiezione', 'allegato')
    search_fields = ('richiesta__codice', 'allegato__nome_originale')


@admin.register(EsitoSmistamento)
class EsitoSmistamentoAdmin(admin.ModelAdmin):
    """La misura sul campo: cosa proponeva l'automatismo e cosa ha confermato
    l'umano. Sola lettura, e i conti li fa `manage.py accuratezza_smistamento`:
    qui si guarda il singolo file."""

    list_display = ('codice_richiesta', 'proposta', 'finale', 'corretto', 'sicura', 'fonte', 'confidenza',
                    'tracciato', 'confermato_il')
    list_filter = ('corretto', 'sicura', 'fonte', 'modello')
    search_fields = ('codice_richiesta', 'proposta', 'finale')
    readonly_fields = [c.name for c in EsitoSmistamento._meta.fields]
