"""Cambiare un prezzo senza riscrivere la storia.

Un prezzo nuovo non modifica la riga in vigore: la chiude il giorno prima e
ne apre un'altra dalla data scelta (vedi il docstring di listino/models.py).
La data non puo' stare nel passato — i consulti gia' fatti sono stati
calcolati col prezzo di allora — e non puo' cadere prima di un cambio gia'
programmato: due righe aperte sullo stesso giorno darebbero un prezzo a
caso.

Per i supplementi `codice` e' unico, quindi la riga nuova prende un codice
col giorno di partenza («URGENZA-20261001»): e' un'etichetta interna, al
collega arriva la descrizione.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Supplemento, VoceListino


class CambioNonValido(Exception):
    """Messaggio per chi sta cambiando il prezzo."""


def _controlla_data(dal, ultima_partenza):
    if dal < timezone.localdate():
        raise CambioNonValido('Il nuovo prezzo parte da oggi o da una data futura, non dal passato.')
    if ultima_partenza and dal <= ultima_partenza:
        raise CambioNonValido(f'C\'e\' gia\' un prezzo che parte il {ultima_partenza:%d/%m/%Y}: '
                              'scegli una data successiva.')


@transaction.atomic
def cambia_prezzo(tipo_esame, prezzo, aliquota_iva, dal, descrizione=''):
    voci = VoceListino.objects.select_for_update().filter(tipo_esame=tipo_esame)
    ultima = voci.order_by('-valido_dal').first()
    _controlla_data(dal, ultima.valido_dal if ultima else None)
    for aperta in voci.filter(valido_al__isnull=True) | voci.filter(valido_al__gte=dal):
        aperta.valido_al = dal - timedelta(days=1)
        aperta.save(update_fields=['valido_al'])
    return VoceListino.objects.create(
        tipo_esame=tipo_esame, prezzo=prezzo, aliquota_iva=aliquota_iva, valido_dal=dal,
        descrizione=descrizione or (ultima.descrizione if ultima else tipo_esame))


@transaction.atomic
def cambia_supplemento(supplemento, dal, importo=None, percentuale=None):
    if (importo is None) == (percentuale is None):
        raise CambioNonValido('Indica un importo oppure una percentuale.')
    stessi = Supplemento.objects.select_for_update().filter(tipo=supplemento.tipo)
    ultima = stessi.order_by('-valido_dal').first()
    _controlla_data(dal, ultima.valido_dal if ultima else None)
    for aperto in stessi.filter(valido_al__isnull=True) | stessi.filter(valido_al__gte=dal):
        aperto.valido_al = dal - timedelta(days=1)
        aperto.save(update_fields=['valido_al'])
    return Supplemento.objects.create(
        codice=f'{supplemento.tipo}-{dal:%Y%m%d}'[:20], descrizione=supplemento.descrizione,
        tipo=supplemento.tipo, importo=importo, percentuale=percentuale, valido_dal=dal)
