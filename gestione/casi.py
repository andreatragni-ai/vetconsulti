"""Le domande che la Gestione fa ai casi: quali sono aperti, quali in
ritardo, cosa si puo' fare su uno di essi.

«In ritardo» si calcola in Python e non nel database perche' la scadenza
dipende dal tempo di risposta che ogni esperto dichiara per ogni tipo di
esame (consulti.regole.scadenza): con decine di casi aperti costa niente, e
la regola resta scritta in un posto solo.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from consulti import regole
from consulti.models import Richiesta, StatoRichiesta
from notifiche.models import EsitoInvio, InvioEmail

STATI_APERTI = (StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO, StatoRichiesta.DECLINATA)

FILTRI = {
    'aperti': 'Aperti',
    'ritardo': 'In ritardo',
    'chiusi': 'Chiusi',
    'tutti': 'Tutti',
}


def inviati():
    """Tutti i casi usciti dalla bozza. Le bozze restano di chi le scrive:
    la Gestione non le mostra (lo staff le vede comunque dalla pagina del caso)."""
    return (Richiesta.objects.exclude(stato=StatoRichiesta.BOZZA)
            .select_related('richiedente__user', 'clinica', 'refertatore__user', 'paziente')
            .order_by('-inviata_il'))


def con_scadenza(richieste, adesso=None):
    """Attacca a ogni caso `scadenza` e `in_ritardo` (solo per chi aspetta
    ancora una risposta: un caso declinato aspetta il richiedente)."""
    adesso = adesso or timezone.now()
    righe = list(richieste)
    for r in righe:
        attende_esperto = r.stato in (StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO)
        r.scadenza = regole.scadenza(r) if attende_esperto else None
        r.in_ritardo = bool(r.scadenza and r.scadenza < adesso)
    return righe


def elenco(filtro='aperti', cerca='', adesso=None):
    qs = inviati()
    if filtro in ('aperti', 'ritardo'):
        qs = qs.filter(stato__in=STATI_APERTI)
    elif filtro == 'chiusi':
        qs = qs.exclude(stato__in=STATI_APERTI)
    cerca = (cerca or '').strip()
    if cerca:
        qs = qs.filter(Q(codice__icontains=cerca) | Q(paziente__nome__icontains=cerca)
                       | Q(paziente__cognome_proprietario__icontains=cerca)
                       | Q(clinica__denominazione__icontains=cerca)
                       | Q(richiedente__user__last_name__icontains=cerca)
                       | Q(refertatore__user__last_name__icontains=cerca))
    righe = con_scadenza(qs, adesso)
    if filtro == 'ritardo':
        righe = [r for r in righe if r.in_ritardo]
    return righe


def email_non_partite(giorni=7):
    dal = timezone.now() - timedelta(days=giorni)
    return (InvioEmail.objects.filter(esito=EsitoInvio.ERRORE, inviata_il__gte=dal)
            .select_related('richiesta').order_by('-inviata_il'))


def esperti_per(richiesta):
    """A chi si puo' affidare il caso: referenti attivi per il tipo, meno
    quello che ce l'ha gia' (se il caso non e' declinato), con il motivo per
    cui uno non si puo' scegliere invece di nasconderlo (assente, urgenze)."""
    from accounts.models import Refertatore
    voci = []
    for ref in Refertatore.referenti_per(richiesta.tipo_esame):
        if ref.pk == richiesta.refertatore_id and richiesta.stato != StatoRichiesta.DECLINATA:
            continue
        ostacolo = regole.rifiuta_urgenza(ref, richiesta.tipo_esame, richiesta.urgenza)
        voci.append({'refertatore': ref, 'ostacolo': ostacolo,
                     'assente': not ref.disponibile_oggi, 'rientro': ref.assente_al})
    return voci
