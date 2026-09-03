from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from accounts.models import CompetenzaRefertatore, Refertatore
from core.tipi import TipoEsame
from listino.models import Supplemento, TipoSupplemento, VoceListino
from listino.prezzi import ORIGINE_LISTINO, ORIGINE_REFERTATORE, PrezzoNonDisponibile, prezzo_effettivo


@pytest.fixture
def listino_base(db):
    VoceListino.objects.create(tipo_esame=TipoEsame.ECG, descrizione='ECG', prezzo=Decimal('40.00'),
                               valido_dal=date(2026, 1, 1))
    # Voce scaduta: non deve vincere anche se piu' recente come valido_dal
    VoceListino.objects.create(tipo_esame=TipoEsame.ECG, descrizione='ECG promo', prezzo=Decimal('10.00'),
                               valido_dal=date(2026, 2, 1), valido_al=date(2026, 2, 28))
    Supplemento.objects.create(codice='URG', descrizione='Urgenza', tipo=TipoSupplemento.URGENZA,
                               percentuale=Decimal('50.00'), valido_dal=date(2026, 1, 1))


def test_prezzo_da_listino(listino_base):
    p = prezzo_effettivo(TipoEsame.ECG, giorno=date(2026, 6, 1))
    assert p.imponibile == Decimal('40.00')
    assert p.supplementi == Decimal('0.00')
    assert p.iva == Decimal('8.80')
    assert p.totale == Decimal('48.80')
    assert p.origine == ORIGINE_LISTINO


def test_voce_scaduta_non_vince(listino_base):
    assert prezzo_effettivo(TipoEsame.ECG, giorno=date(2026, 2, 15)).imponibile == Decimal('10.00')
    assert prezzo_effettivo(TipoEsame.ECG, giorno=date(2026, 3, 1)).imponibile == Decimal('40.00')


def test_override_refertatore(listino_base):
    u = User.objects.create_user('r', 'r@x.it', 'pw')
    r = Refertatore.objects.create(user=u)
    CompetenzaRefertatore.objects.create(refertatore=r, tipo_esame=TipoEsame.ECG, referente=True,
                                         prezzo_personalizzato=Decimal('55.00'))
    p = prezzo_effettivo(TipoEsame.ECG, refertatore=r, giorno=date(2026, 6, 1))
    assert p.imponibile == Decimal('55.00')
    assert p.origine == ORIGINE_REFERTATORE
    assert p.aliquota_iva == Decimal('22.00')


def test_urgenza(listino_base):
    p = prezzo_effettivo(TipoEsame.ECG, urgenza=True, giorno=date(2026, 6, 1))
    assert p.supplementi == Decimal('20.00')
    assert p.imponibile_totale == Decimal('60.00')
    assert p.iva == Decimal('13.20')
    assert p.totale == Decimal('73.20')
    assert p.dettaglio_supplementi == [('URG', Decimal('20.00'))]


def test_senza_listino_si_solleva(listino_base):
    with pytest.raises(PrezzoNonDisponibile):
        prezzo_effettivo(TipoEsame.ECO, giorno=date(2026, 6, 1))
