"""
Gli esemplari: l'immagine di riferimento di ogni riga del protocollo,
mostrata al modello insieme alle miniature da riconoscere.

Descrivere a parole «asse lungo 4 camere» dice al modello cosa cercare; far
vedere com'e' fatta quella proiezione sull'ecografo dice molto di piu'. Gli
esemplari sono le stesse immagini che il collega vede accanto a ogni riga
nel passo 3 (eco.ImmagineRiferimento, la prima per `ordine`), ridotte a
320 px sul lato lungo: una manciata di token l'una.

Stanno in testa alla richiesta, in un **prefisso stabile** marcato con
`cache_control`: si pagano una volta e le richieste successive (gli altri
gruppi dello stesso esame, e gli esami dei giorni dopo finche' la cache
dura) li leggono a un decimo del prezzo.

Non tutte le righe hanno un'immagine di riferimento buona come esemplare:
qui si prende solo la prima immagine di ogni riga attiva non libera, e le
righe senza restano descritte a parole nel prompt di sistema.

## Misurato, e spento

Sul banco di prova (3 semi, Claude Opus 5, 12/09/2026), con il leave-one-out
obbligatorio (l'esemplare della riga vera di ogni file va tolto, altrimenti il
modello riconosce se stesso): riga giusta 10,7 su 17 contro 10,3 senza
esemplari — dentro il rumore —, «sconosciuto» 1,0 contro 3,3, ma file finiti
nella riga SBAGLIATA 5,0 contro 2,7, e costo +30 %. Cioe': il confronto visivo
fa indovinare di piu' invece di ammettere di non sapere. Per questo
`CONSULTI_SMISTAMENTO_ESEMPLARI` e' False: il codice resta pronto e si
rimisura quando il banco avra' immagini vere non usate come riferimento.

Il banco di prova e' fatto con le stesse immagini: `chiave` identifica
l'immagine sorgente cosi' che la valutazione possa escluderla
(leave-one-out, vedi `manage.py valuta_smistamento`).
"""

import logging

from .dati import NOMI_TRACCIATO, Esemplare

logger = logging.getLogger('eco')

LATO_ESEMPLARE = 320
# {(pk immagine, lato): byte} — le immagini del catalogo cambiano di rado e
# ridurle costa; il processo le tiene in memoria.
_cache = {}


def descrizione(riga):
    media = {'CLIP': 'filmato', 'STATICA': 'immagine', 'ENTRAMBI': 'filmato o immagine'}.get(riga.tipo_media, '')
    colore = {'color': 'con color Doppler', 'bmode': 'senza colore'}.get(riga.colore or '', '')
    parti = [riga.finestra, media, NOMI_TRACCIATO.get(riga.tracciato, riga.tracciato), colore]
    return ', '.join(p for p in parti if p)


def da_catalogo(righe, lato=LATO_ESEMPLARE):
    """Gli esemplari delle righe (dal database: ImmagineRiferimento), saltando
    quelle senza immagine e quelle libere. Un'immagine illeggibile si salta
    con un avviso: la riga resta descritta solo a parole."""
    from consulti.anteprime import AnteprimaNonValida, jpeg_ridotto
    from eco.models import ImmagineRiferimento

    codici = [r.codice for r in righe if not r.libera]
    per_codice = {r.codice: r for r in righe}
    prime = {}
    for im in ImmagineRiferimento.objects.filter(proiezione__codice__in=codici).order_by('ordine', 'pk') \
            .select_related('proiezione'):
        prime.setdefault(im.proiezione.codice, im)
    esemplari = []
    for codice in codici:
        im = prime.get(codice)
        if im is None or not im.immagine:
            continue
        chiave = (im.pk, lato)
        if chiave not in _cache:
            try:
                with im.immagine.open('rb') as f:
                    _cache[chiave] = jpeg_ridotto(f, lato_max=lato)
            except (OSError, AnteprimaNonValida) as e:
                logger.warning('Esemplare non leggibile per %s: %s', codice, e)
                _cache[chiave] = None
        if _cache[chiave] is None:
            continue
        riga = per_codice[codice]
        esemplari.append(Esemplare(codice=codice, nome=riga.nome, descrizione=descrizione(riga),
                                   dati=_cache[chiave], chiave=f'riferimento:{im.pk}'))
    return esemplari


def da_settings(righe):
    """Gli esemplari se sono accesi in settings, altrimenti nessuno."""
    from django.conf import settings
    if not getattr(settings, 'CONSULTI_SMISTAMENTO_ESEMPLARI', True):
        return []
    return da_catalogo(righe, lato=getattr(settings, 'CONSULTI_SMISTAMENTO_ESEMPLARI_PX', LATO_ESEMPLARE))
