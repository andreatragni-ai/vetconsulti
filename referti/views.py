from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404

from core.views_media import consegna
from . import pdf
from .models import Referto


def _puo_vedere(utente, referto):
    if utente.is_staff:
        return True
    r = referto.richiesta
    if r.richiedente.user_id == utente.id:
        return referto.firmato  # il richiedente vede solo il referto firmato
    ref = getattr(utente, 'refertatore', None)
    return ref is not None and r.refertatore_id == ref.id


@login_required
def stampa(request, pk):
    """PDF del referto. Se e' firmato e gia' salvato lo consegna dallo
    storage; altrimenti (anteprima del refertatore) lo genera al volo."""
    referto = get_object_or_404(Referto.objects.select_related('richiesta__richiedente'), pk=pk)
    if not _puo_vedere(request.user, referto):
        raise Http404
    if referto.firmato and referto.pdf:
        return consegna(referto.pdf.name, nome_scaricato=f'{referto.richiesta.codice}.pdf')
    risposta = HttpResponse(pdf.genera_pdf(referto), content_type='application/pdf')
    risposta['Content-Disposition'] = f'inline; filename="{referto.richiesta.codice}_anteprima.pdf"'
    return risposta
