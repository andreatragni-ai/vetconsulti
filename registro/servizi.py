"""Registrazione di una prestazione alla firma del referto. Idempotente:
chiamarla due volte per la stessa richiesta ritorna la stessa riga."""

import logging

from django.db import transaction
from django.utils import timezone

from listino.prezzi import prezzo_effettivo
from .models import Prestazione, StatoFatturazione

logger = logging.getLogger('registro')


def registra_prestazione(richiesta):
    esistente = Prestazione.objects.filter(richiesta=richiesta).first()
    if esistente:
        return esistente
    if richiesta.refertatore is None:
        raise ValueError(f'{richiesta.codice}: nessun refertatore, non si registra una prestazione.')

    oggi = timezone.localdate()
    prezzo = prezzo_effettivo(richiesta.tipo_esame, refertatore=richiesta.refertatore,
                              urgenza=richiesta.urgenza, giorno=oggi)
    with transaction.atomic():
        prestazione = Prestazione.objects.create(
            richiesta=richiesta, richiedente=richiesta.richiedente, clinica=richiesta.clinica,
            refertatore=richiesta.refertatore, tipo_esame=richiesta.tipo_esame, data=oggi,
            soggetto_emittente=richiesta.refertatore.soggetto_emittente,
            imponibile=prezzo.imponibile, supplementi=prezzo.supplementi,
            aliquota_iva=prezzo.aliquota_iva, totale=prezzo.totale, origine_prezzo=prezzo.origine)
        StatoFatturazione.objects.create(prestazione=prestazione)
        richiesta.registra('PRESTAZIONE_REGISTRATA', None, prestazione=prestazione.id,
                           totale=str(prestazione.totale))
    logger.info('Prestazione %s registrata per %s: € %s', prestazione.id, richiesta.codice, prestazione.totale)
    return prestazione
