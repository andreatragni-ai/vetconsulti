"""
Calcolo del prezzo effettivo di un consulto.

Una sola funzione, `prezzo_effettivo`, che risponde alla domanda «quanto
costa questo consulto oggi con questo refertatore» e dice da dove viene il
numero. La pagina «Nuova richiesta» la chiama per mostrare il prezzo accanto
al nome; il registro la chiama alla firma per fissarlo nella Prestazione.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .models import Supplemento, TipoSupplemento, VoceListino


class PrezzoNonDisponibile(Exception):
    """Nessuna voce di listino in vigore e nessun prezzo personalizzato."""


ORIGINE_LISTINO = 'LISTINO'
ORIGINE_REFERTATORE = 'REFERTATORE'


@dataclass
class Prezzo:
    imponibile: Decimal
    supplementi: Decimal
    aliquota_iva: Decimal
    iva: Decimal
    totale: Decimal
    origine: str
    dettaglio_supplementi: list = field(default_factory=list)

    @property
    def imponibile_totale(self):
        return self.imponibile + self.supplementi


def _due_decimali(valore):
    return Decimal(valore).quantize(Decimal('0.01'))


def prezzo_effettivo(tipo_esame, refertatore=None, urgenza=False, giorno=None):
    giorno = giorno or date.today()
    voce = (VoceListino.objects.filter(tipo_esame=tipo_esame, valido_dal__lte=giorno)
            .exclude(valido_al__lt=giorno).order_by('-valido_dal').first())

    personalizzato = None
    if refertatore is not None:
        comp = refertatore.competenza_per(tipo_esame)
        if comp and comp.prezzo_personalizzato is not None:
            personalizzato = comp.prezzo_personalizzato

    if personalizzato is not None:
        imponibile = _due_decimali(personalizzato)
        origine = ORIGINE_REFERTATORE
    elif voce is not None:
        imponibile = _due_decimali(voce.prezzo)
        origine = ORIGINE_LISTINO
    else:
        raise PrezzoNonDisponibile(f'Nessun prezzo disponibile per {tipo_esame} il {giorno}.')

    # L'aliquota viene sempre dal listino: il prezzo personalizzato e' un
    # imponibile, non un regime fiscale. Senza listino si usa il 22%.
    aliquota = _due_decimali(voce.aliquota_iva) if voce is not None else Decimal('22.00')

    supplementi = Decimal('0.00')
    dettaglio = []
    if urgenza:
        for s in Supplemento.objects.filter(tipo=TipoSupplemento.URGENZA, valido_dal__lte=giorno) \
                .exclude(valido_al__lt=giorno):
            quanto = _due_decimali(s.calcola(imponibile))
            supplementi += quanto
            dettaglio.append((s.codice, quanto))

    base = imponibile + supplementi
    iva = _due_decimali(base * aliquota / Decimal('100'))
    return Prezzo(imponibile=imponibile, supplementi=supplementi, aliquota_iva=aliquota,
                  iva=iva, totale=base + iva, origine=origine, dettaglio_supplementi=dettaglio)
