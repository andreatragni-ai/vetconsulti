"""Casi in sola lettura: si interviene da Gestione (core/admin_sola_lettura.py)."""

from django.contrib import admin

from core.admin_sola_lettura import SolaLettura
from .models import Allegato, EventoAudit, Paziente, PazienteArchivio, Richiesta


class PazienteInline(SolaLettura, admin.StackedInline):
    model = Paziente
    extra = 0


class AllegatoInline(SolaLettura, admin.TabularInline):
    model = Allegato
    extra = 0
    fields = ('categoria', 'nome_originale', 'stato', 'caricato_il')


class AuditInline(SolaLettura, admin.TabularInline):
    model = EventoAudit
    extra = 0
    fields = ('quando', 'utente', 'azione', 'dettaglio')


@admin.register(Richiesta)
class RichiestaAdmin(SolaLettura, admin.ModelAdmin):
    list_display = ('codice', 'tipo_esame', 'stato', 'richiedente', 'refertatore', 'urgenza', 'inviata_il')
    list_filter = ('stato', 'tipo_esame', 'urgenza')
    search_fields = ('codice', 'paziente__nome', 'clinica__denominazione')
    exclude = ('motivo_esame',)
    inlines = [PazienteInline, AllegatoInline, AuditInline]


@admin.register(EventoAudit)
class EventoAuditAdmin(SolaLettura, admin.ModelAdmin):
    list_display = ('richiesta', 'azione', 'utente', 'quando')
    list_filter = ('azione',)
    search_fields = ('richiesta__codice',)


@admin.register(PazienteArchivio)
class PazienteArchivioAdmin(SolaLettura, admin.ModelAdmin):
    """L'archivio pazienti si guarda, non si corregge: lo riscrive l'invio
    successivo (`consulti/anagrafica.py`, l'ultimo caso vince). I doppioni
    si uniscono dalla Gestione, il giorno che serve (docs/BACKLOG.md)."""

    list_display = ('nome', 'cognome_proprietario', 'specie', 'razza', 'clinica', 'visto_il')
    list_filter = ('specie', 'clinica')
    search_fields = ('nome', 'cognome_proprietario', 'razza')
