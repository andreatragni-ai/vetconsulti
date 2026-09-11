"""
Grado 3 dello smistamento: la lettura AI delle miniature (API Anthropic).

## Cosa si manda

Le miniature (JPEG, lato lungo 800 px), a gruppi di `per_richiesta` (8)
immagini nella stessa richiesta, ciascuna preceduta da «Miniatura N: filmato
o immagine, righe possibili: ...». Nel prompt di sistema (uguale per tutte
le richieste, quindi in cache) c'e' il protocollo: codice, nome, finestra,
filmato/immagine, tipo di tracciato, colore, cosa deve vedersi.

La risposta e' JSON vincolato da uno schema (structured output): per ogni
miniatura tipo di tracciato, codice della riga (o «sconosciuto»), seconda
scelta, confidenza alta/media/bassa e un motivo breve. Al modello si chiede
di usare le scritte dell'ecografo (PW, CW, TDI, M, scala colore) e di dire
«sconosciuto» invece di indovinare.

## Privacy

Le miniature arrivano ad Anthropic: l'intestazione dell'ecografo porta
spesso nome del paziente e codice. `taglio_alto` (settings
CONSULTI_SMISTAMENTO_TAGLIO_ALTO) toglie quella fascia prima dell'invio;
quanto costa in accuratezza lo misura `manage.py valuta_smistamento`.

## Quando non c'e'

Chiave assente, libreria non installata, chiave rifiutata, modello non
disponibile: LetturaNonDisponibile con una frase per chi carica, e lo
smistamento si ferma a formato e pixel. Un gruppo che non risponde (timeout,
sovraccarico, rifiuto) lascia quei file da smistare a mano e finisce negli
`errori` della telemetria; gli altri gruppi vanno avanti.

## Telemetria

Token (ingresso, uscita, cache), richieste, durata, costo stimato in dollari
con i prezzi di `prezzi` ($ per milione di token), errori: si salva nello
Smistamento, e il comando di valutazione la riporta per esame.
"""

import base64
import io
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from .dati import (BIDIMENSIONALE, CONTINUO, M_MODE, NOMI_TRACCIATO, PULSATO, TDI, Lettura,
                   LetturaNonDisponibile)

logger = logging.getLogger('eco')

DA_TRACCIATO = {'bidimensionale': BIDIMENSIONALE, 'm-mode': M_MODE, 'doppler pulsato': PULSATO,
                'doppler continuo': CONTINUO, 'tdi': TDI, 'sconosciuto': ''}
CONFIDENZE = ('alta', 'media', 'bassa')
SCONOSCIUTO = 'sconosciuto'
NESSUNA = 'nessuna'
# Il fallback lato server per i rifiuti dei classificatori di sicurezza esiste
# per questi modelli (skill claude-api): con gli altri non si chiede.
MODELLI_CON_FALLBACK = ('claude-opus-5', 'claude-fable-5-1')
BETA_FALLBACK = 'server-side-fallback-2026-07-01'

ISTRUZIONI = """Smisti i file di un'ecocardiografia veterinaria (cane o gatto) che un collega carica su un portale di teleconsulto. Ogni file e' un filmato, di cui vedi un fotogramma, oppure un'immagine esportata dall'ecografo. Il nome della proiezione non e' scritto da nessuna parte: lo devi riconoscere dall'immagine.

Per ogni miniatura numerata:
1. Riconosci il tipo di tracciato: "bidimensionale" (B-mode, anche con il color Doppler sovrapposto), "m-mode" (linee orizzontali che scorrono nel tempo, con la piccola immagine bidimensionale di riferimento in alto), "doppler pulsato" (spettro di velocita' con volume campione/gate, scritta PW), "doppler continuo" (spettro senza gate, scritta CW), "tdi" (Doppler tissutale: velocita' basse del miocardio o dell'anello, scritta TDI o TVI), oppure "sconosciuto". Usa le scritte sullo schermo dell'ecografo: PW, CW, TDI/TVI, M o M-mode, Gate, Sweep, la scala delle velocita' (cm/s, m/s), la barra della scala colore.
2. Indica la riga del protocollo che corrisponde, scegliendo SOLO fra le "righe possibili" indicate per quella miniatura (le altre sono gia' escluse dal formato del file o dal colore). Se non sei ragionevolmente sicuro, rispondi "sconosciuto" invece di indovinare: un file lasciato da smistare costa un gesto al collega, un file nella riga sbagliata puo' sfuggire al refertatore.
3. Seconda scelta: un'altra riga possibile plausibile, oppure "nessuna".
4. Confidenza: "alta" solo se tracciato e proiezione si riconoscono chiaramente; "media" se la proiezione e' probabile ma non certa; "bassa" altrimenti.
5. color_doppler: true se nel settore bidimensionale c'e' il riquadro del color Doppler (pixel rossi e blu del flusso).
6. Motivo: una frase breve in italiano, al massimo 15 parole, su cio' che hai visto (strutture, scritte). Non riportare mai nomi di pazienti, proprietari o codici visibili sullo schermo.

Il protocollo, nell'ordine in cui il collega dovrebbe acquisire:
"""


