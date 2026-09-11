"""Carica (o aggiorna) il catalogo delle proiezioni eco da un file JSON.

    manage.py carica_catalogo_eco [eco/catalogo/catalogo_eco.json] [--immagini eco/catalogo/img]

Il file e' quello che scrive Andre (`eco/catalogo/catalogo_eco.json`, in
git con le immagini): `{"versione", "righe": [{codice, finestra, nome,
tipo_media, obbligatoria, libera, ordine, istruzioni, deve_essere_visibile,
serve_per, immagini_riferimento: [file...], nota_riferimento,
scheda_guida}]}`.

Idempotente: ogni riga si aggiorna per `codice` (update_or_create) e le sue
immagini di riferimento si sostituiscono con quelle elencate, nell'ordine
del file. Le voci che nel file non ci sono piu' si DISATTIVANO, non si
cancellano (le richieste vecchie le referenziano): `--senza-disattivare`
per non toccarle. Prima di scrivere controlla tutto (codici doppi, finestre
e tipi sconosciuti, immagini mancanti, filmati liberi segnati obbligatori):
un file sbagliato non lascia un catalogo a meta'.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from eco.models import Finestra, ImmagineRiferimento, ProiezioneCatalogo, TipoMedia

CATALOGO_PREDEFINITO = Path(settings.BASE_DIR) / 'eco' / 'catalogo' / 'catalogo_eco.json'

# Didascalia dal suffisso del nome del file (dx1_sonda.jpg -> «Posizione della sonda»).
DIDASCALIE = {
    'eco': 'Immagine ecografica', 'eco2': 'Immagine ecografica', 'schema': 'Schema',
    'sonda': 'Posizione della sonda', 'misura': 'Come si misura', 'svedese': 'Misura con il metodo svedese',
    'rx': 'Radiografia', 'pw': 'Doppler pulsato', 'ao': 'Aorta', '3d': 'Modello tridimensionale',
    'corto': 'Asse corto', 'lungo': 'Asse lungo', 'mmode': 'M-mode', 'guida': 'Guida',
}
TESTI = ('istruzioni', 'deve_essere_visibile', 'serve_per', 'nota_riferimento', 'scheda_guida', 'descrizione')


def didascalia(nome_file):
    suffisso = Path(nome_file).stem.rsplit('_', 1)[-1].lower()
    return DIDASCALIE.get(suffisso, '')


class Command(BaseCommand):
    help = 'Carica o aggiorna il catalogo delle proiezioni eco da un file JSON (con le immagini di riferimento).'

    def add_arguments(self, parser):
        parser.add_argument('file', nargs='?', default=str(CATALOGO_PREDEFINITO),
                            help='File JSON del catalogo (predefinito: eco/catalogo/catalogo_eco.json).')
        parser.add_argument('--immagini', default=None,
                            help='Cartella delle immagini di riferimento (predefinita: img/ accanto al file).')
        parser.add_argument('--senza-disattivare', action='store_true',
                            help='Non disattivare le voci che nel file non ci sono piu\'.')

    def handle(self, *args, **opzioni):
        percorso = Path(opzioni['file'])
        if not percorso.is_file():
            raise CommandError(f'File del catalogo non trovato: {percorso}')
        cartella = Path(opzioni['immagini']) if opzioni['immagini'] else percorso.parent / 'img'
        dati = json.loads(percorso.read_text(encoding='utf-8'))
        righe = dati['righe'] if isinstance(dati, dict) else dati
        self._controlla(righe, cartella)

        vecchi_file = []
        n_immagini = 0
        with transaction.atomic():
            for riga in righe:
                valori = {
                    'nome': riga['nome'], 'finestra': riga['finestra'], 'tipo_media': riga['tipo_media'],
                    'obbligatoria': bool(riga.get('obbligatoria')), 'libera': bool(riga.get('libera')),
                    'ordine': int(riga.get('ordine') or 0), 'attiva': riga.get('attiva', True),
                    **{campo: (riga.get(campo) or '').strip() for campo in TESTI},
                }
                proiezione, _ = ProiezioneCatalogo.objects.update_or_create(codice=riga['codice'], defaults=valori)
                for vecchia in proiezione.immagini.all():
                    vecchi_file.append(vecchia.immagine.name)
                    vecchia.delete()
                for ordine, nome in enumerate(riga.get('immagini_riferimento') or [], start=1):
                    immagine = ImmagineRiferimento(proiezione=proiezione, ordine=ordine, didascalia=didascalia(nome))
                    with open(cartella / nome, 'rb') as f:
                        immagine.immagine.save(nome, File(f), save=True)
                    n_immagini += 1
            codici = [r['codice'] for r in righe]
            disattivate = []
            if not opzioni['senza_disattivare']:
                fuori = ProiezioneCatalogo.objects.exclude(codice__in=codici).filter(attiva=True)
                disattivate = list(fuori.values_list('codice', flat=True))
                fuori.update(attiva=False)
            # I file delle immagini sostituite si cancellano solo a transazione riuscita.
            transaction.on_commit(lambda: self._cancella(vecchi_file))

        obbligatorie = sum(1 for r in righe if r.get('obbligatoria'))
        libere = sum(1 for r in righe if r.get('libera'))
        self.stdout.write(
            f'Catalogo eco {dati.get("versione", "") if isinstance(dati, dict) else ""}: {len(righe)} righe '
            f'({obbligatorie} obbligatorie, {libere} filmati liberi), {n_immagini} immagini di riferimento.')
        if disattivate:
            self.stdout.write(f'Disattivate perche\' non piu\' nel file: {", ".join(disattivate)}.')

    def _controlla(self, righe, cartella):
        errori = []
        visti = set()
        for i, riga in enumerate(righe, start=1):
            codice = riga.get('codice') or f'(riga {i})'
            if not riga.get('codice') or not riga.get('nome'):
                errori.append(f'{codice}: mancano codice o nome.')
            if codice in visti:
                errori.append(f'{codice}: codice doppio.')
            visti.add(codice)
            if riga.get('finestra') not in Finestra.values:
                errori.append(f'{codice}: finestra sconosciuta «{riga.get("finestra")}».')
            if riga.get('tipo_media') not in TipoMedia.values:
                errori.append(f'{codice}: tipo_media sconosciuto «{riga.get("tipo_media")}».')
            if riga.get('libera') and riga.get('obbligatoria'):
                errori.append(f'{codice}: un filmato libero non puo\' essere obbligatorio.')
            for nome in riga.get('immagini_riferimento') or []:
                if not (cartella / nome).is_file():
                    errori.append(f'{codice}: immagine {nome} non trovata in {cartella}.')
        if errori:
            raise CommandError('Catalogo non caricato:\n  ' + '\n  '.join(errori))

    @staticmethod
    def _cancella(nomi):
        from django.core.files.storage import default_storage
        for nome in nomi:
            if nome and not ImmagineRiferimento.objects.filter(immagine=nome).exists():
                default_storage.delete(nome)
