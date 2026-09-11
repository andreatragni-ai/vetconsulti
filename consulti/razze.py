"""
Le razze per il passo 1 della richiesta: un elenco per specie, in cui chi
compila scrive per filtrare (static/consulti/js/elenco_filtrato.js).

## Da dove vengono

COPIATE da VetCardio, `templates/cardio/scheda_esame.html` (oggetto JS
`RAZZE`, chiavi "Cane" e "Gatto"; commit e440af2 del 10/09/2026): 207 razze
canine e 58 feline, «meticcio» in testa, nello stesso ordine. Il portale non
importa mai da `cardio`: se l'elenco di VetCardio cambia, qui si ricopia a
mano. Le chiavi sono i valori di `consulti.models.Specie`.

## Una razza fuori elenco si accetta

Chi compila puo' scrivere una razza che non c'e' (un incrocio, un nome
straniero): il campo resta libero e la pagina lo segnala con un avviso
discreto. Se invece corrisponde a una voce dell'elenco, a meno di maiuscole
e accenti, si salva scritta come nell'elenco (`normalizza`).

## Il filtro

`filtra` e' la stessa regola del JS: minuscole senza accenti, prima le voci
che INIZIANO con il testo, poi quelle che lo CONTENGONO, ciascun gruppo
nell'ordine dell'elenco (cosi' «meticcio» resta in testa quando c'entra).
Il JS la ripete lato browser; qui c'e' per i test e per chi la vuole
leggere.
"""

import unicodedata

# Specie.CANE: 207 razze, «meticcio» in testa.
CANE = [
    'meticcio', 'Affenpinscher', 'Akita Inu', 'Alano', 'Alaskan Malamute', 'American Akita',
    'American Bulldog', 'American Staffordshire Terrier', 'Anatolian Shepherd', 'Australian Shepherd',
    'Barbone', 'Barbone Grande Mole', 'Barbone Media Mole', 'Barbone Nano', 'Barboncino', 'Barboncino Nano',
    'Barboncino Toy', 'Basenji', 'Basset Hound', 'Bassotto', 'Bassotto Nano', 'Bassotto Pelo Corto',
    'Bassotto Pelo Lungo', 'Bassotto Tedesco', 'Bassotto Tedesco Pelo Lungo',
    'Bassotto Tedesco Pelo Ruvido', 'Beagle', 'Bearded Collie', 'Bernese', 'Bichon Avanese', 'Bichon Frisé',
    'Black Russian Terrier', 'Bobtail', 'Bolognese', 'Border Collie', 'Border Terrier', 'Boston Terrier',
    'Bouledogue Francese', 'Bovaro del Bernese', "Bovaro dell'Appenzell", "Bovaro dell'Entlebuch",
    'Bovaro delle Fiandre', 'Boxer', 'Bracco', 'Bracco Italiano', 'Bracco Tedesco', 'Bracco Ungherese',
    'Breton', 'Briard', 'Broholmer', 'Bull Terrier', 'Bulldog', 'Bulldog Francese', 'Bulldog Inglese',
    'Bullmastiff', 'Cairn Terrier', 'Cane Corso', 'Cane da Pastore Australiano', 'Cane da Pastore Belga',
    'Cane da Pastore Bergamasco', 'Cane da Pastore Tedesco', 'Cane della Beauce', "Cane d'Acqua Portoghese",
    'Cane Lupo Cecoslovacco', 'Cane Nudo Cinese', 'Cane Nudo del Messico', 'Cane Pastore',
    'Cane Pastore Svizzero', 'Carlino', 'Cavalier King Charles Spaniel', 'Chien Spaniel Giapponese',
    'Chihuahua', 'Chow Chow', "Cirneco dell'Etna", 'Cocker Spaniel', 'Cocker Spaniel Americano',
    'Cocker Spaniel Inglese', 'Collie', 'Coton de Tulear', 'Dachshund', 'Dalmata', 'Dobermann',
    'Dogo Argentino', 'Dogue de Bordeaux', 'Drahthaar', 'English Setter', 'Epagneul Breton',
    'Epagneul Breton Cocker', 'Fila Brasileiro', 'Flatcoated Retriever', 'Fox Terrier', 'Golden Retriever',
    'Gordon Setter', 'Gran Danese', 'Grande Bovaro Svizzero', 'Greyhound', 'Griffone di Bruxelles',
    'Hovawart', 'Husky', 'Husky Siberiano', 'Incrocio', 'Incrocio Breton', 'Incrocio Labrador',
    'Incrocio Maltese', 'Incrocio Pitbull', 'Irish Setter', 'Jack Russell Terrier', 'Kelpie Australiano',
    'Komondor', 'Kurzhaar', 'Labrador Retriever', 'Labrador x Terranova', 'Lagotto Romagnolo', 'Leonberger',
    'Levriero Afgano', 'Levriero Inglese', 'Levriero Irlandese', 'Levriero Italiano', 'Levriero Persiano',
    'Levriero Spagnolo', 'Lhasa Apso', 'Lucas Terrier', 'Lupo Cecoslovacco', 'Lupo Italiano', 'Maltese',
    'Maremma', 'Mastiff', 'Mastino dei Pirenei', 'Mastino Napoletano', 'Mastino Tibetano',
    'Meticcio Border Collie', 'Meticcio Breton', 'Meticcio Pastore Bergamasco', 'Meticcio Pastore Tedesco',
    'Newfoundland', 'Norsk Elkhound', 'Old English Bulldog', 'Olde English Bulldogge', 'Papillon',
    'Pastore Australiano', 'Pastore Australiano Kelpie', 'Pastore Belga', 'Pastore Belga Malinois',
    'Pastore Bergamasco', 'Pastore Bianco Svizzero', 'Pastore Caucaso', 'Pastore dei Pirenei',
    'Pastore del Bernese', 'Pastore del Caucaso', "Pastore dell'Anatolia", "Pastore dell'Asia Centrale",
    'Pastore della Brie', 'Pastore Maremmano', 'Pastore Polacco', 'Pastore Scozzese', 'Pastore Tedesco',
    'Pechinese', 'Pharaoh Hound', 'Piccolo Levriero Italiano', 'Pinscher', 'Pinscher Nano', 'Pitbull',
    'Pointer', 'Pomerania', 'Poodle', 'Presa Canario', 'Pug', 'Rhodesian Ridgeback', 'Riesenschnauzer',
    'Rottweiler', 'Saluki', 'Samoiedo', 'San Bernardo', 'Schnauzer', 'Schnauzer Gigante', 'Schnauzer Nano',
    'Scottish Terrier', 'Sealyham Terrier', 'Segugio', 'Segugio Italiano', 'Setter Inglese',
    'Setter Irlandese', 'Shar Pei', 'Shetland Sheepdog', 'Shiba Inu', 'Shih Tzu', 'Spaniel',
    'Spino degli Iblei', 'Spinone Italiano', 'Spitz Tedesco', 'Spitz Tedesco Nano', 'Springer Spaniel',
    'Staffordshire Bull Terrier', 'Terranova', 'Tibetan Spaniel', 'Tibetan Terrier', 'Tosa',
    'Toy Terrier Russo', 'Volpino Bianco', 'Volpino di Pomerania', 'Volpino Italiano', 'Weimaraner',
    'Welsh Corgi', 'Welsh Terrier', 'West Highland White Terrier', 'Whippet', 'Yorkshire Terrier',
]