def _descrivi_riga(r):
    media = {'CLIP': 'filmato', 'STATICA': 'immagine', 'ENTRAMBI': 'filmato o immagine'}.get(r.tipo_media, '')
    colore = {'color': 'con color Doppler', 'bmode': 'senza colore (B-mode)'}.get(r.colore or '', '')
    parti = [f'finestra: {r.finestra}', media, f'tracciato: {NOMI_TRACCIATO.get(r.tracciato, r.tracciato)}']
    if colore:
        parti.append(colore)
    testo = f'- {r.codice}: {r.nome} ({", ".join(p for p in parti if p)})'
    if r.deve_essere_visibile:
        testo += f'. Deve vedersi: {r.deve_essere_visibile.strip()}'
    return testo


def prompt_sistema(righe):
    return ISTRUZIONI + '\n'.join(_descrivi_riga(r) for r in righe)


def schema(codici):
    """Schema JSON della risposta. I codici sono tutti quelli del protocollo
    (stabili: lo schema compilato resta in cache lato API)."""
    return {
        'type': 'object',
        'properties': {
            'miniature': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'numero': {'type': 'integer'},
                        'tracciato': {'type': 'string', 'enum': list(DA_TRACCIATO)},
                        'color_doppler': {'type': 'boolean'},
                        'codice': {'type': 'string', 'enum': [*codici, SCONOSCIUTO]},
                        'seconda_scelta': {'type': 'string', 'enum': [*codici, NESSUNA]},
                        'confidenza': {'type': 'string', 'enum': list(CONFIDENZE)},
                        'motivo': {'type': 'string'},
                    },
                    'required': ['numero', 'tracciato', 'color_doppler', 'codice', 'seconda_scelta', 'confidenza',
                                 'motivo'],
                    'additionalProperties': False,
                },
            },
        },
        'required': ['miniature'],
        'additionalProperties': False,
    }


def prepara_immagine(dati_jpeg, taglio_alto=0.0):
    """La miniatura da mandare: senza la fascia alta (se chiesto), in JPEG."""
    if not taglio_alto:
        return dati_jpeg
    from PIL import Image
    with Image.open(io.BytesIO(dati_jpeg)) as im:
        im = im.convert('RGB')
        larghezza, altezza = im.size
        im = im.crop((0, int(altezza * taglio_alto), larghezza, altezza))
        uscita = io.BytesIO()
        im.save(uscita, 'JPEG', quality=85)
        return uscita.getvalue()


def contenuto_gruppo(gruppo, taglio_alto=0.0):
    """I blocchi del messaggio utente per un gruppo di DaLeggere."""
    blocchi = []
    for n, d in enumerate(gruppo, start=1):
        cosa = 'filmato (fotogramma verso meta\' durata)' if d.genere == 'video' else \
            ('file DICOM' if d.genere == 'dicom' else 'immagine')
        testo = f'Miniatura {n}: {cosa}. Righe possibili: {", ".join(d.candidati)}.'
        if d.colore == 'color':
            testo += ' I pixel dicono: color Doppler presente.'
        elif d.colore == 'bmode':
            testo += ' I pixel dicono: nessun colore.'
        blocchi.append({'type': 'text', 'text': testo})
        blocchi.append({'type': 'image', 'source': {
            'type': 'base64', 'media_type': 'image/jpeg',
            'data': base64.standard_b64encode(prepara_immagine(d.anteprima, taglio_alto)).decode('ascii')}})
    blocchi.append({'type': 'text', 'text': f'Rispondi con una voce per ciascuna delle {len(gruppo)} miniature.'})
    return blocchi


