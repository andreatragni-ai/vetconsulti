"""
«Ripulisci con l'AI» del testo dettato: la forma, mai il contenuto.

## Perche' esiste

Il collega detta nei campi di testo col **riconoscimento vocale del browser**
(`static/consulti/js/dettatura.js`): gratis, e l'audio non esce dal suo
computer perche' non passa da noi. In cambio il testo arriva senza
punteggiatura, con le sigle a orecchio («emme emme vi di») e le unita' di
misura attaccate. Questo modulo manda **solo quel testo** a Claude e lo
riscrive in forma leggibile. Niente audio ai fornitori, e il costo e' quello
di poche centinaia di token.

La strada alternativa — la pipeline di VetCardio con ElevenLabs Scribe a
0,10 $/minuto — resta per il giorno in cui la qualita' del browser non
bastasse: non e' implementata qui di proposito (decisione di Andre, 12/09/2026).

## Le tre regole

1. **Solo forma.** Il prompt (`prompts/it/ripulitura_dettatura.md`, mai
   inline) vieta di aggiungere, togliere o interpretare contenuto clinico.
   `_plausibile` e' la cintura di sicurezza: una risposta che ha perso un
   pezzo di testo viene scartata e il campo resta com'era.
2. **L'ultima parola e' del collega.** La vista non salva nulla: il testo
   ripulito torna al browser, che lo mette nel campo e tiene quello di prima
   per «Annulla ripulitura».
3. **Se non funziona, non si perde niente.** Chiave assente, libreria
   mancante, API che non risponde: `RipulituraNonDisponibile` con una frase
   per il collega, e il testo nel campo non si tocca.

## Modello

`settings.CONSULTI_MODELLO_DETTATURA` (oggi Claude Sonnet 5): e' un lavoro di
sola forma su poche righe di testo, senza immagini e senza giudizio clinico,
e chi ha dettato aspetta davanti allo schermo. Vedi il commento in
`config/settings/base.py`.
"""

import json
import logging
import os
import time
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from .glossario_dettatura import per_prompt, sigle_per_prompt

logger = logging.getLogger('consulti')

CARTELLA_PROMPT = Path(settings.BASE_DIR) / 'prompts'
LINGUA = 'it'

# Un campo dettato e' qualche riga: il tetto serve a non mandare per sbaglio
# (o per dispetto) un documento intero all'API.
LIMITE_CARATTERI = 4000
# Freno semplice: quante ripuliture per utente in QUANTI_SECONDI. Sta nella
# cache di Django (in dev e' in memoria, quindi per processo: con piu' worker
# il tetto vero e' questo numero per worker. Basta a fermare un pulsante
# premuto a raffica, che e' cio' che deve fermare).
QUANTE_RIPULITURE = 20
QUANTI_SECONDI = 300


class RipulituraNonDisponibile(Exception):
    """Il messaggio e' pensato per chi ha dettato."""


class TestoTroppoLungo(RipulituraNonDisponibile):
    pass


class TroppeRipuliture(RipulituraNonDisponibile):
    pass


def prompt_sistema():
    """Il prompt dal file, con glossario e sigle al posto dei segnaposti."""
    testo = (CARTELLA_PROMPT / LINGUA / 'ripulitura_dettatura.md').read_text(encoding='utf-8')
    return testo.replace('{{GLOSSARIO}}', per_prompt()).replace('{{SIGLE}}', sigle_per_prompt())


