"""
Consegna protetta degli allegati.

Gli allegati di un consulto sono dati clinici: un tracciato ECG, una clip
ecocardiografica, il referto di un Holter. Non vengono MAI serviti come
statici pubblici — MEDIA_URL non compare in urls.py — ma passano da questa
view, che verifica chi sta chiedendo e poi:

- in DEBUG legge il file e lo manda (FileResponse), comodo in locale;
- in produzione risponde con X-Accel-Redirect verso /_media_interno/, un
  prefisso che nginx serve come `internal`: il file non attraversa Python,
  quindi il controllo dei permessi non si paga in banda ne' in memoria.

Chi ha titolo: il richiedente che ha aperto la richiesta, il refertatore
assegnato (o, se non c'e' ancora, un refertatore referente per quel tipo),
lo staff. Tutti gli altri ricevono 404, non 403: non si conferma che il
file esista.
"""

import mimetypes
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404

# Prefisso interno noto solo a nginx: non e' raggiungibile dall'esterno.
PREFISSO_INTERNO = '/_media_interno/'


def consegna(percorso_relativo, nome_scaricato=None):
    """Risposta che consegna un file sotto MEDIA_ROOT."""
    assoluto = os.path.join(settings.MEDIA_ROOT, percorso_relativo)

    if settings.DEBUG:
        if not os.path.isfile(assoluto):
            raise Http404
        risposta = FileResponse(open(assoluto, 'rb'))
        if nome_scaricato:
            risposta['Content-Disposition'] = f'attachment; filename="{nome_scaricato}"'
        return risposta

    risposta = HttpResponse()
    # quote(): l'intestazione viaggia come URI; uno spazio o un accento nel
    # nome farebbero rispondere 404 a nginx senza che Django lo sappia.
    risposta['X-Accel-Redirect'] = PREFISSO_INTERNO + quote(percorso_relativo)
    del risposta['Content-Type']
    tipo, _ = mimetypes.guess_type(assoluto)
    if tipo:
        risposta['Content-Type'] = tipo
    if nome_scaricato:
        risposta['Content-Disposition'] = f'attachment; filename="{nome_scaricato}"'
    return risposta


def puo_vedere_allegato(utente, allegato):
    """Regola unica su chi apre un allegato: la usano questa view e i test."""
    if utente.is_staff:
        return True
    richiesta = allegato.richiesta
    if richiesta.richiedente and richiesta.richiedente.user_id == utente.id:
        return True
    refertatore = getattr(utente, 'refertatore', None)
    if refertatore is None:
        return False
    if richiesta.refertatore_id == refertatore.id:
        return True
    # Caso non ancora assegnato: chi e' referente per quel tipo puo' guardarlo
    # per decidere se prenderlo in carico.
    return richiesta.refertatore_id is None and refertatore.referta(richiesta.tipo_esame)


@login_required
def scarica_allegato(request, pk):
    from consulti.models import Allegato

    allegato = get_object_or_404(Allegato.objects.select_related('richiesta__richiedente'), pk=pk)
    if not puo_vedere_allegato(request.user, allegato):
        raise Http404
    if not allegato.file:
        raise Http404
    return consegna(allegato.file.name, nome_scaricato=allegato.nome_originale or None)
