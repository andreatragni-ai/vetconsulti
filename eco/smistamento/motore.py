"""
Il motore dello smistamento: dai file caricati alle proposte, per gradi.

    1  formato     il PDF e' il referto dell'ecografo; un filmato va solo
                   nelle righe «filmato», un'immagine solo in quelle «immagine»
    2  pixel       un filmato color Doppler va solo nelle righe «— color
                   Doppler», uno B-mode solo in quelle «— B-mode» (colore.py)
    3  lettura AI  tipo di tracciato e proiezione dalla miniatura, fra le sole
                   righe rimaste possibili (lettore.py); senza AI si salta
    4  ordine      se i file, nell'ordine di acquisizione, seguono l'ordine
                   del protocollo, le letture in sequenza pesano di piu' e un
                   file non riconosciuto fra due riconosciuti prende l'unica
                   riga che sta fra le loro
    5  assegnazione una riga al piu' un file, un file al piu' una riga:
                   greedy per punteggio, a parita' vince il file acquisito
                   prima e la riga che viene prima nel protocollo

Tutto deterministico a parita' di letture. Niente Django: `smista()` riceve
FileEsame e Riga (dati.py) e un lettore qualsiasi con il metodo
`leggi(da_leggere, righe) -> (letture, telemetria)`.

I filmati liberi (LIBERO_1, LIBERO_2) non si riempiono da soli: vogliono
una nota di chi carica. Un file in piu' resta «da smistare» e il collega,
se vuole, lo sposta in una riga libera scrivendo la nota.
"""

import os
import re

from . import colore as colore_pixel
from .dati import (BMODE, COLOR, CONFIDENZA, INCERTO, NOMI_TRACCIATO, SOGLIA_SICURA, DaLeggere,
                   LetturaNonDisponibile, Proposta, Risultato)

FORMATO = 'FORMATO'
AI = 'AI'
ORDINE = 'ORDINE'

PUNTEGGIO_SECONDA = 0.3
PUNTEGGIO_ORDINE = 0.5
SPINTA_SEQUENZA = 0.1
# Una sequenza «segue il protocollo» se almeno 4 letture e almeno il 60 %
# delle letture utili stanno in ordine crescente di protocollo.
SEQUENZA_MIN = 4
SEQUENZA_QUOTA = 0.6
# Letture che contano per la sequenza: almeno «media».
SOGLIA_SEQUENZA = 0.6


def chiave_naturale(testo):
    """IMG_2 prima di IMG_10: i numeri si confrontano come numeri."""
    return [int(p) if p.isdigit() else p for p in re.split(r'(\d+)', (testo or '').lower())]


def ordina_acquisizione(files):
    """Nome naturale (con la cartella), poi data di modifica, poi id."""
    return sorted(files, key=lambda f: (chiave_naturale(f.percorso or f.nome), f.modificato_il or 0, f.id))


def _tipi_per_genere(genere):
    if genere == 'video':
        return ('CLIP', 'ENTRAMBI')
    if genere == 'immagine':
        return ('STATICA', 'ENTRAMBI')
    if genere == 'dicom':
        return ('CLIP', 'STATICA', 'ENTRAMBI')
    return ()


def candidati(file, righe):
    """Gradi 1 e 2: le righe (non libere) dove il file puo' andare."""
    tipi = _tipi_per_genere(file.genere)
    possibili = [r for r in righe if not r.libera and r.tipo_media in tipi]
    if file.genere == 'video' and file.colore in (COLOR, BMODE):
        possibili = [r for r in possibili if r.colore in (None, file.colore)]
    return possibili


def sottosequenza_crescente(valori):
    """Indici di una sottosequenza strettamente crescente piu' lunga
    (a parita', quella che finisce prima). O(n^2): n e' una trentina."""
    if not valori:
        return []
    lunghezza = [1] * len(valori)
    precedente = [-1] * len(valori)
    for i in range(len(valori)):
        for j in range(i):
            if valori[j] < valori[i] and lunghezza[j] + 1 > lunghezza[i]:
                lunghezza[i] = lunghezza[j] + 1
                precedente[i] = j
    fine = max(range(len(valori)), key=lambda i: (lunghezza[i], -i))
    indici = []
    while fine != -1:
        indici.append(fine)
        fine = precedente[fine]
    return indici[::-1]


