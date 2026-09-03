"""
Regole su cosa serve perche' una richiesta parta.

Una sola funzione che risponde «perche' non posso inviare?» con una frase
per l'utente, oppure None. La usa `Richiesta.invia()` come guardia e la
usa la pagina della richiesta per mostrare cosa manca PRIMA che l'utente
prema il bottone.
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


def perche_non_puoi_inviare(richiesta):
    if richiesta.stato != StatoRichiesta.BOZZA:
        return f'La richiesta e\' gia\' «{richiesta.get_stato_display()}».'
    if not richiesta.richiedente.puo_richiedere:
        return 'Completa i dati di fatturazione della clinica prima di inviare.'
    if not richiesta.richiedente.approvazione_ok():
        if richiesta.clinica_id:
            return 'La clinica non e\' ancora stata approvata: riceverai un avviso quando lo sara\'.'
        return 'Il tuo profilo non e\' ancora stato approvato: riceverai un avviso quando lo sara\'.'
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
