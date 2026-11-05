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
import unicodedata

_SEPARA = re.compile(r"(['’\-])")


def _parola(parola):
    if parola != parola.lower():
        return parola
    return ''.join(pezzo[:1].upper() + pezzo[1:] for pezzo in _SEPARA.split(parola))


def maiuscole_nome(testo):
    if not testo:
        return testo
    return ' '.join(_parola(p) for p in testo.split())


# ── La chiave dell'archivio pazienti ────────────────────────────────────────
# Due richieste parlano dello stesso animale se combaciano nome, specie e
# cognome del proprietario a meno di maiuscole, accenti, apostrofi e spazi:
# «Luna»/«luna», «D'Amico»/«d amico». Non e' una identita' vera (due Luna
# Rossi nella stessa clinica diventano una sola voce), ma e' cio' che un
# veterinario userebbe al telefono, e l'unicita' in archivio sta qui.

_SOLO_LETTERE = re.compile(r'[^a-z0-9 ]')


def _semplifica(testo):
    senza_accenti = unicodedata.normalize('NFKD', (testo or '').strip().lower())
    senza_accenti = ''.join(c for c in senza_accenti if not unicodedata.combining(c))
    return ' '.join(_SOLO_LETTERE.sub(' ', senza_accenti).split())


def chiave_archivio(nome, specie, cognome_proprietario=''):
    """`nome|SPECIE|cognome` normalizzati: la chiave di PazienteArchivio."""
    return '|'.join((_semplifica(nome), (specie or '').upper(), _semplifica(cognome_proprietario)))
