"""
Lo smistamento automatico di una richiesta: dal database al motore e
ritorno, in un thread dopo il commit (come la transcodifica: niente code
esterne). La pagina del passo 3 legge lo stato dell'ultimo Smistamento con
htmx finche' non e' FATTO.

Cosa si rimette in gioco: i file da smistare e quelli proposti dal formato,
dalla lettura AI o dall'ordine che non sono ancora confermati. Restano dove
sono i file spostati a mano, quelli caricati direttamente in una riga e
tutto cio' che e' gia' confermato (con il loro posto occupato).
"""

import logging
import threading

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from consulti import anteprime
from consulti.caricamento import genere_file

from . import lettore as lettore_ai
from . import esiti, motore, righe as righe_catalogo, tavolo
from .dati import FileEsame

logger = logging.getLogger('eco')

USA_SETTINGS = object()
# Uno smistamento IN_CORSO da piu' di cosi' si considera morto (thread perso
# con un riavvio del server): se ne puo' avviare un altro.
MINUTI_MAX = 15


def in_corso(richiesta):
    from eco.models import StatoSmistamento
    ultimo = richiesta.smistamenti.first()
    if ultimo is None or ultimo.stato != StatoSmistamento.IN_CORSO:
        return None
    if (timezone.now() - ultimo.avviato_il).total_seconds() > MINUTI_MAX * 60:
        return None
    return ultimo


def avvia(richiesta, utente):
    """Crea lo Smistamento e lo fa partire dopo il commit. Se ce n'e' gia'
    uno in corso ritorna quello."""
    from eco.models import Smistamento
    gia = in_corso(richiesta)
    if gia is not None:
        return gia
    tavolo.assicura_proposte(richiesta)
    ai = getattr(settings, 'CONSULTI_SMISTAMENTO_AI', True)
    s = Smistamento.objects.create(
        richiesta=richiesta, avviato_da=utente, n_file=richiesta.proposte_smistamento.count(),
        modello=settings.CONSULTI_MODELLO_SMISTAMENTO if ai else '')
    richiesta.registra('SMISTAMENTO_AVVIATO', utente, smistamento=s.pk, file=s.n_file)
    transaction.on_commit(lambda: pianifica(s.pk))
    return s


def pianifica(smistamento_id):
    if not getattr(settings, 'CONSULTI_SMISTAMENTO_IN_THREAD', True):
        esegui(smistamento_id)
        return None

    def lavoro():
        from django.db import connection
        try:
            esegui(smistamento_id)
        finally:
            connection.close()

    filo = threading.Thread(target=lavoro, name=f'smistamento-{smistamento_id}', daemon=True)
    filo.start()
    return filo


def _file_esame(proposta):
    allegato = proposta.allegato
    genere = genere_file(allegato.nome_originale or allegato.file.name, allegato.mime)
    if genere in ('immagine', 'video'):
        anteprime.assicura(allegato)
    dati = None
    if allegato.anteprima:
        try:
            with allegato.anteprima.open('rb') as f:
                dati = f.read()
        except OSError:
            dati = None
    return FileEsame(id=allegato.pk, nome=allegato.nome_originale or allegato.file.name, genere=genere,
                     anteprima=dati, percorso=proposta.percorso_originale or allegato.nome_originale,
                     modificato_il=proposta.modificato_il)


def esegui(smistamento_id, lettore=USA_SETTINGS):
    """Il lavoro vero: legge proposte e catalogo, chiama il motore, scrive le
    proposte nuove e chiude lo Smistamento. Qualsiasi errore lascia le
    proposte com'erano e un messaggio per chi carica."""
    from eco.models import (FonteProposta, ProiezioneCatalogo, PropostaSmistamento, Smistamento,
                            StatoSmistamento, in_ordine)
    s = Smistamento.objects.select_related('richiesta').get(pk=smistamento_id)
    richiesta = s.richiesta
    try:
        if lettore is USA_SETTINGS:
            lettore = lettore_ai.da_settings()
        confermate, referti = tavolo.stato_confermato(richiesta)
        proposte = list(PropostaSmistamento.objects.filter(richiesta=richiesta).select_related('allegato'))
        fisse = [p for p in proposte if p.fonte in (FonteProposta.MANUALE, FonteProposta.RIGA)
                 or (not p.da_smistare and tavolo.e_confermata(p, confermate, referti))]
        mobili = [p for p in proposte if p not in fisse]
        righe = righe_catalogo.da_catalogo(in_ordine(ProiezioneCatalogo.objects.filter(attiva=True)))
        risultato = motore.smista(
            [_file_esame(p) for p in mobili], righe, lettore,
            righe_occupate=frozenset(p.proiezione_id for p in fisse if p.proiezione_id),
            referto_libero=not any(p.referto for p in fisse))
        per_file = {r.file_id: r for r in risultato.proposte}
        with transaction.atomic():
            PropostaSmistamento.objects.filter(pk__in=[p.pk for p in mobili]).update(proiezione=None, referto=False)
            for p in mobili:
                r = per_file.get(p.allegato_id)
                if r is None:
                    continue
                p.proiezione_id = r.riga_id
                p.referto = r.referto
                p.fonte = r.fonte if (r.riga_id or r.referto) else FonteProposta.DA_SMISTARE
                p.confidenza = r.confidenza
                p.sicura = r.sicura
                p.motivo = (r.motivo or '')[:300]
                p.seconda_scelta_id = r.seconda_id
                p.tracciato = r.tracciato or ''
                p.colore = r.colore or ''
                p.save()
            # La misura sul campo: la proposta si fotografa adesso, prima che
            # uno spostamento a mano la riscriva (eco/smistamento/esiti.py).
            esiti.fotografa(s, mobili)
            s.stato = StatoSmistamento.FATTO
            s.lettura_ai = risultato.lettura_ai
            s.messaggio = risultato.messaggio
            s.telemetria = risultato.telemetria
            s.finito_il = timezone.now()
            s.save()
    except Exception:
        logger.exception('Smistamento %s della richiesta %s non riuscito.', s.pk, richiesta.codice)
        Smistamento.objects.filter(pk=s.pk).update(
            stato=StatoSmistamento.ERRORE, finito_il=timezone.now(),
            messaggio='Lo smistamento automatico non e\' riuscito: metti tu i file nelle righe.')
    return Smistamento.objects.get(pk=s.pk)
