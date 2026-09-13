"""L'admin di Django come cassetta degli attrezzi (13/09/2026).

Il lavoro di tutti i giorni sta in Gestione. Qui restano poche voci, e
quelle che toccano la storia (casi, referti, email, listino) sono in sola
lettura: uno stato cambiato da un menu a tendina scavalca le transizioni,
non lascia audit e puo' rompere la fatturazione.
"""

from django.contrib import admin


class SolaLettura:
    """Mixin per ModelAdmin e inline: si guarda, non si tocca."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def togli(*modelli):
    for m in modelli:
        if admin.site.is_registered(m):
            admin.site.unregister(m)