# Specie.GATTO: 58 razze, «meticcio» in testa.
GATTO = [
    'meticcio', 'Abissino', 'American Curl', 'American Shorthair', 'American Wirehair', 'Angora Turco',
    'Balinese', 'Bengala', 'Birmano', 'Bombay', 'British Longhair', 'British Shorthair', 'Burmese',
    'Certosino', 'Chartreux', 'Comune Europeo', 'Cornish Rex', 'Devon Rex', 'Egeo', 'Esotico a Pelo Corto',
    'Exotic Shorthair', 'Havana Brown', 'Highland Fold', 'Himalayano', 'Javanese', 'LaPerm', 'Maine Coon',
    'Manx', 'Mau Egiziano', 'Munchkin', 'Nebelung', 'Norvegese delle Foreste', 'Norwegian Forest Cat',
    'Ocicat', 'Orientale', 'Persiano', 'Peterbald', 'Pixie Bob', 'Ragamuffin', 'Ragdoll', 'Rex Cornish',
    'Russian Blue', 'Sacro di Birmania', 'Savannah', 'Scottish Fold', 'Scottish Straight', 'Selkirk Rex',
    'Siamese', 'Siberiano', 'Singapura', 'Sphynx', 'Snowshoe', 'Somalo', 'Thai', 'Tonkinese',
    'Turco di Van', 'Turkish Angora', 'Turkish Van',
]


RAZZE = {'CANE': CANE, 'GATTO': GATTO}


def _piano(testo):
    """Minuscole, senza accenti, spazi compattati: «Bichon Frisé» -> «bichon frise»."""
    testo = unicodedata.normalize('NFD', testo or '')
    testo = ''.join(c for c in testo if unicodedata.category(c) != 'Mn')
    return ' '.join(testo.lower().split())


def elenco(specie):
    """Le razze della specie ([] se la specie non e' scelta o non esiste)."""
    return RAZZE.get(specie or '', [])


def filtra(specie, testo):
    """Le voci della specie che corrispondono a `testo` (tutte se e' vuoto)."""
    voci = elenco(specie)
    cerca = _piano(testo)
    if not cerca:
        return list(voci)
    iniziano = [v for v in voci if _piano(v).startswith(cerca)]
    contengono = [v for v in voci if cerca in _piano(v) and not _piano(v).startswith(cerca)]
    return iniziano + contengono


def in_elenco(specie, razza):
    return normalizza(specie, razza) in elenco(specie)


def normalizza(specie, razza):
    """La razza come sta nell'elenco della specie se corrisponde a meno di
    maiuscole e accenti («maine coon» -> «Maine Coon»); altrimenti com'e'
    stata scritta, senza spazi in piu'."""
    razza = ' '.join((razza or '').split())
    piano = _piano(razza)
    for voce in elenco(specie):
        if _piano(voce) == piano:
            return voce
    return razza
