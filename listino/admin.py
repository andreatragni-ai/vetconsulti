from django.contrib import admin

from .models import Supplemento, VoceListino


@admin.register(VoceListino)
class VoceListinoAdmin(admin.ModelAdmin):
    list_display = ('tipo_esame', 'descrizione', 'prezzo', 'aliquota_iva', 'valido_dal', 'valido_al')
    list_filter = ('tipo_esame',)


@admin.register(Supplemento)
class SupplementoAdmin(admin.ModelAdmin):
    list_display = ('codice', 'descrizione', 'tipo', 'importo', 'percentuale', 'valido_dal', 'valido_al')
    list_filter = ('tipo',)
