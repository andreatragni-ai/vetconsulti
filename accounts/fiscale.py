"""
Validazioni fiscali italiane, senza dipendenze da Django.

Stanno in un modulo a parte perche' si testano da sole e perche' le stesse
regole servono sia ai dati di fatturazione della clinica sia a quelli del
refertatore che emette in proprio. Ogni funzione solleva ValueError con un
messaggio pensato per chi compila il form, non per chi legge il log.
"""

import re

_SOLO_CIFRE = re.compile(r'^\d+$')
_ALFANUMERICO = re.compile(r'^[A-Z0-9]+$')
_CF_PERSONA = re.compile(r'^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$')


def normalizza(valore):
    return (valore or '').strip().upper().replace(' ', '')


def valida_partita_iva(valore):
    """Undici cifre con check digit (algoritmo Luhn variante italiana).

    Ritorna la P.IVA normalizzata. Il check digit prende gli errori di
    battitura piu' comuni — due cifre invertite, una cifra sbagliata — che
    sono esattamente quelli che si scoprono quando la fattura torna indietro.
    """
    piva = normalizza(valore)
    if len(piva) != 11 or not _SOLO_CIFRE.match(piva):
        raise ValueError('La partita IVA deve essere di 11 cifre.')
    somma = 0
    for i, c in enumerate(piva[:10]):
        n = int(c)
        if i % 2 == 0:
            somma += n
        else:
            n *= 2
            somma += n if n < 10 else n - 9
    controllo = (10 - somma % 10) % 10
    if controllo != int(piva[10]):
        raise ValueError('Partita IVA non valida: la cifra di controllo non torna.')
    return piva


def valida_codice_fiscale(valore):
    """Sedici caratteri alfanumerici (persona fisica) oppure 11 cifre
    (soggetto giuridico, coincide con la P.IVA). Ritorna il valore
    normalizzato.

    Per le persone fisiche si verifica solo la struttura (posizioni lettere/
    cifre, con le lettere di omocodia ammesse nei campi numerici), non il
    carattere di controllo: lo scopo e' bloccare un numero di telefono
    incollato nel campo sbagliato, non rifare l'Agenzia delle Entrate.
    """
    cf = normalizza(valore)
    if len(cf) == 11:
        if not _SOLO_CIFRE.match(cf):
            raise ValueError('Il codice fiscale di 11 caratteri deve essere numerico.')
        return cf
    if len(cf) == 16:
        if not _CF_PERSONA.match(cf):
            raise ValueError('Codice fiscale di 16 caratteri non valido nella struttura.')
        return cf
    raise ValueError('Il codice fiscale deve essere di 16 caratteri (persona) o 11 cifre (societa\').')


def valida_codice_sdi(valore):
    """Esattamente 7 caratteri alfanumerici. '0000000' e' il valore che
    l'SdI accetta quando la fattura va per PEC o al cassetto fiscale."""
    sdi = normalizza(valore)
    if len(sdi) != 7 or not _ALFANUMERICO.match(sdi):
        raise ValueError('Il codice destinatario SDI deve essere di 7 caratteri alfanumerici.')
    return sdi


SDI_NULLO = '0000000'


def recapito_fattura_valido(codice_sdi, pec_fatturazione):
    """Una fattura elettronica deve poter arrivare da qualche parte: o un
    codice SDI vero, o una PEC. Con SDI '0000000' e PEC vuota finirebbe solo
    nel cassetto fiscale e nessuno se ne accorgerebbe."""
    return normalizza(codice_sdi) != SDI_NULLO or bool((pec_fatturazione or '').strip())
