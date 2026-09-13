"""
Il racconto dell'audit: da `EventoAudit` (codici e JSON) a frasi che una
persona legge sulla pagina del caso.

Chi guarda cosa: lo staff vede tutto, chi ha chiesto e chi referta non
vedono gli eventi interni (accessi dello staff, registrazione della
prestazione). L'audit resta intatto: qui si decide solo cosa si mostra.
"""

from accounts.models import Refertatore

SOLO_STAFF = {'ACCESSO_STAFF', 'PRESTAZIONE_REGISTRATA'}
# REFERTATA e REFERTO_FIRMATO arrivano insieme: nel racconto basta il secondo.
DOPPIONI = {'REFERTATA'}


def _nome_utente(utente):
    if utente is None:
        return 'Il portale'
    return utente.get_full_name() or utente.get_username()


def _frase(evento, refertatori):
    d = evento.dettaglio or {}
    a = evento.azione

    def ref(chiave='refertatore'):
        return refertatori.get(d.get(chiave), 'un esperto')

    motivo = f' — «{d["motivo"]}»' if d.get('motivo') else ''
    frasi = {
        'CREATA': 'ha creato la richiesta in bozza',
        'ALLEGATO_CARICATO': f'ha caricato «{d.get("nome", "un allegato")}»'
                             + (f' ({d["proiezione"]})' if d.get('proiezione') else ''),
        'ALLEGATO_ELIMINATO': (f'ha sostituito «{d.get("nome", "")}»' if d.get('sostituito_da')
                               else f'ha eliminato l\'allegato «{d.get("nome", "")}»'),
        'ALLEGATO_TRANSCODIFICATO': 'clip convertita per la visione nel browser',
        'INVIATA': f'ha inviato il caso a {ref()}',
        'PRESA_IN_CARICO': 'ha preso in carico il caso',
        'RILASCIATA': f'presa in carico rilasciata{motivo}',
        'DECLINATA': f'ha declinato il caso{motivo}',
        'RIASSEGNATA': f'ha girato il caso a {ref()}',
        'NON_REFERTABILE': f'ha segnato il caso come non refertabile{motivo}',
        'ANNULLATA': 'ha annullato la richiesta',
        # Il motivo di uno spostamento («e' malato», «non risponde») e' della
        # gestione: chi ha chiesto vede solo a chi e' passato il caso. Lo staff
        # lo legge nella scheda del caso in Gestione, dall'audit.
        'SPOSTATA_DA_GESTIONE': f'la gestione ha affidato il caso a {ref()}',
        'ANNULLATA_DA_GESTIONE': f'la gestione ha annullato il caso{motivo}',
        'REFERTATA': 'caso refertato',
        'REFERTO_FIRMATO': f'ha firmato il referto (versione {d.get("versione", 1)})',
        'REFERTO_RETTIFICATO': f'ha emesso la rettifica, versione {d.get("versione", "?")}{motivo}',
        'PRESTAZIONE_REGISTRATA': f'prestazione registrata (€ {d.get("totale", "?")})',
        'SOLLECITO': 'promemoria inviato all\'esperto a meta\' del tempo di risposta',
        'ACCESSO_STAFF': f'ha consultato il caso come staff ({d.get("pagina", "pagina")})',
        'SMISTAMENTO_AVVIATO': f'ha avviato lo smistamento automatico di {d.get("file", "")} file',
        'SMISTAMENTO_CONFERMATO': f'ha confermato lo smistamento dei file ({d.get("righe", 0)} proiezioni)',
    }
    return frasi.get(a, a.replace('_', ' ').lower())


def racconta(eventi, per_staff=False):
    """[{quando, chi, frase, azione}] nell'ordine dell'audit."""
    eventi = list(eventi)
    ids = {v for e in eventi for k, v in (e.dettaglio or {}).items() if k in ('refertatore', 'da') and v}
    refertatori = {r.id: r.nome_completo for r in Refertatore.objects.filter(id__in=ids).select_related('user')}
    righe = []
    for e in eventi:
        if not per_staff and (e.azione in SOLO_STAFF or e.azione in DOPPIONI):
            continue
        righe.append({'quando': e.quando, 'chi': _nome_utente(e.utente), 'frase': _frase(e, refertatori),
                      'azione': e.azione})
    return righe
