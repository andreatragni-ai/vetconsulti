"""
I file di un caso nell'ordine in cui li legge chi referta, non in quello
di caricamento (collaudo dell'11/09/2026: 26 riquadri in fila erano
confusi). Lo usano la pagina di refertazione (il visore) e la pagina del
caso.

- **Eco**: il referto dell'ecografo in testa; poi un gruppo per finestra
  acustica nell'ordine del catalogo (Parasternale destra, Sottoxifoidea,
  Parasternale sinistra, eventuali «Altre proiezioni», Filmati liberi);
  dentro ogni finestra prima i filmati poi le immagini, ciascuno
  nell'ordine delle righe del catalogo (`ProiezioneCatalogo.chiave_ordine`).
- **ECG**: i tracciati PDF, poi le foto. **Holter**: il referto del
  software, poi il file dell'apparecchio. Pochi file: un gruppo solo,
  senza titolo.
- In fondo «Altri file»: cio' che non sta in nessun posto previsto (per
  esempio da una versione vecchia del portale).

`gruppi_file` ritorna [{etichetta, voci}] (etichetta '' = senza titolo),
ogni voce {allegato, genere, filmato, proiezione, nota, miniatura}:
`miniatura` e' l'indirizzo protetto dell'immagine da mostrare in piccolo
(oggi l'immagine stessa; per i filmati None, finche' il lavoro sullo
smistamento non ne produce una). Gli allegati SCARTATO non ci sono.
"""

from django.urls import reverse

from core.tipi import TipoEsame
from .models import CategoriaAllegato, StatoAllegato

ORDINE_ECG = (CategoriaAllegato.ECG_PDF, CategoriaAllegato.ECG_IMMAGINE)
ORDINE_HOLTER = (CategoriaAllegato.HOLTER_REFERTO, CategoriaAllegato.HOLTER_FILE)


def _voce(allegato, pc=None):
    genere = allegato.genere
    miniatura = f'{reverse("scarica_allegato", args=[allegato.pk])}?inline=1' if genere == 'immagine' else None
    return {
        'allegato': allegato,
        'genere': genere,
        'filmato': allegato.categoria == CategoriaAllegato.ECO_CLIP or genere == 'video',
        'proiezione': pc.proiezione.nome if pc else None,
        'nota': pc.nota if pc else '',
        'miniatura': miniatura,
    }


def _per_categoria(allegati, ordine):
    """Prima le categorie di `ordine`, nell'ordine dato; poi il resto."""
    posto = {c: i for i, c in enumerate(ordine)}
    return sorted(allegati, key=lambda a: posto.get(a.categoria, len(ordine)))


def gruppi_file(richiesta):
    from eco.models import ORDINE_FINESTRE, Finestra

    allegati = list(richiesta.allegati.exclude(stato=StatoAllegato.SCARTATO).order_by('caricato_il', 'pk'))
    if richiesta.tipo_esame == TipoEsame.ECG:
        return [{'etichetta': '', 'voci': [_voce(a) for a in _per_categoria(allegati, ORDINE_ECG)]}] \
            if allegati else []
    if richiesta.tipo_esame == TipoEsame.HOLTER:
        return [{'etichetta': '', 'voci': [_voce(a) for a in _per_categoria(allegati, ORDINE_HOLTER)]}] \
            if allegati else []

    proiezioni = {}
    for pc in richiesta.proiezioni.select_related('proiezione').order_by('pk'):
        proiezioni.setdefault(pc.allegato_id, pc)
    referti = [a for a in allegati if a.categoria == CategoriaAllegato.ECO_REFERTO_PDF]
    per_finestra, liberi, altri = {}, [], []
    for a in allegati:
        if a in referti:
            continue
        pc = proiezioni.get(a.id)
        if pc is None:
            altri.append(a)
        elif pc.proiezione.libera:
            liberi.append(a)
        else:
            per_finestra.setdefault(pc.proiezione.finestra, []).append(a)

    def in_ordine(lista):
        # Filmati prima delle immagini, poi l'ordine delle righe del catalogo.
        voci = [_voce(a, proiezioni.get(a.id)) for a in lista]
        return sorted(voci, key=lambda v: (not v['filmato'], proiezioni[v['allegato'].id].proiezione.chiave_ordine()))

    gruppi = []
    if referti:
        gruppi.append({'etichetta': 'Referto dell\'ecografo', 'voci': [_voce(a) for a in referti]})
    for finestra in ORDINE_FINESTRE:
        if per_finestra.get(finestra):
            etichetta = 'Altre proiezioni' if finestra == Finestra.ALTRO else Finestra(finestra).label
            gruppi.append({'etichetta': etichetta, 'voci': in_ordine(per_finestra[finestra])})
    if liberi:
        gruppi.append({'etichetta': Finestra.ALTRO.label, 'voci': in_ordine(liberi)})
    if altri:
        gruppi.append({'etichetta': 'Altri file', 'voci': [_voce(a) for a in altri]})
    return gruppi


def voci_in_ordine(richiesta):
    """Le voci di `gruppi_file` in fila, con l'etichetta del gruppo accanto."""
    return [{**v, 'gruppo': g['etichetta']} for g in gruppi_file(richiesta) for v in g['voci']]
