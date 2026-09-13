from django.contrib import admin

from core.admin_sola_lettura import SolaLettura
from .models import Supplemento, VoceListino


@admin.register(VoceListino)
class VoceListinoAdmin(SolaLettura, admin.ModelAdmin):
    """I prezzi si cambiano da Gestione → Listino, che non riscrive la storia."""
    list_display = ('tipo_esame', 'prezzo', 'aliquota_iva', 'valido_dal', 'valido_al')
    list_filter = ('tipo_esame',)


@admin.register(Supplemento)
class SupplementoAdmin(SolaLettura, admin.ModelAdmin):
    list_display = ('descrizione', 'importo', 'percentuale', 'valido_dal', 'valido_al')
