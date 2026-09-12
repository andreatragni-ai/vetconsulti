"""
L'endpoint di «Ripulisci» (dettatura vocale): riceve SOLO del testo, lo manda
a Claude per la forma (consulti/dettatura.py) e lo restituisce. Non salva
niente: il testo di prima resta nel browser per «Annulla ripulitura», e il
campo lo salva il form come sempre.

Chi puo' chiamarlo:

- con `caso`: il richiedente che ha aperto quella richiesta, finche' e' in
  BOZZA, oppure il refertatore assegnato. Tutti gli altri 404 (come
  consulti/permessi.py: non si conferma nemmeno che il caso esista).
- senza `caso`: solo al passo 2 di una richiesta **nuova**, dove la bozza
  ancora non esiste (nasce premendo «Avanti»). Vale per chi ha un profilo di
  richiedente o di refertatore, gli altri 403: il portale non e' un servizio
  di AI per chiunque abbia un account.

Piu' un tetto di lunghezza e un freno sulla frequenza (dettatura.py).
"""

import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST

from . import dettatura
from .models import Richiesta
from .permessi import e_refertatore_assegnato, e_richiedente

logger = logging.getLogger('consulti')


def _ha_titolo(utente, caso):
    """La richiesta se l'utente puo' dettarci dentro, altrimenti 404."""
    try:
        richiesta = Richiesta.objects.get(pk=caso)
    except (Richiesta.DoesNotExist, ValueError, TypeError):
        raise Http404
    if e_refertatore_assegnato(utente, richiesta):
        return richiesta
    if e_richiedente(utente, richiesta) and richiesta.modificabile:
        return richiesta
    raise Http404


def _puo_dettare_senza_caso(utente):
    return getattr(utente, 'richiedente', None) is not None or getattr(utente, 'refertatore', None) is not None


@login_required
@require_POST
def ripulisci(request):
    if not settings.CONSULTI_DETTATURA_AI:
        return JsonResponse({'errore': 'La ripulitura non e\' attiva su questo server: '
                                       'il testo resta come l\'hai dettato.'}, status=503)
    try:
        dati = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'errore': 'Richiesta non leggibile.'}, status=400)
    caso = dati.get('caso')
    if caso:
        _ha_titolo(request.user, caso)
    elif not _puo_dettare_senza_caso(request.user):
        return JsonResponse({'errore': 'Non hai i permessi per usare la ripulitura.'}, status=403)

    testo = dati.get('testo') or ''
    if not isinstance(testo, str):
        return JsonResponse({'errore': 'Richiesta non leggibile.'}, status=400)
    try:
        dettatura.controlla_lunghezza(testo)
        dettatura.controlla_frequenza(request.user)
        pulito, correzioni, telemetria = dettatura.ripulisci(testo)
    except dettatura.TestoTroppoLungo as e:
        return JsonResponse({'errore': str(e)}, status=413)
    except dettatura.TroppeRipuliture as e:
        return JsonResponse({'errore': str(e)}, status=429)
    except dettatura.RipulituraNonDisponibile as e:
        return JsonResponse({'errore': str(e)}, status=503)
    logger.info('Ripulitura dettatura: %s', telemetria)
    return JsonResponse({'testo': pulito, 'correzioni': correzioni})