def _misura_colore(files):
    for f in files:
        if f.genere == 'video' and f.anteprima and not f.colore:
            try:
                f.colore, f.frazione_colore = colore_pixel.classifica(f.anteprima)
            except Exception:  # miniatura illeggibile: nessun vincolo
                f.colore = INCERTO


def _estensione(nome):
    return (os.path.splitext(nome or '')[1].lstrip('.') or 'senza estensione').upper()


def smista(files, righe, lettore=None, *, righe_occupate=frozenset(), referto_libero=True):
    """Le proposte per `files` sulle `righe` non gia' occupate (quelle con un
    file messo a mano o caricato nella riga). `referto_libero`: False se il
    referto dell'ecografo e' gia' al suo posto."""
    ordinati = ordina_acquisizione(files)
    rango = {f.id: i for i, f in enumerate(ordinati)}
    libere = [r for r in righe if r.id not in righe_occupate]
    per_id = {r.id: r for r in righe}
    per_codice = {r.codice: r for r in libere}
    proposte = {f.id: Proposta(file_id=f.id) for f in ordinati}
    messaggio = ''

    # ── Grado 1: il PDF ─────────────────────────────────────────────────
    pdf = [f for f in ordinati if f.genere == 'pdf']
    for i, f in enumerate(pdf):
        p = proposte[f.id]
        if i == 0 and referto_libero:
            p.referto, p.fonte, p.confidenza = True, FORMATO, 1.0
            p.sicura = len(pdf) == 1
            p.motivo = ('E\' l\'unico PDF: e\' il referto dell\'ecografo.' if len(pdf) == 1 else
                        f'Il primo dei {len(pdf)} PDF: controlla che sia il referto dell\'ecografo.')
        elif not referto_libero:
            p.motivo = 'Il referto dell\'ecografo c\'e\' gia\': se e\' questo quello giusto, spostalo tu.'
        else:
            p.motivo = 'Piu\' di un PDF: il referto proposto e\' il primo; questo resta a te.'

    # ── Grado 2: colore dai pixel ───────────────────────────────────────
    _misura_colore(ordinati)
    for f in ordinati:
        proposte[f.id].colore = f.colore or ''
    possibili = {f.id: candidati(f, libere) for f in ordinati}

    # ── Grado 3: lettura AI ─────────────────────────────────────────────
    da_leggere = [DaLeggere(file_id=f.id, anteprima=f.anteprima, genere=f.genere,
                            candidati=[r.codice for r in possibili[f.id]], colore=f.colore or '')
                  for f in ordinati if f.anteprima and possibili[f.id]]
    letture, telemetria, lettura_ai = {}, {}, False
    if da_leggere:
        if lettore is None:
            messaggio = 'Lettura automatica spenta: i file sono divisi per formato, le righe scegline tu.'
        else:
            try:
                letture, telemetria = lettore.leggi(da_leggere, [r for r in libere if not r.libera])
                lettura_ai = bool(letture)
                non_lette = len(da_leggere) - len(letture)
                if non_lette and telemetria.get('errori'):
                    messaggio = (f'La lettura automatica non ha risposto per {non_lette} file su '
                                 f'{len(da_leggere)}: smistali tu.')
            except LetturaNonDisponibile as e:
                messaggio = str(e)

    # Opzioni: (punteggio, file, riga, fonte, motivo, primaria)
    opzioni = []
    primaria = {}
    for f in ordinati:
        lettura = letture.get(f.id)
        codici = {r.codice for r in possibili[f.id]}
        p = proposte[f.id]
        if lettura is None:
            continue
        p.tracciato = lettura.tracciato
        if lettura.codice in codici:
            riga = per_codice[lettura.codice]
            punteggio = CONFIDENZA.get(lettura.confidenza, CONFIDENZA['bassa'])
            motivo = lettura.motivo
            if lettura.tracciato and lettura.tracciato != riga.tracciato:
                punteggio = min(punteggio, 0.6)
                motivo = (f'{motivo} (letto come {NOMI_TRACCIATO.get(lettura.tracciato, lettura.tracciato)}, '
                          f'la riga vuole {NOMI_TRACCIATO[riga.tracciato]})').strip()
            if f.genere == 'video' and riga.colore:
                if f.colore == INCERTO:
                    punteggio = min(punteggio, 0.8)   # i pixel non confermano
                if lettura.color_doppler is not None and lettura.color_doppler != (riga.colore == COLOR):
                    punteggio = min(punteggio, 0.6)
            primaria[f.id] = [punteggio, riga.id, motivo]
        if lettura.seconda in codici and lettura.seconda != lettura.codice:
            riga2 = per_codice[lettura.seconda]
            p.seconda_id = riga2.id
            opzioni.append([PUNTEGGIO_SECONDA, f.id, riga2.id, AI,
                            f'Seconda scelta della lettura automatica. {lettura.motivo}'.strip(), False])

    # ── Grado 4: ordine di acquisizione ─────────────────────────────────
    sequenza = [(rango[fid], per_id[v[1]].ordine, fid) for fid, v in primaria.items() if v[0] >= SOGLIA_SEQUENZA]
    sequenza.sort()
    indici = sottosequenza_crescente([s[1] for s in sequenza])
    in_sequenza = [sequenza[i] for i in indici]
    segue_protocollo = len(in_sequenza) >= SEQUENZA_MIN and len(in_sequenza) >= SEQUENZA_QUOTA * len(sequenza)
    telemetria = {**telemetria, 'segue_protocollo': segue_protocollo,
                  'in_sequenza': len(in_sequenza), 'letture_utili': len(sequenza)}
    if segue_protocollo:
        for _r, _o, fid in in_sequenza:
            primaria[fid][0] = min(0.99, primaria[fid][0] + SPINTA_SEQUENZA)
        for f in ordinati:
            if f.id in primaria or not possibili[f.id]:
                continue
            prima = max((s for s in in_sequenza if s[0] < rango[f.id]), default=None)
            dopo = min((s for s in in_sequenza if s[0] > rango[f.id]), default=None)
            if prima is None and dopo is None:
                continue
            basso = prima[1] if prima else -1
            alto = dopo[1] if dopo else float('inf')
            fra = [r for r in possibili[f.id] if basso < r.ordine < alto]
            if len(fra) == 1:
                opzioni.append([PUNTEGGIO_ORDINE, f.id, fra[0].id, ORDINE,
                                'Dedotta dall\'ordine di acquisizione: sta fra due file riconosciuti.', False])

    for fid, (punteggio, riga_id, motivo) in primaria.items():
        opzioni.append([punteggio, fid, riga_id, AI, motivo, True])

    # ── Grado 5: assegnazione ───────────────────────────────────────────
    opzioni.sort(key=lambda o: (-o[0], rango[o[1]], per_id[o[2]].ordine))
    righe_prese, file_messi = set(), set()
    for punteggio, fid, riga_id, fonte, motivo, e_primaria in opzioni:
        if fid in file_messi or riga_id in righe_prese:
            continue
        p = proposte[fid]
        p.riga_id, p.confidenza, p.fonte, p.motivo = riga_id, round(punteggio, 2), fonte, motivo
        p.sicura = fonte == AI and e_primaria and punteggio >= SOGLIA_SICURA
        righe_prese.add(riga_id)
        file_messi.add(fid)

    # Chi resta da smistare sa perche'.
    for f in ordinati:
        p = proposte[f.id]
        if p.riga_id is not None or p.referto or f.genere == 'pdf':
            continue
        lettura = letture.get(f.id)
        if f.genere not in ('video', 'immagine', 'dicom'):
            p.motivo = 'Formato non riconosciuto: scegli tu dove va.'
        elif not possibili[f.id]:
            p.motivo = ('Nessuna riga libera per un filmato cosi\': se serve, mettilo in un filmato libero.'
                        if f.genere == 'video' else 'Nessuna riga libera per un\'immagine cosi\'.')
        elif not f.anteprima:
            p.motivo = (f'Il browser non ha potuto leggere questo filmato ({_estensione(f.nome)}): '
                        f'trascinalo tu sulla riga giusta.' if f.genere in ('video', 'dicom') else
                        'Nessuna miniatura: trascinalo tu sulla riga giusta.')
        elif lettura is None:
            p.motivo = 'Non letto automaticamente: scegli tu la riga.'
        elif f.id in primaria:
            p.motivo = (f'La riga proposta («{per_id[primaria[f.id][1]].nome}») e\' andata a un file '
                        f'piu\' probabile: controlla tu.')
        else:
            p.motivo = ('La lettura automatica non l\'ha riconosciuto'
                        + (f': {lettura.motivo}' if lettura.motivo else '.'))
    return Risultato(proposte=[proposte[f.id] for f in ordinati], messaggio=messaggio, lettura_ai=lettura_ai,
                     telemetria=telemetria, letture=letture)
