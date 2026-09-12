"""
La memoria della misura: cosa proponeva lo smistamento automatico e cosa ha
confermato l'umano (modello EsitoSmistamento).

Due momenti, perche' le proposte vengono consumate:

1. **appena lo smistamento finisce** (`fotografa`, chiamata da esecuzione.py)
   si fotografa la proposta — riga, confidenza, «sicuro», tracciato, modello —
   prima che uno spostamento a mano la riscriva;
2. **alla conferma** (`registra_conferma`, chiamata da tavolo.conferma) si
   scrive dove il file e' finito davvero e se l'umano ha corretto.

Un file che non e' mai passato dallo smistamento automatico (caricato
direttamente nella sua riga) non ha niente da misurare e non entra qui: non
c'e' nessuna proposta da giudicare.

In questa tabella non finisce **nessun dato del paziente**: codice del caso,
id dell'allegato, codici del catalogo.
"""

import logging

from django.utils import timezone

logger = logging.getLogger('eco')


def _modello():
    from eco.models import EsitoSmistamento
    return EsitoSmistamento


def fotografa(smistamento, proposte):
    """La proposta di ogni file appena lo smistamento automatico finisce.
    `proposte`: le PropostaSmistamento appena scritte (gia' salvate)."""
    EsitoSmistamento = _modello()
    richiesta = smistamento.richiesta
    for p in proposte:
        EsitoSmistamento.objects.update_or_create(
            richiesta=richiesta, allegato_interno=p.allegato_id,
            defaults={
                'codice_richiesta': richiesta.codice,
                'smistamento': smistamento,
                'modello': smistamento.modello,
                'proposta': p.proiezione.codice if p.proiezione_id else '',
                'proposta_referto': p.referto,
                'fonte': p.fonte or '',
                'confidenza': p.confidenza,
                'sicura': p.sicura,
                'tracciato': p.tracciato or '',
                'seconda_scelta': p.seconda_scelta.codice if p.seconda_scelta_id else '',
                # Un giro nuovo azzera la conferma precedente: si rigiudica.
                'confermato_il': None, 'finale': '', 'finale_referto': False, 'corretto': False,
            })


def registra_conferma(richiesta, proposte):
    """«Confermo lo smistamento»: dove ogni file e' finito davvero. Tocca solo
    i file che una proposta automatica ce l'avevano."""
    EsitoSmistamento = _modello()
    adesso = timezone.now()
    per_allegato = {p.allegato_id: p for p in proposte}
    esiti = EsitoSmistamento.objects.filter(richiesta=richiesta, allegato_interno__in=per_allegato)
    for esito in esiti:
        p = per_allegato[esito.allegato_interno]
        esito.finale = p.proiezione.codice if p.proiezione_id else ''
        esito.finale_referto = p.referto
        esito.corretto = esito.dove_proponeva != esito.dove_e_finito
        esito.confermato_il = adesso
        esito.save(update_fields=['finale', 'finale_referto', 'corretto', 'confermato_il'])
    return len(esiti)
