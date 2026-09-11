"""
Misura onesta dello smistamento automatico, con l'API vera, su un banco di
immagini ecografiche vere.

    ANTHROPIC_API_KEY=... manage.py valuta_smistamento [--taglio 0.08]
        [--ordine mescolato|protocollo] [--modello claude-opus-5]
        [--effort medium] [--json risultati.json]

## Il banco

Le immagini di riferimento del catalogo (eco/catalogo/img/), che sono
proiezioni vere; niente schemi, foto della sonda, radiografie o disegni.
NON si usano i file del kit dimostrativo: hanno il nome della proiezione
scritto dentro e la lettura barerebbe. Le immagini NON si copiano da nessuna
parte: si leggono da eco/catalogo/img/ a ogni esecuzione, si riducono come
fa il browser (800 px), si rinominano in modo neutro (IMG_0001.jpg...) e si
mescolano con un seme fisso. La verita' (quale riga) viene dal catalogo
(`immagini_riferimento` di ogni riga), scritta qui sotto in BANCO.

Due gruppi:
- `principale` (17): immagini che SONO il file che la riga chiede. Le 7 dei
  filmati B-mode fanno da fotogramma del filmato (genere «video»); le 10
  immagini (M-mode, LA/Ao, LAD, Doppler pulsato e continuo, TDI) genere
  «immagine». Alcune hanno scritte che aiutano (misure, «METODO ...»,
  «LAD Distance», lettere sulle strutture): sono segnate `scritte` e i
  numeri si danno anche senza di loro.
- `guida` (9): immagini bidimensionali che il catalogo usa come guida per
  righe Doppler o M-mode (dove mettere il cursore). NON sono il file che
  quelle righe chiedono: la risposta giusta e' «sconosciuto» o «da
  verificare», mai «sicuro» su una riga Doppler.

Limiti del banco (da ricordare leggendo i numeri): e' piccolo (17 + 9);
non ha fotogrammi color Doppler veri (il colore dai pixel e' provato sulle
immagini sintetiche dei test); e' fatto di immagini scelte per una
presentazione, piu' pulite della media dei filmati di un collega.
"""

import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from consulti.anteprime import jpeg_ridotto
from eco.models import ProiezioneCatalogo, in_ordine
from eco.smistamento import esemplari as modulo_esemplari
from eco.smistamento import motore, righe as righe_catalogo
from eco.smistamento.dati import NOMI_TRACCIATO, Esemplare, FileEsame
from eco.smistamento.lettore import LettoreClaude

CARTELLA = Path(__file__).resolve().parents[2] / 'catalogo'