def schema():
    """Structured output: il testo e le correzioni da mostrare al collega."""
    return {
        'type': 'object',
        'properties': {
            'testo': {'type': 'string'},
            'correzioni': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['testo', 'correzioni'],
        'additionalProperties': False,
    }


# ── Freno e limiti ───────────────────────────────────────────────────────────

def controlla_lunghezza(testo):
    if len(testo) > LIMITE_CARATTERI:
        raise TestoTroppoLungo(
            f'Il testo e\' troppo lungo per la ripulitura ({len(testo)} caratteri, '
            f'il massimo e\' {LIMITE_CARATTERI}): ripulisci un pezzo alla volta.')


def controlla_frequenza(utente):
    """Conta le ripuliture dell'utente nella finestra e si ferma al tetto."""
    chiave = f'dettatura:ripuliture:{utente.pk}'
    cache.add(chiave, 0, QUANTI_SECONDI)
    try:
        quante = cache.incr(chiave)
    except ValueError:          # scaduta fra l'add e l'incr: si riparte da uno
        cache.set(chiave, 1, QUANTI_SECONDI)
        quante = 1
    if quante > QUANTE_RIPULITURE:
        raise TroppeRipuliture('Hai chiesto troppe ripuliture di seguito: aspetta un minuto e riprova.')


# ── La cintura di sicurezza ──────────────────────────────────────────────────

# Sotto questa lunghezza non si misura niente: «emme emme vi di» (15 caratteri)
# diventa «MMVD» (4) ed e' una ripulitura perfetta.
MINIMO_DA_MISURARE = 40
MENO_DEL = 0.5      # un testo che si dimezza non e' stato ripulito: e' stato riassunto
PIU_DEL = 2.0       # e uno che raddoppia ha qualcosa in piu' che non abbiamo dettato


def _plausibile(prima, dopo):
    """Vero se `dopo` e' ancora lo stesso testo, ripulito.

    Si guardano i CARATTERI e non le parole: sciogliere le sigle dettate
    accorcia molto il conto delle parole («tre sesti» -> «3/6», «emme emme vi
    di» -> «MMVD») ed e' proprio cio' che vogliamo. Un testo che si dimezza o
    raddoppia, invece, non e' piu' quello del collega: si butta e resta il
    suo. E' una rete di sicurezza grossolana sopra il prompt, non un
    controllo del contenuto: quello lo fa il collega rileggendo."""
    prima, dopo = (prima or '').strip(), (dopo or '').strip()
    if not prima:
        return not dopo
    if not dopo:
        return False
    if len(prima) < MINIMO_DA_MISURARE:
        return True
    return MENO_DEL <= len(dopo) / len(prima) <= PIU_DEL


# ── La chiamata ──────────────────────────────────────────────────────────────

def _crea_client(timeout):
    chiave = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not chiave:
        raise RipulituraNonDisponibile('La ripulitura non e\' configurata su questo server: '
                                       'il testo resta come l\'hai dettato.')
    try:
        import anthropic
    except ImportError:
        raise RipulituraNonDisponibile('La ripulitura non e\' installata su questo server: '
                                       'il testo resta come l\'hai dettato.')
    return anthropic.Anthropic(api_key=chiave, timeout=timeout, max_retries=1)


def ripulisci(testo, *, client=None, modello=None, timeout=None):
    """(testo ripulito, [correzioni], telemetria). Non salva niente e non
    solleva mai un'eccezione che non sia RipulituraNonDisponibile."""
    testo = (testo or '').strip()
    controlla_lunghezza(testo)
    if not testo:
        return '', [], {}
    modello = modello or settings.CONSULTI_MODELLO_DETTATURA
    timeout = timeout or settings.CONSULTI_DETTATURA_TIMEOUT
    client = client or _crea_client(timeout)
    inizio = time.monotonic()
    risposta = _chiedi(client, modello, testo)
    uso = getattr(risposta, 'usage', None)
    telemetria = {
        'modello': getattr(risposta, 'model', modello),
        'input': getattr(uso, 'input_tokens', 0) or 0,
        'output': getattr(uso, 'output_tokens', 0) or 0,
        'durata': round(time.monotonic() - inizio, 2),
    }
    if getattr(risposta, 'stop_reason', None) == 'refusal':
        raise RipulituraNonDisponibile('La ripulitura non e\' andata a buon fine: '
                                       'il testo resta come l\'hai dettato.')
    grezzo = next((b.text for b in risposta.content if getattr(b, 'type', '') == 'text'), '')
    try:
        dati = json.loads(grezzo)
        pulito = (dati['testo'] or '').strip()
        correzioni = [str(c).strip()[:80] for c in (dati.get('correzioni') or [])][:12]
    except (ValueError, TypeError, KeyError) as e:
        logger.warning('Ripulitura: risposta non leggibile (%s)', e)
        raise RipulituraNonDisponibile('La ripulitura non e\' andata a buon fine: '
                                       'il testo resta come l\'hai dettato.')
    if not _plausibile(testo, pulito):
        logger.warning('Ripulitura scartata: %d caratteri diventati %d', len(testo), len(pulito))
        raise RipulituraNonDisponibile('La ripulitura ha cambiato troppo il testo, quindi l\'ho scartata: '
                                       'il tuo testo e\' intatto.')
    return pulito, correzioni, telemetria


def _chiedi(client, modello, testo):
    """Una richiesta all'API. Gli errori diventano RipulituraNonDisponibile con
    una frase per il collega: il campo non si tocca mai."""
    import anthropic
    parametri = dict(
        model=modello, max_tokens=4000,
        system=[{'type': 'text', 'text': prompt_sistema(), 'cache_control': {'type': 'ephemeral'}}],
        output_config={'effort': settings.CONSULTI_DETTATURA_EFFORT,
                       'format': {'type': 'json_schema', 'schema': schema()}},
        messages=[{'role': 'user', 'content': f'Testo dettato da ripulire:\n\n{testo}'}],
    )
    try:
        return client.beta.messages.create(**parametri)
    except anthropic.AuthenticationError:
        raise RipulituraNonDisponibile('La ripulitura non e\' disponibile (chiave rifiutata): '
                                       'il testo resta come l\'hai dettato.')
    except anthropic.PermissionDeniedError:
        raise RipulituraNonDisponibile('La ripulitura non e\' disponibile su questo server: '
                                       'il testo resta come l\'hai dettato.')
    except anthropic.NotFoundError:
        raise RipulituraNonDisponibile('Il modello della ripulitura non e\' disponibile: '
                                       'il testo resta come l\'hai dettato.')
    except anthropic.RateLimitError:
        raise RipulituraNonDisponibile('Il fornitore AI e\' occupato: riprova fra un momento, '
                                       'il testo resta come l\'hai dettato.')
    except anthropic.APIError as e:
        logger.warning('Ripulitura: errore dall\'API (%s)', e)
        raise RipulituraNonDisponibile('La ripulitura non e\' andata a buon fine: '
                                       'il testo resta come l\'hai dettato.')
