"""
Glossario clinico per la ripulitura del testo dettato (consulti/dettatura.py).

## Provenienza

Lista **copiata a mano, non importata**, da VetCardio il 12/09/2026:
`~/progetti/vetcardio/dettatura/fixtures/glossario_it.yaml` (70 voci, caricate
la' da `manage.py seed_glossario` nel modello `TermineGlossario`) e la forma
del testo per il prompt da `vetcardio/dettatura/services/glossario.py`
(`glossario_per_prompt`). Il portale **non importa da `cardio` ne' da
`dettatura`** (CLAUDE.md): qui ci sono solo i termini che servono a un
teleconsulto cardiologico, senza il modello, la cache e i contatori d'uso che
in VetCardio servono alla sua pipeline ASR.

Rispetto alla lista di VetCardio sono rimaste fuori le voci che qui non
servono (nessuna: il teleconsulto e' cardiologico come il gemello) e si sono
aggiunte le **sigle dettate a voce** (`SIGLE_DETTATE`), che in VetCardio
vengono imparate a poco a poco nel modello `VarianteFonetica` a partire dalle
correzioni vere. Qui non c'e' nulla da imparare: sono scritte a mano, perche'
il riconoscimento vocale del browser le sbaglia sempre allo stesso modo.

Si aggiorna QUI, mai nel prompt e mai nel codice della vista. Se un giorno
serve che i colleghi lo estendano da soli, questo file diventa una tabella.
"""

# ── Termini corretti, per categoria (da vetcardio/dettatura/fixtures/glossario_it.yaml) ──
TERMINI = {
    'Valvole': [
        'mitrale', 'tricuspide', 'aortica', 'polmonare', 'insufficienza mitralica',
        'rigurgito mitralico', 'insufficienza tricuspidale', 'rigurgito tricuspidale',
        'endocardiosi valvolare mitralica',
    ],
    'Patologie': [
        'MMVD', 'cardiomiopatia dilatativa', 'cardiomiopatia ipertrofica',
        'cardiomiopatia restrittiva', 'displasia della valvola mitrale',
        'displasia della valvola tricuspide', 'dotto arterioso pervio',
        'stenosi sottoaortica', 'stenosi polmonare', 'difetto del setto interventricolare',
        'difetto del setto interatriale', 'versamento pericardico', 'tamponamento cardiaco',
        'endocardite batterica', 'ipertensione polmonare',
    ],
    'Aritmie': [
        'fibrillazione atriale', 'tachicardia sopraventricolare', 'tachicardia ventricolare',
        'bradicardia sinusale', 'extrasistole ventricolare', 'blocco atrioventricolare',
    ],
    'Stadiazione': [
        'ACVIM', 'classe B1', 'classe B2', 'classe C', 'classe D', 'ISACHC', 'stadio CHIEF',
    ],
    'Anatomia': [
        'ventricolo sinistro', 'ventricolo destro', 'atrio sinistro', 'atrio destro',
        'setto interventricolare', 'parete libera del ventricolo sinistro', 'aorta',
        'arteria polmonare', 'anulus mitralico',
    ],
    'Parametri': [
        'LVIDdN', 'LA/Ao', 'TAPSE', 'MAPSE', 'frazione di accorciamento',
        'frazione di eiezione', 'MINE Score',
    ],
    'Doppler': [
        'gradiente pressorio', 'velocita di picco', 'flusso transmitralico',
        'flusso transtricuspidale', 'shunt sinistro-destro', 'shunt destro-sinistro',
    ],
    'Farmaci': [
        'pimobendan', 'benazepril', 'ramipril', 'spironolattone', 'furosemide',
        'torasemide', 'sildenafil', 'clopidogrel', 'diltiazem', 'atenololo', 'sotalolo',
    ],
}

# ── Sigle dettate lettera per lettera (come le sente il browser -> come si scrivono) ──
# Il riconoscimento vocale del browser non conosce le sigle cardiologiche e le
# trascrive fonetica: sono gli errori che si ripetono a ogni dettatura.
SIGLE_DETTATE = [
    ('emme emme vi di', 'MMVD'),
    ('acvim be due', 'ACVIM B2'),
    ('acvim be uno', 'ACVIM B1'),
    ('elle a su a o', 'LA/Ao'),
    ('ti a pi esse e', 'TAPSE'),
    ('emme a pi esse e', 'MAPSE'),
    ('vi ti i', 'VTI'),
    ('elle vi i di di enne', 'LVIDdN'),
    ('di ci emme', 'DCM'),
    ('ci emme i', 'CMI'),
    ('e ci gi', 'ECG'),
    ('pi di a', 'PDA'),
    ('esse a emme', 'SAM'),
]


def per_prompt():
    """Il glossario come testo per il prompt: una riga per categoria, come fa
    `glossario_per_prompt` in VetCardio."""
    return '\n'.join(f'{categoria}: ' + ', '.join(TERMINI[categoria]) for categoria in TERMINI)


def sigle_per_prompt():
    """Le sigle dettate a voce: «come si sente» -> «come si scrive»."""
    return '\n'.join(f'{detto} -> {scritto}' for detto, scritto in SIGLE_DETTATE)