# (file, righe giuste, genere, gruppo, scritte che aiutano)
BANCO = [
    ('dx1_eco.jpg', ('DX1_B',), 'video', 'principale', False),
    ('dx2_eco.jpg', ('DX2_B',), 'video', 'principale', False),
    ('dx2_eco2.jpg', ('DX2_B',), 'video', 'principale', False),
    ('dx3_eco.jpg', ('DX3_B',), 'video', 'principale', False),
    ('rif_sub_eco.jpg', ('SUB_B',), 'video', 'principale', False),
    ('sx1_eco.jpg', ('SX1_B',), 'video', 'principale', False),
    ('sx2_eco.jpg', ('SX2_B',), 'video', 'principale', False),
    ('dx5_eco.jpg', ('DX5_LAAO',), 'immagine', 'principale', False),
    ('dx5_misura.jpg', ('DX5_LAAO',), 'immagine', 'principale', True),
    ('dx5_svedese.jpg', ('DX5_LAAO',), 'immagine', 'principale', True),
    ('dx7_mmode.jpg', ('DX7_MMODE',), 'immagine', 'principale', False),
    ('dx7_resp.jpg', ('DX7_MMODE',), 'immagine', 'principale', True),
    ('rif_lad_misura.jpg', ('DX_LAD',), 'immagine', 'principale', True),
    ('rif_pvpa_mmode.jpg', ('D2_PVPA',), 'immagine', 'principale', True),
    ('d1_pw.jpg', ('D1_MIT_PW',), 'immagine', 'principale', False),
    ('sx10_ao.jpg', ('SUB_LVOT_CW',), 'immagine', 'principale', False),
    ('rif_tdi.jpg', ('D1_TDI',), 'immagine', 'principale', False),
    ('d2_corto.jpg', ('D2_PVPA',), 'immagine', 'guida', False),
    ('d2_lungo.jpg', ('D2_PVPA',), 'immagine', 'guida', False),
    ('dx6_eco.jpg', ('DX6_AP_PW', 'DX6_AP_CW'), 'immagine', 'guida', True),
    ('dx6_eco2.jpg', ('DX6_AP_PW', 'DX6_AP_CW'), 'immagine', 'guida', False),
    ('dx7_guida.jpg', ('DX7_MMODE',), 'immagine', 'guida', False),
    ('rif_pvpa_bmode.jpg', ('D2_PVPA',), 'immagine', 'guida', True),
    ('rif_sx_polmonare.jpg', ('SX4_AP_PW', 'SX4_AP_CW'), 'immagine', 'guida', True),
    ('sx4_eco.jpg', ('SX4_AP_PW', 'SX4_AP_CW'), 'immagine', 'guida', True),
    ('sx4_eco2.jpg', ('SX4_AP_PW', 'SX4_AP_CW'), 'immagine', 'guida', False),
]
# Righe che accettano un'immagine bidimensionale ferma: una guida finita li'
# non e' un «sicuro sbagliato» per forza (l'asse corto alla base E' un LA/Ao).
RIGHE_2D_STATICHE = ('DX5_LAAO', 'DX_LAD')


def _prima_immagine(riga_json):
    """Il nome del file della prima immagine di riferimento (il JSON accetta
    sia la stringa sia {file, didascalia})."""
    for voce in riga_json.get('immagini_riferimento') or []:
        nome = voce['file'] if isinstance(voce, dict) else voce
        if nome:
            return nome
    return None


def esemplari_dal_catalogo(righe, lato):
    """Gli esemplari del banco: la prima immagine di riferimento di ogni riga,
    letta da eco/catalogo/img/ (come fa il portale dal database). `chiave` e'
    il nome del file: cosi' la valutazione puo' escluderlo (leave-one-out)."""
    dati = json.loads((CARTELLA / 'catalogo_eco.json').read_text(encoding='utf-8'))['righe']
    per_codice = {r.codice: r for r in righe}
    esemplari = []
    for riga_json in dati:
        riga = per_codice.get(riga_json['codice'])
        nome = _prima_immagine(riga_json)
        if riga is None or riga.libera or not nome:
            continue
        esemplari.append(Esemplare(codice=riga.codice, nome=riga.nome,
                                   descrizione=modulo_esemplari.descrizione(riga),
                                   dati=jpeg_ridotto(CARTELLA / 'img' / nome, lato_max=lato), chiave=nome))
    return esemplari


def righe_dal_catalogo():
    """Le righe dal JSON del catalogo (nessun database), nell'ordine del passo 3."""
    dati = json.loads((CARTELLA / 'catalogo_eco.json').read_text(encoding='utf-8'))['righe']
    campi = ('codice', 'nome', 'finestra', 'tipo_media', 'obbligatoria', 'ordine', 'istruzioni',
             'deve_essere_visibile')
    proiezioni = []
    for i, r in enumerate(dati, start=1):
        p = ProiezioneCatalogo(**{k: r.get(k, '') for k in campi})
        p.libera = bool(r.get('libera'))
        p.id = i
        proiezioni.append(p)
    return righe_catalogo.da_catalogo(in_ordine(proiezioni))


