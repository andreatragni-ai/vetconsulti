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
"""

from core.tipi import TipoEsame
from .models import CategoriaAllegato, StatoRichiesta


def allegati_mancanti(richiesta):
    """Elenco di frasi, una per requisito non soddisfatto."""
    categorie = set(richiesta.allegati.exclude(stato='SCARTATO').values_list('categoria', flat=True))
    mancanti = []
    if richiesta.tipo_esame == TipoEsame.ECG:
        if not categorie & {CategoriaAllegato.ECG_PDF, CategoriaAllegato.ECG_IMMAGINE}:
            mancanti.append('il tracciato ECG (PDF o immagine)')
    elif richiesta.tipo_esame == TipoEsame.HOLTER:
        if CategoriaAllegato.HOLTER_REFERTO not in categorie:
            mancanti.append('il referto Holter dell\'apparecchio')
    elif richiesta.tipo_esame == TipoEsame.ECO:
        if CategoriaAllegato.ECO_REFERTO_PDF not in categorie:
            mancanti.append('il referto dell\'ecografo (PDF)')
        from eco.models import ProiezioneCatalogo
        caricate = set(richiesta.proiezioni.values_list('proiezione_id', flat=True))
        for p in ProiezioneCatalogo.objects.filter(obbligatoria=True, attiva=True).order_by('ordine'):
            if p.id not in caricate:
                mancanti.append(f'la proiezione «{p.nome}»')
    return mancanti


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
    mancanti = allegati_mancanti(richiesta)
    if mancanti:
        if len(mancanti) == 1:
            return f'Manca {mancanti[0]}.'
        return 'Mancano: ' + '; '.join(mancanti) + '.'
    return None


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
