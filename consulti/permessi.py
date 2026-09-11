"""
Chi puo' fare cosa su un caso. Una regola in un posto solo:

- **refertatore assegnato**: l'unico che decide (prende in carico, declina,
  referta, firma, rettifica);
- **richiedente**: il suo caso; annulla solo prima della presa in carico,
  riassegna un caso declinato;
- **staff**: vede tutto in lettura e non agisce; ogni volta che apre un
  caso che non e' suo resta un EventoAudit ACCESSO_STAFF;
- **tutti gli altri**: 404, non 403 (non si conferma che il caso esista).
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
