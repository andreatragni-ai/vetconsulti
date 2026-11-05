"""
Chi puo' fare cosa su un caso. Una regola in un posto solo:

- **refertatore assegnato**: l'unico che decide (prende in carico, declina,
  referta, firma, rettifica);
- **richiedente**: il suo caso; annulla solo prima della presa in carico,
  riassegna un caso declinato;
- **staff**: vede tutto; ogni volta che apre un caso che non e' suo resta
  un EventoAudit ACCESSO_STAFF. Sui casi agisce SOLO dalla Gestione e solo
  nelle emergenze (gestione/views.py: affidare a un altro esperto,
  annullare), con le transizioni *_da_gestione del modello: mai dalle
  pagine del richiedente o del refertatore, mai dall'admin di Django;
- **tutti gli altri**: 404, non 403 (non si conferma che il caso esista).

Una sola eccezione, decisa con Andre il 05/11/2026 (`puo_leggere_referto`):
l'esperto assegnato a un caso puo' leggere i referti FIRMATI degli altri
casi dello stesso paziente, anche di colleghi, perche' lo storico di quel
cane serve a refertare. Solo il PDF, e con un ACCESSO_STORICO nell'audit del
caso letto.
"""

from django.http import Http404

from .models import Richiesta


def e_refertatore_assegnato(utente, richiesta):
    ref = getattr(utente, 'refertatore', None)
    return ref is not None and richiesta.refertatore_id == ref.id


def e_richiedente(utente, richiesta):
    return richiesta.richiedente.user_id == utente.id


def caso_del_refertatore(utente, pk):
    """La richiesta se `utente` ne e' il refertatore assegnato; 404 per tutti
    gli altri, staff compreso (lo staff non agisce)."""
    ref = getattr(utente, 'refertatore', None)
    if ref is None:
        raise Http404
    try:
        return (Richiesta.objects.select_related('richiedente__user', 'clinica', 'refertatore__user', 'paziente')
                .get(pk=pk, refertatore=ref))
    except Richiesta.DoesNotExist:
        raise Http404


def caso_del_richiedente(utente, pk):
    try:
        return Richiesta.objects.select_related('refertatore__user').get(pk=pk, richiedente__user=utente)
    except Richiesta.DoesNotExist:
        raise Http404


def registra_accesso_staff(utente, richiesta, pagina):
    """Lo staff che guarda un caso non suo lascia traccia. Chi e' anche
    richiedente o refertatore del caso sta guardando il proprio lavoro."""
    if not utente.is_staff:
        return None
    if e_richiedente(utente, richiesta) or e_refertatore_assegnato(utente, richiesta):
        return None
    return richiesta.registra('ACCESSO_STAFF', utente, pagina=pagina)


def puo_leggere_referto(utente, richiesta):
    """Chi puo' leggere il PDF di un referto FIRMATO: lo staff, chi ha
    chiesto, l'esperto assegnato — e, dal 05/11/2026, l'esperto assegnato a
    un altro caso dello stesso paziente (`anagrafica.puo_leggere_per_storico`:
    chi referta oggi l'eco di Luna vuole vedere l'ECG di marzo). Non apre la
    pagina del caso ne' gli allegati, e lascia un ACCESSO_STORICO."""
    from . import anagrafica
    return bool(utente.is_staff or e_richiedente(utente, richiesta)
                or e_refertatore_assegnato(utente, richiesta)
                or anagrafica.puo_leggere_per_storico(utente, richiesta))


def registra_accesso_storico(utente, richiesta, pagina):
    """L'esperto di un altro caso che legge questo referto lascia traccia,
    come lo staff. Chi e' richiedente, refertatore assegnato o staff sta
    guardando cose sue: nessun evento (lo staff ha il suo)."""
    if (utente.is_staff or e_richiedente(utente, richiesta)
            or e_refertatore_assegnato(utente, richiesta)):
        return None
    from . import anagrafica
    if not anagrafica.puo_leggere_per_storico(utente, richiesta):
        return None
    return richiesta.registra('ACCESSO_STORICO', utente, pagina=pagina)
