"""
Quanto ci prende lo smistamento automatico sugli esami VERI.

    manage.py accuratezza_smistamento [--da 2026-09-15] [--json misure.json]

## Da dove vengono i numeri

Non da un banco di prova: da cio' che i colleghi hanno confermato. Ogni
«Confermo lo smistamento» e' una correzione umana, cioe' la verita' — chi ha
caricato i file sa dove vanno. Lo smistamento fotografa la sua proposta
appena finisce e la conferma scrive dove il file e' finito davvero
(eco/smistamento/esiti.py, modello EsitoSmistamento).

E' la risposta alla domanda che `manage.py valuta_smistamento` non puo'
dare: quel banco e' fatto con le immagini di riferimento del catalogo, che
vengono da una presentazione e hanno intestazioni pulite. Qui ci sono i file
degli ecografi dei colleghi, con i loro nomi e le loro intestazioni.

## I numeri che contano

- **«Sicuri» sbagliati**: un file messo in una riga con il bollino «sicuro»
  che il collega ha dovuto spostare. E' il numero che decide se la soglia di
  «sicuro» (0,85) e' giusta: un «sicuro» sbagliato puo' sfuggire.
- **Riga giusta** sulle proposte fatte, e su tutti i file.
- **Quante volte l'AI non ha saputo assegnare**: costa un gesto al collega,
  ma e' l'errore buono.

## Attenzione al collaudo

Gli esami di `seed_demo` e le prove di Andre finiscono in tabella come gli
altri. `--da` e' il modo di lasciarli fuori: si da' la data del primo esame
vero.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from eco.models import EsitoSmistamento, Finestra, ProiezioneCatalogo


def percentuale(n, d):
    return f'{n}/{d} ({(n / d if d else 0):.0%})'


class Command(BaseCommand):
    help = ('Accuratezza dello smistamento automatico dell\'eco misurata sulle conferme dei colleghi '
            '(ogni conferma e\' una correzione umana).')

    def add_arguments(self, parser):
        parser.add_argument('--da', help='Solo le conferme da questa data in poi (AAAA-MM-GG): '
                                         'serve a lasciare fuori il collaudo.')
        parser.add_argument('--json', help='Scrive anche i numeri in un file JSON.')

    def handle(self, *args, **opzioni):
        esiti = EsitoSmistamento.objects.filter(confermato_il__isnull=False)
        da = None
        if opzioni.get('da'):
            try:
                da = datetime.strptime(opzioni['da'], '%Y-%m-%d')
            except ValueError:
                raise CommandError('La data va scritta AAAA-MM-GG (per esempio 2026-09-15).')
            da = timezone.make_aware(da)
            esiti = esiti.filter(confermato_il__gte=da)
        esiti = list(esiti)
        if not esiti:
            self.stdout.write(self.style.WARNING(
                'Nessun esame ancora: nessuno smistamento e\' stato confermato'
                + (f' dal {opzioni["da"]}' if da else '') + '.'))
            self.stdout.write(
                'La tabella si riempie da sola: ogni «Confermo lo smistamento» di un\'eco vera lascia una riga '
                'per file. Quando ci saranno tre o quattro esami veri, rilancia questo comando e guarda i '
                '«sicuri» sbagliati prima di toccare la soglia o il modello.')
            return

        numeri = self._conta(esiti)
        self._stampa(numeri, esiti, da)
        if opzioni.get('json'):
            Path(opzioni['json']).write_text(
                json.dumps(numeri, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
            self.stdout.write(f'\nNumeri in {opzioni["json"]}')

    # ── I conti ─────────────────────────────────────────────────────────────
    def _conta(self, esiti):
        etichette = dict(Finestra.choices)
        finestre = {c: etichette.get(f, f)
                    for c, f in ProiezioneCatalogo.objects.values_list('codice', 'finestra')}
        nomi = dict(ProiezioneCatalogo.objects.values_list('codice', 'nome'))
        proposti = [e for e in esiti if e.dove_proponeva]
        giusti = [e for e in proposti if not e.corretto]
        sicuri = [e for e in proposti if e.sicura]
        da_verificare = [e for e in proposti if not e.sicura]

        per_riga = defaultdict(lambda: [0, 0])       # verita' -> [giusti, totali]
        per_finestra = defaultdict(lambda: [0, 0])
        for e in esiti:
            vero = e.dove_e_finito
            if not vero:
                continue
            giusto = e.dove_proponeva == vero
            per_riga[vero][0] += giusto
            per_riga[vero][1] += 1
            finestra = finestre.get(vero, 'referto dell\'ecografo' if vero == 'referto' else 'fuori catalogo')
            per_finestra[finestra][0] += giusto
            per_finestra[finestra][1] += 1

        confusioni = Counter(f'{e.dove_e_finito or "da smistare"} <- {e.dove_proponeva}'
                             for e in proposti if e.corretto)
        return {
            'esami': len(set(e.codice_richiesta for e in esiti)),
            'file': len(esiti),
            'dal': min(e.confermato_il for e in esiti),
            'al': max(e.confermato_il for e in esiti),
            'modelli': dict(Counter(e.modello or 'senza AI' for e in esiti)),
            'proposti': len(proposti),
            'non_assegnati': len(esiti) - len(proposti),
            'giusti': len(giusti),
            'corretti_dall_umano': len(proposti) - len(giusti),
            'sicuri': len(sicuri),
            'sicuri_sbagliati': sum(1 for e in sicuri if e.corretto),
            'da_verificare': len(da_verificare),
            'da_verificare_sbagliati': sum(1 for e in da_verificare if e.corretto),
            'per_fonte': {fonte: [sum(1 for e in gruppo if not e.corretto), len(gruppo)]
                          for fonte, gruppo in self._per(proposti, lambda e: e.fonte or 'nessuna').items()},
            'per_riga': {nomi.get(k, k): v for k, v in sorted(per_riga.items())},
            'per_finestra': dict(sorted(per_finestra.items())),
            'confusioni': confusioni.most_common(10),
            'tracciati': dict(Counter(e.tracciato or 'non letto' for e in esiti)),
        }

    @staticmethod
    def _per(esiti, chiave):
        gruppi = defaultdict(list)
        for e in esiti:
            gruppi[chiave(e)].append(e)
        return gruppi

    # ── La stampa ───────────────────────────────────────────────────────────
    def _stampa(self, n, esiti, da):
        o = self.stdout.write
        esami = 'un esame' if n['esami'] == 1 else f'{n["esami"]} esami'
        o(f'Smistamento automatico su esami veri: {n["file"]} file in {esami}, confermati fra il '
          f'{n["dal"]:%d/%m/%Y} e il {n["al"]:%d/%m/%Y}' + (f' (dal {da:%d/%m/%Y} in poi)' if da else '') + '.')
        o('Modello: ' + ', '.join(f'{k} ({v} file)' for k, v in n['modelli'].items()))
        if n['esami'] < 3:
            quanti = 'un esame solo' if n['esami'] == 1 else f'{n["esami"]} esami'
            o(self.style.WARNING(f'Attenzione: {quanti}. I numeri qui sotto sono un\'indicazione, '
                                 'non una misura: con meno di tre o quattro esami un file sposta le percentuali.'))

        o('\n== Quanto ci prende ==')
        o(f'Proposta fatta: {percentuale(n["proposti"], n["file"])} — gli altri {n["non_assegnati"]} file '
          f'l\'automatismo non ha saputo assegnarli e li ha lasciati da smistare.')
        o(f'Riga giusta sulle proposte fatte: {percentuale(n["giusti"], n["proposti"])}')
        o(f'Riga giusta su tutti i file:      {percentuale(n["giusti"], n["file"])}')
        o(f'Corretti a mano dal collega:      {n["corretti_dall_umano"]}')

        o('\n== Per livello di sicurezza ==')
        o(f'«Sicuro»:       {percentuale(n["sicuri"] - n["sicuri_sbagliati"], n["sicuri"])} giusti')
        o(f'«Da verificare»: {percentuale(n["da_verificare"] - n["da_verificare_sbagliati"], n["da_verificare"])} giusti')
        frase = f'«Sicuri» sbagliati: {n["sicuri_sbagliati"]}'
        o(self.style.ERROR(frase + '  <- il numero che conta') if n['sicuri_sbagliati']
          else self.style.SUCCESS(frase + ' — nessun file col bollino «sicuro» e\' stato spostato.'))

        o('\n== Per fonte della proposta ==')
        for fonte, (giusti, totali) in sorted(n['per_fonte'].items()):
            o(f'  {fonte:8s} {percentuale(giusti, totali)}')

        o('\n== Per finestra (la verita\' e\' la riga confermata) ==')
        for finestra, (giusti, totali) in n['per_finestra'].items():
            o(f'  {finestra:42s} {percentuale(giusti, totali)}')

        o('\n== Per riga del catalogo ==')
        for riga, (giusti, totali) in n['per_riga'].items():
            o(f'  {riga:45s} {percentuale(giusti, totali)}')

        if n['confusioni']:
            o('\n== Confusioni piu\' frequenti (dove doveva andare <- dove l\'aveva messo) ==')
            for confusione, quante in n['confusioni']:
                o(f'  {confusione}  (x{quante})')

        o('\nTipo di tracciato letto: ' + ', '.join(f'{k} {v}' for k, v in sorted(n['tracciati'].items())))
        o('\nLe decisioni che questi numeri devono sbloccare (docs/BACKLOG.md): la soglia di «sicuro» (oggi 0,85) '
          'e il modello (oggi Opus 5, ~$ 0,2 a esame).')