class Command(BaseCommand):
    help = 'Misura lo smistamento automatico sul banco di immagini ecografiche vere del catalogo (API vera).'

    def add_arguments(self, parser):
        parser.add_argument('--modello', default=settings.CONSULTI_MODELLO_SMISTAMENTO)
        parser.add_argument('--effort', default=getattr(settings, 'CONSULTI_SMISTAMENTO_EFFORT', 'medium'))
        parser.add_argument('--taglio', type=float, default=getattr(settings, 'CONSULTI_SMISTAMENTO_TAGLIO_ALTO', 0.0),
                            help='Frazione tolta in alto prima dell\'invio (0 = niente).')
        parser.add_argument('--ordine', choices=('mescolato', 'protocollo'), default='mescolato',
                            help='mescolato: ordine casuale (seme fisso); protocollo: nell\'ordine del protocollo.')
        parser.add_argument('--seme', type=int, default=11)
        parser.add_argument('--esemplari', choices=('si', 'no'), default='si',
                            help='si: manda anche le immagini di riferimento delle righe (prefisso in cache).')
        parser.add_argument('--esemplari-px', type=int, default=modulo_esemplari.LATO_ESEMPLARE)
        parser.add_argument('--json', help='Salva qui i risultati per file (JSON).')

    def handle(self, *args, **opzioni):
        righe = righe_dal_catalogo()
        per_codice = {r.codice: r for r in righe}
        banco = list(BANCO)
        if opzioni['ordine'] == 'mescolato':
            random.Random(opzioni['seme']).shuffle(banco)
        else:
            banco.sort(key=lambda b: min(per_codice[c].ordine for c in b[1]))
        con_esemplari = opzioni['esemplari'] == 'si'
        esemplari = esemplari_dal_catalogo(righe, opzioni['esemplari_px']) if con_esemplari else []
        files, verita = [], {}
        for i, (nome, giuste, genere, gruppo, scritte) in enumerate(banco, start=1):
            neutro = f'IMG_{i:04d}.{"mp4" if genere == "video" else "jpg"}'
            anteprima = jpeg_ridotto(CARTELLA / 'img' / nome)
            # LEAVE-ONE-OUT: il banco e' fatto delle stesse immagini di
            # riferimento. Per questo file si tolgono dagli esemplari la sua
            # stessa immagine (ovunque compaia) e l'esemplare della sua riga
            # vera: senza, il modello riconoscerebbe se stesso e il numero non
            # varrebbe niente.
            escludi = tuple({e.chiave for e in esemplari if e.chiave == nome or e.codice in giuste})
            files.append(FileEsame(id=i, nome=neutro, genere=genere, anteprima=anteprima, percorso=neutro,
                                   escludi_esemplari=escludi))
            verita[i] = {'file': nome, 'neutro': neutro, 'giuste': giuste, 'genere': genere, 'gruppo': gruppo,
                         'scritte': scritte, 'esemplari_esclusi': list(escludi)}
        lettore = LettoreClaude(opzioni['modello'], effort=opzioni['effort'], taglio_alto=opzioni['taglio'],
                                esemplari=(lambda _righe: esemplari) if con_esemplari else None,
                                timeout=getattr(settings, 'CONSULTI_SMISTAMENTO_TIMEOUT', 180.0),
                                per_richiesta=getattr(settings, 'CONSULTI_SMISTAMENTO_PER_RICHIESTA', 8),
                                prezzi=getattr(settings, 'CONSULTI_PREZZI_MODELLI', {}))
        inizio = time.monotonic()
        risultato = motore.smista(files, righe, lettore)
        durata = time.monotonic() - inizio
        # Gradi 1 e 2 (senza AI): quante righe restano possibili per file, e se
        # la riga giusta e' sempre fra quelle (il colore dai pixel l'ha misurato il motore).
        for f in files:
            possibili = [r.codice for r in motore.candidati(f, righe)]
            verita[f.id].update(n_possibili=len(possibili),
                                giusta_fra_possibili=any(c in possibili for c in verita[f.id]['giuste']))
        self._rapporto(risultato, verita, righe, opzioni, durata)

    # ── Rapporto ─────────────────────────────────────────────────────────
    def _rapporto(self, risultato, verita, righe, opzioni, durata):
        per_id = {r.id: r for r in righe}
        per_codice = {r.codice: r for r in righe}
        proposte = {p.file_id: p for p in risultato.proposte}
        esiti = []
        for fid, v in verita.items():
            lettura = risultato.letture.get(fid)
            p = proposte[fid]
            proposta = per_id[p.riga_id].codice if p.riga_id else None
            tracciato_vero = per_codice[v['giuste'][0]].tracciato
            esiti.append({
                **v, 'giuste': list(v['giuste']),
                'lettura': lettura.codice if lettura else None,
                'confidenza': lettura.confidenza if lettura else None,
                'seconda': lettura.seconda if lettura else None,
                'tracciato_letto': lettura.tracciato if lettura else None,
                'tracciato_vero': tracciato_vero,
                'motivo': lettura.motivo if lettura else '',
                'proposta': proposta, 'sicura': p.sicura, 'fonte': p.fonte, 'colore': p.colore,
                'finestra': per_codice[v['giuste'][0]].finestra,
            })
        t = risultato.telemetria
        o = self.stdout.write
        o(f'\nSmistamento sul banco — modello {opzioni["modello"]}, effort {opzioni["effort"]}, '
          f'taglio in alto {opzioni["taglio"]:.0%}, ordine {opzioni["ordine"]}, '
          f'esemplari {opzioni["esemplari"]} ({t.get("esemplari", 0)} a {opzioni["esemplari_px"]} px, '
          f'leave-one-out)')
        senza = t.get('righe_senza_esemplare') or []
        if t.get('esemplari'):
            per_richiesta = t.get('esemplari_per_richiesta') or []
            media = sum(per_richiesta) / len(per_richiesta) if per_richiesta else 0
            o(f'Esemplari mostrati: {media:.1f} su {t["esemplari"]} per richiesta ({per_richiesta}); righe rimaste '
              f'senza esemplare in almeno una richiesta per colpa del leave-one-out: {len(senza)}'
              + (f' — {", ".join(senza)}' if senza else ''))
            o('  (per ogni file del banco l\'esemplare della SUA riga e\' sempre escluso: il guadagno misurato '
              'qui e\' quindi un limite inferiore, in produzione l\'esemplare giusto c\'e\')')
        if risultato.messaggio:
            o(f'Messaggio: {risultato.messaggio}')
        o(f'Richieste {t.get("richieste")}, immagini lette {t.get("immagini")}, token in {t.get("token_input")} '
          f'+ cache {t.get("token_cache_scrittura")}/{t.get("token_cache_lettura")}, out {t.get("token_output")}, '
          f'costo stimato $ {t.get("costo_usd")}, durata {durata:.1f} s, errori {t.get("errori")}')
        immagini = t.get('immagini') or 1
        o(f'Per un esame da 27 file (26 immagini + il PDF): circa $ {t.get("costo_usd", 0) / immagini * 26:.3f}')

        def percentuale(n, d):
            return f'{n}/{d} ({(n / d if d else 0):.0%})'

        obbligatorie = sum(1 for r in righe if not r.libera)
        filmati = [e for e in esiti if e['genere'] == 'video']
        immagini_ = [e for e in esiti if e['genere'] != 'video']
        o(f'Gradi 1-2 (formato e pixel, senza AI): righe possibili per file, su {obbligatorie}: filmati '
          f'{sum(e["n_possibili"] for e in filmati) / max(1, len(filmati)):.1f}, immagini '
          f'{sum(e["n_possibili"] for e in immagini_) / max(1, len(immagini_)):.1f}; riga giusta fra le possibili '
          f'{percentuale(sum(1 for e in esiti if e["giusta_fra_possibili"]), len(esiti))}; colore dei fotogrammi '
          f'di filmato (tutti B-mode veri): ' + ', '.join(f'{k} {n}' for k, n in Counter(e['colore'] for e in filmati).items()))

        if not risultato.lettura_ai:
            o(self.style.WARNING('\nLettura AI non eseguita (vedi il messaggio): serve ANTHROPIC_API_KEY valida. '
                                 'Qui sopra solo i gradi 1-2.'))
            self._salva(opzioni, t, durata, risultato, esiti)
            return
        for nome_gruppo in ('principale', 'guida'):
            gruppo = [e for e in esiti if e['gruppo'] == nome_gruppo]
            giuste_lettura = sum(1 for e in gruppo if e['lettura'] in e['giuste'])
            sconosciute = sum(1 for e in gruppo if e['lettura'] is None)
            sicure = [e for e in gruppo if e['sicura']]
            if nome_gruppo == 'guida':
                sicure_sbagliate = [e for e in sicure if e['proposta'] not in e['giuste']
                                    and e['proposta'] not in RIGHE_2D_STATICHE]
            else:
                sicure_sbagliate = [e for e in sicure if e['proposta'] not in e['giuste']]
            messe = [e for e in gruppo if e['proposta']]
            o(f'\n== Gruppo {nome_gruppo} ({len(gruppo)} file) ==')
            o(f'Lettura AI: riga giusta {percentuale(giuste_lettura, len(gruppo))}, «sconosciuto» {sconosciute}')
            o(f'Tracciato letto giusto: {percentuale(sum(1 for e in gruppo if e["tracciato_letto"] == e["tracciato_vero"]), len(gruppo))}')
            o(f'Proposta finale (dopo ordine e assegnazione): in una riga {len(messe)}, giusta '
              f'{sum(1 for e in messe if e["proposta"] in e["giuste"])}, sbagliata '
              f'{sum(1 for e in messe if e["proposta"] not in e["giuste"])}, da smistare {len(gruppo) - len(messe)}')
            o(f'«Sicuro»: {len(sicure)}, di cui sbagliati {len(sicure_sbagliate)}'
              + (f' ({", ".join(e["neutro"] + "=" + e["file"] + "->" + str(e["proposta"]) for e in sicure_sbagliate)})'
                 if sicure_sbagliate else ''))
            if nome_gruppo == 'principale':
                pulite = [e for e in gruppo if not e['scritte']]
                o(f'Senza le immagini con scritte che aiutano: riga giusta '
                  f'{percentuale(sum(1 for e in pulite if e["lettura"] in e["giuste"]), len(pulite))}')
                per_tracciato = defaultdict(list)
                per_finestra = defaultdict(list)
                for e in gruppo:
                    per_tracciato[e['tracciato_vero']].append(e['lettura'] in e['giuste'])
                    per_finestra[e['finestra']].append(e['lettura'] in e['giuste'])
                o('Per tipo di tracciato: ' + '; '.join(
                    f'{NOMI_TRACCIATO[k]} {percentuale(sum(v), len(v))}' for k, v in per_tracciato.items()))
                o('Per finestra: ' + '; '.join(f'{k} {percentuale(sum(v), len(v))}' for k, v in per_finestra.items()))
            confusioni = Counter(f'{"/".join(e["giuste"])} -> {e["lettura"] or "sconosciuto"}'
                                 for e in gruppo if e['lettura'] not in e['giuste'])
            if confusioni:
                o('Confusioni: ' + '; '.join(f'{k} (x{n})' for k, n in confusioni.most_common()))
        o('\nPer file:')
        for e in sorted(esiti, key=lambda e: e['neutro']):
            o(f'  {e["neutro"]} {e["file"]:22s} {e["gruppo"]:10s} vero {"/".join(e["giuste"]):22s} '
              f'letto {str(e["lettura"]):12s} {str(e["confidenza"]):5s} {str(e["tracciato_letto"]):4s} '
              f'-> {str(e["proposta"]):12s} {"SICURO" if e["sicura"] else "      "} {e["fonte"]:6s} «{e["motivo"]}»')
        self._salva(opzioni, t, durata, risultato, esiti)

    def _salva(self, opzioni, t, durata, risultato, esiti):
        if not opzioni.get('json'):
            return
        Path(opzioni['json']).write_text(json.dumps(
            {'opzioni': {k: opzioni[k] for k in ('modello', 'effort', 'taglio', 'ordine', 'seme', 'esemplari',
                                                 'esemplari_px')},
             'telemetria': t, 'durata_s': round(durata, 1), 'messaggio': risultato.messaggio, 'file': esiti},
            ensure_ascii=False, indent=1), encoding='utf-8')
        self.stdout.write(f'\nRisultati in {opzioni["json"]}')