def interpreta(testo, gruppo):
    """Dal JSON della risposta alle Letture, per file_id. Un codice fuori
    dalle righe possibili di quella miniatura vale «sconosciuto»."""
    dati = json.loads(testo)
    letture = {}
    for voce in dati.get('miniature', []):
        n = voce.get('numero')
        if not isinstance(n, int) or not 1 <= n <= len(gruppo):
            continue
        d = gruppo[n - 1]
        codice = voce.get('codice')
        seconda = voce.get('seconda_scelta')
        letture[d.file_id] = Lettura(
            codice=codice if codice in d.candidati else None,
            seconda=seconda if seconda in d.candidati else None,
            confidenza=voce.get('confidenza') if voce.get('confidenza') in CONFIDENZE else 'bassa',
            tracciato=DA_TRACCIATO.get(voce.get('tracciato'), ''),
            color_doppler=voce.get('color_doppler') if isinstance(voce.get('color_doppler'), bool) else None,
            motivo=(voce.get('motivo') or '').strip()[:200])
    return letture


class LettoreClaude:
    """Legge le miniature con un modello Claude con visione.

    `client` si passa nei test (un finto con `beta.messages.create`); senza,
    si crea `anthropic.Anthropic` con la chiave di ANTHROPIC_API_KEY."""

    def __init__(self, modello, *, chiave=None, effort='medium', timeout=180.0, taglio_alto=0.0, per_richiesta=8,
                 paralleli=3, prezzi=None, client=None):
        self.modello = modello
        self.chiave = chiave
        self.effort = effort
        self.timeout = timeout
        self.taglio_alto = taglio_alto
        self.per_richiesta = max(1, per_richiesta)
        self.paralleli = max(1, paralleli)
        self.prezzi = prezzi or {}
        self._client = client
        self.modello_senza_fallback = False

    # ── client ──────────────────────────────────────────────────────────
    def _crea_client(self):
        if self._client is not None:
            return self._client
        chiave = self.chiave or os.environ.get('ANTHROPIC_API_KEY', '').strip()
        if not chiave:
            raise LetturaNonDisponibile('La lettura automatica non e\' configurata su questo server: '
                                        'i file sono divisi per formato, le righe scegline tu.')
        try:
            import anthropic
        except ImportError:
            raise LetturaNonDisponibile('La lettura automatica non e\' installata su questo server: '
                                        'i file sono divisi per formato, le righe scegline tu.')
        self._client = anthropic.Anthropic(api_key=chiave, timeout=self.timeout, max_retries=2)
        return self._client

    # ── una richiesta ───────────────────────────────────────────────────
    def _chiedi(self, client, sistema, formato, gruppo):
        parametri = dict(
            model=self.modello, max_tokens=16000,
            system=[{'type': 'text', 'text': sistema, 'cache_control': {'type': 'ephemeral'}}],
            output_config={'effort': self.effort, 'format': {'type': 'json_schema', 'schema': formato}},
            messages=[{'role': 'user', 'content': contenuto_gruppo(gruppo, self.taglio_alto)}],
        )
        if self.modello in MODELLI_CON_FALLBACK and not self.modello_senza_fallback:
            parametri.update(betas=[BETA_FALLBACK], fallbacks='default')
        inizio = time.monotonic()
        risposta = client.beta.messages.create(**parametri)
        durata = time.monotonic() - inizio
        uso = getattr(risposta, 'usage', None)
        consumo = {
            'input': getattr(uso, 'input_tokens', 0) or 0,
            'output': getattr(uso, 'output_tokens', 0) or 0,
            'cache_scrittura': getattr(uso, 'cache_creation_input_tokens', 0) or 0,
            'cache_lettura': getattr(uso, 'cache_read_input_tokens', 0) or 0,
            'durata': durata,
            'modello_risposta': getattr(risposta, 'model', self.modello),
        }
        if getattr(risposta, 'stop_reason', None) == 'refusal':
            return {}, consumo, 'rifiuto'
        testo = next((b.text for b in risposta.content if getattr(b, 'type', '') == 'text'), '')
        try:
            return interpreta(testo, gruppo), consumo, None
        except (ValueError, TypeError) as e:
            return {}, consumo, f'risposta non leggibile ({getattr(risposta, "stop_reason", "")}): {e}'

    def _gruppo_protetto(self, client, sistema, formato, gruppo):
        """Una richiesta, con gli errori per gruppo trasformati in una voce di
        telemetria. Gli errori che valgono per tutti (chiave, permesso,
        modello) risalgono come LetturaNonDisponibile."""
        import anthropic
        try:
            try:
                return self._chiedi(client, sistema, formato, gruppo)
            except anthropic.BadRequestError as e:
                # Il fallback lato server e' in beta: se l'API non lo accetta
                # insieme al resto, si riprova una volta senza.
                if self.modello not in MODELLI_CON_FALLBACK or 'fallback' not in str(e).lower():
                    raise
                logger.warning('Smistamento: fallback rifiutato dall\'API, riprovo senza: %s', e)
                self.modello_senza_fallback = True
                return self._chiedi(client, sistema, formato, gruppo)
        except anthropic.AuthenticationError:
            raise LetturaNonDisponibile('La lettura automatica non e\' disponibile (chiave rifiutata): '
                                        'smista i file a mano.')
        except anthropic.PermissionDeniedError:
            raise LetturaNonDisponibile('La lettura automatica non e\' disponibile (permesso negato): '
                                        'smista i file a mano.')
        except anthropic.NotFoundError:
            raise LetturaNonDisponibile(f'La lettura automatica non e\' disponibile (modello {self.modello} '
                                        f'non trovato): smista i file a mano.')
        except anthropic.RateLimitError as e:
            return {}, {}, f'servizio sovraccarico: {e.__class__.__name__}'
        except anthropic.APITimeoutError:
            return {}, {}, 'tempo scaduto'
        except anthropic.APIConnectionError:
            return {}, {}, 'connessione non riuscita'
        except anthropic.BadRequestError as e:
            logger.warning('Smistamento: richiesta rifiutata dall\'API: %s', e)
            return {}, {}, f'richiesta non valida: {getattr(e, "message", e)}'[:300]
        except anthropic.APIStatusError as e:
            return {}, {}, f'errore del servizio ({e.status_code})'

    # ── tutte ───────────────────────────────────────────────────────────
    def leggi(self, da_leggere, righe):
        client = self._crea_client()
        sistema = prompt_sistema(righe)
        formato = schema([r.codice for r in righe])
        gruppi = [da_leggere[i:i + self.per_richiesta] for i in range(0, len(da_leggere), self.per_richiesta)]
        inizio = time.monotonic()
        esiti = []
        # Il primo gruppo da solo (scrive la cache del prompt di sistema), gli
        # altri in parallelo (la leggono).
        if gruppi:
            esiti.append(self._gruppo_protetto(client, sistema, formato, gruppi[0]))
        if len(gruppi) > 1:
            with ThreadPoolExecutor(max_workers=self.paralleli) as pool:
                esiti.extend(pool.map(lambda g: self._gruppo_protetto(client, sistema, formato, g), gruppi[1:]))
        letture, errori = {}, []
        totali = {'input': 0, 'output': 0, 'cache_scrittura': 0, 'cache_lettura': 0}
        modelli = set()
        for lette, consumo, errore in esiti:
            letture.update(lette)
            for k in totali:
                totali[k] += consumo.get(k, 0)
            if consumo.get('modello_risposta'):
                modelli.add(consumo['modello_risposta'])
            if errore:
                errori.append(errore)
        telemetria = {
            'modello': self.modello, 'modelli_risposta': sorted(modelli), 'effort': self.effort,
            'taglio_alto': self.taglio_alto, 'richieste': len(gruppi), 'immagini': len(da_leggere),
            'token_input': totali['input'], 'token_output': totali['output'],
            'token_cache_scrittura': totali['cache_scrittura'], 'token_cache_lettura': totali['cache_lettura'],
            'durata_s': round(time.monotonic() - inizio, 1), 'errori': errori,
            'costo_usd': round(self.costo(totali), 4),
        }
        if errori and not letture:
            logger.warning('Smistamento: nessun gruppo letto (%s).', '; '.join(errori))
        return letture, telemetria

    def costo(self, totali):
        """Dollari stimati: ingresso, uscita (pensiero compreso), scrittura in
        cache a 1,25x e lettura a 0,1x del prezzo d'ingresso."""
        ingresso, uscita = self.prezzi.get(self.modello, (0, 0))
        return (totali['input'] * ingresso + totali['output'] * uscita
                + totali['cache_scrittura'] * ingresso * 1.25 + totali['cache_lettura'] * ingresso * 0.1) / 1e6


def da_settings():
    """Il lettore configurato in settings, o None se lo smistamento AI e'
    spento (CONSULTI_SMISTAMENTO_AI = False)."""
    from django.conf import settings
    if not getattr(settings, 'CONSULTI_SMISTAMENTO_AI', True):
        return None
    return LettoreClaude(
        settings.CONSULTI_MODELLO_SMISTAMENTO,
        effort=getattr(settings, 'CONSULTI_SMISTAMENTO_EFFORT', 'medium'),
        timeout=getattr(settings, 'CONSULTI_SMISTAMENTO_TIMEOUT', 90.0),
        taglio_alto=getattr(settings, 'CONSULTI_SMISTAMENTO_TAGLIO_ALTO', 0.0),
        per_richiesta=getattr(settings, 'CONSULTI_SMISTAMENTO_PER_RICHIESTA', 8),
        prezzi=getattr(settings, 'CONSULTI_PREZZI_MODELLI', {}),
    )
