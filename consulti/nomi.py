"""
Maiuscole automatiche sui nomi propri scritti in fretta (collaudo
dell'11/09/2026): il nome del paziente e il cognome del proprietario si
salvano con l'iniziale maiuscola, «luna» -> «Luna», «rossi» -> «Rossi».

Regole, parola per parola (le parole sono separate da spazi):

- una parola tutta minuscola prende la maiuscola all'inizio e dopo
  apostrofo o trattino: «de simone» -> «De Simone», «d'amico» -> «D'Amico»,
  «rossi-bianchi» -> «Rossi-Bianchi»;
- una parola che ha GIA' almeno una maiuscola non si tocca: «McDonald»,
  «DeSimone», anche «ROSSI» tutto maiuscolo (chi l'ha scritto cosi' l'ha
  voluto: da confermare con Andre);
- gli spazi doppi o in testa e in coda si tolgono.

La applicano `Paziente.save()` (qualunque strada: form, admin, seed) e il
form del passo 1, cosi' il nome si vede gia' giusto al passo 2.
"""

import re

_SEPARA = re.compile(r"(['’\-])")


def _parola(parola):
    if parola != parola.lower():
        return parola
    return ''.join(pezzo[:1].upper() + pezzo[1:] for pezzo in _SEPARA.split(parola))


def maiuscole_nome(testo):
    if not testo:
        return testo
    return ' '.join(_parola(p) for p in testo.split())
