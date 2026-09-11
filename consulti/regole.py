"""
Regole su cosa serve perche' una richiesta parta, e sui tempi promessi.

`perche_non_puoi_inviare` risponde «perche' non posso inviare?» con una
frase per l'utente, oppure None. La usa `Richiesta.invia()` come guardia e
la usa la pagina della richiesta per mostrare cosa manca PRIMA che l'utente
prema il bottone. `perche_non_puoi_riassegnare` fa lo stesso per un caso
declinato che il richiedente gira a un altro esperto.

`ore_risposta_dichiarate` e' il tempo di risposta che l'esperto ha promesso
per quel tipo: lo mostra l'elenco dei casi ricevuti e lo usa
`sorveglia_consulti` per il sollecito a meta' tempo.

## Una regola sola per la frase e per la lista

`elementi_obbligatori` dice, per il tipo di esame, quali file servono e se
ci sono gia'. Da li' escono sia la frase di `perche_non_puoi_inviare` (via
`allegati_mancanti`) sia la lista con le caselle del passo «Carica gli
esami» della richiesta guidata: il template non riscrive la regola, la
legge. Aggiungere un requisito qui lo aggiunge in entrambi i posti.
"""

from dataclasses import dataclass

from core.tipi import TipoEsame
from .models import CategoriaAllegato, StatoRichiesta


@dataclass(frozen=True)
class Elemento:
    """Un file obbligatorio per inviare. `frase` entra nel messaggio di
    `perche_non_puoi_inviare` («Manca <frase>.»), `etichetta` e' la voce
    della lista con le caselle; `proiezione_id` e' valorizzato per le
    proiezioni eco del catalogo."""

    chiave: str
    etichetta: str
    frase: str
    fatto: bool
    proiezione_id: int | None = None


def elementi_obbligatori(richiesta):
    """Gli elementi obbligatori per il tipo della richiesta, in ordine, con
    lo stato fatto/mancante. Gli allegati SCARTATO non contano per le
    categorie; per le proiezioni conta la riga ProiezioneCaricata, come
    prima del refactor (nessun cambiamento in cio' che blocca l'invio)."""
    categorie = set(richiesta.allegati.exclude(stato='SCARTATO').values_list('categoria', flat=True))
    elementi = []
    if richiesta.tipo_esame == TipoEsame.ECG:
        elementi.append(Elemento(
            'ecg', 'Tracciato ECG (PDF o foto)', 'il tracciato ECG (PDF o immagine)',
            bool(categorie & {CategoriaAllegato.ECG_PDF, CategoriaAllegato.ECG_IMMAGINE})))
    elif richiesta.tipo_esame == TipoEsame.HOLTER:
        elementi.append(Elemento(
            'holter_referto', 'Referto del software Holter (PDF)', 'il referto Holter dell\'apparecchio',
            CategoriaAllegato.HOLTER_REFERTO in categorie))
    elif richiesta.tipo_esame == TipoEsame.ECO:
        elementi.append(Elemento(
            'eco_referto', 'Referto dell\'ecografo (PDF)', 'il referto dell\'ecografo (PDF)',
            CategoriaAllegato.ECO_REFERTO_PDF in categorie))
        from eco.models import ProiezioneCatalogo, in_ordine
        caricate = set(richiesta.proiezioni.values_list('proiezione_id', flat=True))
        # Stesso ordine delle righe del passo 3: finestra, filmati prima delle immagini, `ordine`.
        for p in in_ordine(ProiezioneCatalogo.objects.filter(obbligatoria=True, attiva=True)):
            elementi.append(Elemento(f'proiezione_{p.id}', p.nome, f'la proiezione «{p.nome}»',
                                     p.id in caricate, proiezione_id=p.id))
    return elementi


def allegati_mancanti(richiesta):
    """Elenco di frasi, una per requisito non soddisfatto."""
    return [e.frase for e in elementi_obbligatori(richiesta) if not e.fatto]


def _perche_non_puo_richiedere(richiesta):
    if not richiesta.richiedente.puo_richiedere:
        return 'Completa i dati di fatturazione della clinica prima di inviare.'
    if not richiesta.richiedente.approvazione_ok():
        if richiesta.clinica_id:
            return 'La clinica non e\' ancora stata approvata: riceverai un avviso quando lo sara\'.'
        return 'Il tuo profilo non e\' ancora stato approvato: riceverai un avviso quando lo sara\'.'
    return None


def perche_non_puoi_inviare(richiesta):
    if richiesta.stato != StatoRichiesta.BOZZA:
        return f'La richiesta e\' gia\' «{richiesta.get_stato_display()}».'
    motivo = _perche_non_puo_richiedere(richiesta)
    if motivo:
        return motivo
    if not hasattr(richiesta, 'paziente'):
        return 'Compila i dati del paziente.'
    if richiesta.refertatore is None:
        return 'Scegli il refertatore a cui mandare il caso.'
    if not richiesta.refertatore.referta(richiesta.tipo_esame):
        return (f'{richiesta.refertatore} non e\' referente per '
                f'{richiesta.get_tipo_esame_display()}: scegli un altro collega.')
    return frase_mancanti(allegati_mancanti(richiesta))


def frase_mancanti(mancanti):
    """«Manca X.» / «Mancano: X; Y.» / None. La usa anche il passo 3 per
    dire perche' «Avanti» e' spento: stessa frase del blocco all'invio."""
    if not mancanti:
        return None
    if len(mancanti) == 1:
        return f'Manca {mancanti[0]}.'
    return 'Mancano: ' + '; '.join(mancanti) + '.'


def perche_non_puoi_riassegnare(richiesta, refertatore):
    """Un caso DECLINATO si gira a un altro esperto referente per il tipo.
    Gli allegati c'erano gia' all'invio: non si ricontrollano."""
    if richiesta.stato != StatoRichiesta.DECLINATA:
        return f'Si riassegna solo un caso declinato; questo e\' «{richiesta.get_stato_display()}».'
    motivo = _perche_non_puo_richiedere(richiesta)
    if motivo:
        return motivo
    if refertatore is None:
        return 'Scegli l\'esperto a cui girare il caso.'
    if not refertatore.referta(richiesta.tipo_esame):
        return (f'{refertatore} non e\' referente per '
                f'{richiesta.get_tipo_esame_display()}: scegli un altro collega.')
    return None


# Tempo di risposta se l'esperto non l'ha dichiarato per quel tipo. Da far
# confermare ad Andre: oggi e' la lettura letterale della voce H di F3.
ORE_RISPOSTA_PREDEFINITE = 48
ORE_RISPOSTA_URGENZA = 4


def ore_risposta_dichiarate(richiesta):
    """Ore promesse dall'esperto assegnato per questo tipo di esame; se non
    le ha dichiarate, 4 per un'urgenza e 48 altrimenti."""
    comp = richiesta.refertatore.competenza_per(richiesta.tipo_esame) if richiesta.refertatore_id else None
    if comp and comp.tempo_risposta_ore:
        return comp.tempo_risposta_ore
    return ORE_RISPOSTA_URGENZA if richiesta.urgenza else ORE_RISPOSTA_PREDEFINITE
