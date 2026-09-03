from django.contrib import admin

from .models import ProiezioneCaricata, ProiezioneCatalogo


@admin.register(ProiezioneCatalogo)
class ProiezioneCatalogoAdmin(admin.ModelAdmin):
    list_display = ('ordine', 'codice', 'nome', 'tipo_media', 'obbligatoria', 'attiva')
    list_display_links = ('codice', 'nome')
    list_filter = ('tipo_media', 'obbligatoria', 'attiva')
    list_editable = ('ordine', 'obbligatoria', 'attiva')
    ordering = ('ordine',)


@admin.register(ProiezioneCaricata)
class ProiezioneCaricataAdmin(admin.ModelAdmin):
    list_display = ('richiesta', 'proiezione', 'allegato', 'nota')
    list_select_related = ('richiesta', 'proiezione', 'allegato')
