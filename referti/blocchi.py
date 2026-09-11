"""
Blocco del referto per tipo di esame: le voci strutturate che si aggiungono
alle tre caselle comuni (descrizione, conclusioni, raccomandazioni).

## Il punto di aggancio

Ogni tipo ha un `Blocco` con un partial (`referti/blocchi/_<tipo>.html`,
incluso dalla pagina di refertazione) e una lista di `Voce`. Le voci finiscono
nel JSON `Referto.classificazione` con la loro chiave, e il PDF le stampa
con la loro etichetta. Aggiungere una voce = aggiungerla qui (e, se serve un
layout speciale, nel partial): nessuna migrazione.

Oggi il blocco e' MINIMO e da far rivedere ad Andre:

- ECG: solo il rischio anestesiologico, con le stesse voci di VetCardio
  (`cardio/refertabile.py`: BASSO, MEDIO=«Intermedio», ALTO, NON_VALUTABILE).
  Le misure strutturate arriveranno dal lettore SEIVA di VetCardio e si
  innestano qui come altre voci del blocco ECG.
- Holter ed eco: nessuna voce, solo le tre caselle.
"""

from dataclasses import dataclass, field

from core.tipi import TipoEsame


RISCHIO_ANESTESIA = [
    ('BASSO', 'Basso'),
    ('MEDIO', 'Intermedio'),
    ('ALTO', 'Alto'),
    ('NON_VALUTABILE', 'Non valutabile su questo tracciato'),
]


@dataclass(frozen=True)
class Voce:
    chiave: str
    etichetta: str
    scelte: list = field(default_factory=list)  # vuota = testo libero
    aiuto: str = ''

    def leggibile(self, valore):
        if self.scelte:
            return dict(self.scelte).get(valore, valore)
        return valore


@dataclass(frozen=True)
class Blocco:
    partial: str
    voci: list = field(default_factory=list)


BLOCCHI = {
    TipoEsame.ECG: Blocco('referti/blocchi/_ecg.html', [
        Voce('rischio_anestesia', 'Rischio anestesiologico', RISCHIO_ANESTESIA,
             'Stesse voci di VetCardio.'),
    ]),
    TipoEsame.HOLTER: Blocco('referti/blocchi/_holter.html'),
    TipoEsame.ECO: Blocco('referti/blocchi/_eco.html'),
}


def blocco_per(tipo_esame):
    return BLOCCHI.get(tipo_esame, Blocco('referti/blocchi/_vuoto.html'))


def classificazione_leggibile(tipo_esame, classificazione):
    """[(etichetta, valore leggibile)] nell'ordine del blocco; le chiavi che
    il blocco non conosce (dati vecchi) finiscono in coda cosi' come sono."""
    classificazione = classificazione or {}
    righe, viste = [], set()
    for voce in blocco_per(tipo_esame).voci:
        valore = classificazione.get(voce.chiave)
        viste.add(voce.chiave)
        if valore not in (None, ''):
            righe.append((voce.etichetta, voce.leggibile(valore)))
    for chiave, valore in classificazione.items():
        if chiave not in viste and valore not in (None, ''):
            righe.append((chiave.replace('_', ' ').capitalize(), valore))
    return righe
