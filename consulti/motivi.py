"""
Le frasi pronte per dire di no.

Chi declina o segna un caso come non refertabile scrive per il collega che
ha chiesto: il motivo e' obbligatorio e deve essere comprensibile senza una
telefonata. Le frasi rapide sono solo un inizio (riempiono la casella, poi
si completa); le voci di «non refertabile» cambiano per tipo di esame.
Testi da far rivedere ad Andre.
"""

from core.tipi import TipoEsame

FRASI_DECLINA = [
    'Non referto gatti.',
    'Non referto questa specie.',
    'Assente fino al ',
    'Caso fuori dalla mia competenza: meglio un collega.',
    'Non riesco a rispettare i tempi di risposta dichiarati.',
]

ALTRO = 'Altro'

VOCI_NON_REFERTABILE = {
    TipoEsame.ECG: [
        'Qualita\' del tracciato insufficiente',
        'Derivazioni inadeguate o mancanti',
        'Parametri di registrazione mancanti (velocita\', ampiezza)',
        'Artefatti che impediscono la lettura',
        ALTRO,
    ],
    TipoEsame.HOLTER: [
        'Qualita\' della registrazione insufficiente',
        'Derivazioni inadeguate o mancanti',
        'Parametri di registrazione mancanti (durata, diario)',
        'Artefatti che impediscono la lettura',
        ALTRO,
    ],
    TipoEsame.ECO: [
        'Qualita\' delle immagini insufficiente',
        'Proiezioni mancanti o inadeguate',
        'Parametri di registrazione mancanti (ECG di sincronizzazione, scala)',
        'Artefatti che impediscono la lettura',
        ALTRO,
    ],
}


def voci_non_refertabile(tipo_esame):
    return VOCI_NON_REFERTABILE.get(tipo_esame, [ALTRO])


def motivo_non_refertabile(voce, dettaglio):
    """Una sola frase per chi legge: «voce: dettaglio», oppure solo il
    dettaglio se la voce e' «Altro»."""
    dettaglio = (dettaglio or '').strip()
    if voce == ALTRO:
        return dettaglio
    return f'{voce}: {dettaglio}' if dettaglio else voce
