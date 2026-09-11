"""
La richiesta di consulto guidata: quattro passi visibili.

    1 Paziente  ->  2 Esame ed esperto  ->  3 Carica gli esami  ->  4 Invia

La Richiesta in BOZZA nasce alla fine del passo 2 (come prima): il codice
TC-AAAA-NNNN non si consuma per una bozza abbandonata al primo passo. Fino
ad allora i dati del paziente stanno in sessione (`SESSIONE_PAZIENTE`, i
valori grezzi del form, rivalidati alla creazione).

Ogni passo salva, e finche' il caso e' in BOZZA si torna indietro a
correggere. Aprendo una bozza dall'elenco si riprende dal primo passo
incompleto (`passo_da_riprendere`). Cosa manca per inviare lo decide
sempre `regole.perche_non_puoi_inviare`; qui si usa la stessa regola per
dire quale passo e' completo, non se ne scrive un'altra.
"""

from datetime import timedelta

from django.urls import reverse

from . import regole

SESSIONE_PAZIENTE = 'richiesta_guidata_paziente'
SESSIONE_ESAME = 'richiesta_guidata_esame'

PASSI = (
    (1, 'paziente', 'Paziente'),
    (2, 'esame', 'Esame ed esperto'),
    (3, 'carica', 'Carica gli esami'),
    (4, 'riepilogo', 'Invia'),
)

NOMI_URL = {1: 'consulti:passo_paziente', 2: 'consulti:passo_esame', 3: 'consulti:passo_carica',
            4: 'consulti:passo_riepilogo'}


def esperti_con_prezzo(tipo, urgenza=False):
    """Refertatori referenti per il tipo, con prezzo, tempo di risposta e
    disponibilita' accanto. Gli assenti ci sono (con il rientro): si vedono,
    non si scelgono. Con l'urgenza il tempo e' sempre 4 ore e chi non accetta
    urgenze per quel tipo si vede, ma non si sceglie (`no_urgenze`)."""
    from accounts.models import Refertatore
    from listino.prezzi import PrezzoNonDisponibile, prezzo_effettivo

    righe = []
    for r in Refertatore.referenti_per(tipo):
        comp = r.competenza_per(tipo)
        try:
            prezzo = prezzo_effettivo(tipo, refertatore=r, urgenza=urgenza)
        except PrezzoNonDisponibile:
            prezzo = None
        accetta = bool(comp and comp.accetta_urgenze)
        no_urgenze = bool(urgenza and not accetta)
        righe.append({'refertatore': r, 'prezzo': prezzo, 'disponibile': r.disponibile_oggi,
                      'rientro': r.assente_al + timedelta(days=1) if r.assente_al else None,
                      'tempo': regole.ORE_RISPOSTA_URGENZA if urgenza else (comp.tempo_risposta_ore if comp else None),
                      'accetta_urgenze': accetta, 'no_urgenze': no_urgenze,
                      'sceglibile': r.disponibile_oggi and not no_urgenze})
    return righe


def url_passo(richiesta, numero):
    return reverse(NOMI_URL[numero], args=[richiesta.pk])


def passo_1_completo(richiesta):
    return getattr(richiesta, 'paziente', None) is not None


def passo_2_completo(richiesta):
    """Esperto referente per il tipo (che accetta urgenze, se il caso e'
    urgente) e quesito scritto: cio' che il form del passo 2 pretende.
    L'assenza dell'esperto non conta qui: il riepilogo la segnala, e la
    regola di invio non la guarda."""
    ref = richiesta.refertatore
    return bool(ref is not None and ref.referta(richiesta.tipo_esame) and (richiesta.quesito or '').strip()
                and not regole.rifiuta_urgenza(ref, richiesta.tipo_esame, richiesta.urgenza))


def passo_3_completo(richiesta):
    return not regole.allegati_mancanti(richiesta)


def passo_da_riprendere(richiesta):
    """Il primo passo incompleto di una bozza (4 se e' tutto pronto)."""
    if not passo_1_completo(richiesta):
        return 1
    if not passo_2_completo(richiesta):
        return 2
    if not passo_3_completo(richiesta):
        return 3
    return 4


def indicatore(attuale, richiesta=None, paziente_in_sessione=False):
    """Le voci dell'indicatore in cima: [{numero, etichetta, url, stato}],
    stato 'attuale' | 'fatto' | 'da-fare'. `url` e' None dove non si puo'
    andare (il passo corrente, o i passi 3-4 prima che la bozza esista)."""
    completi = {}
    if richiesta is not None:
        completi = {1: passo_1_completo(richiesta), 2: passo_2_completo(richiesta),
                    3: passo_3_completo(richiesta), 4: False}
    else:
        completi = {1: paziente_in_sessione}
    voci = []
    for numero, _nome, etichetta in PASSI:
        if richiesta is not None:
            url = url_passo(richiesta, numero)
        elif numero == 1:
            url = reverse('consulti:nuova')
        elif numero == 2 and paziente_in_sessione:
            url = reverse('consulti:nuova_esame')
        else:
            url = None
        if numero == attuale:
            stato, url = 'attuale', None
        elif completi.get(numero):
            stato = 'fatto'
        else:
            stato = 'da-fare'
        voci.append({'numero': numero, 'etichetta': etichetta, 'url': url, 'stato': stato})
    return voci
