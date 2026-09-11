"""
B-mode o color Doppler dai pixel della miniatura, senza AI.

Un fotogramma B-mode e' in scala di grigi: gli unici pixel saturi sono le
scritte colorate dell'ecografo, il tracciato ECG (verde) e qualche linea di
misura. Un fotogramma color Doppler ha il riquadro colore (rosso-giallo
verso la sonda, blu-azzurro in allontanamento) e SEMPRE la barra della scala
colore, che contiene sia rosso sia blu.

Si conta, sulla miniatura ridotta a 200 px, la frazione di pixel saturi
(S > 0,45 e V > 0,25 in HSV) che non sono verdi (tinta fuori da 70-170
gradi: il tracciato ECG e i marcatori verdi non contano), escludendo la
fascia alta (6 %: nome del paziente, intestazione) e la fascia bassa
(15 %: tracciato ECG, barra dei fotogrammi). Tre esiti:

- `color`   frazione >= 1,5 % e presenti sia rossi sia blu (>= 0,15 % ciascuno);
- `bmode`   frazione <= 0,4 %;
- `incerto` in mezzo (nessun vincolo sulle righe).

Tarato sulle 40 immagini del catalogo (eco/catalogo/img): i fotogrammi
B-mode veri stanno sotto lo 0,2 %; le linee di misura colorate su
un'immagine arrivano allo 0,7 % (restano sotto la soglia del color); una
mappa di grigi «virata» (seppia, bronzo) ha una tinta sola e non passa la
regola rossi+blu. I test sono in eco/tests_smistamento.py.

Un filmato color in diastole puo' avere poco colore a meta' durata: per
questo il browser sceglie, fra tre fotogrammi (30, 50, 70 %), quello con
piu' pixel colorati (static/consulti/js/anteprime.js).
"""

import io

from .dati import BMODE, COLOR, INCERTO

LATO_ANALISI = 200
TAGLIO_ALTO = 0.06
TAGLIO_BASSO = 0.15
SOGLIA_S = 115       # 0,45 su 255
SOGLIA_V = 64        # 0,25 su 255
SOGLIA_COLOR = 0.015
SOGLIA_BMODE = 0.004
SOGLIA_TINTA = 0.0015


def misura(immagine):
    """(frazione colorata, frazione rossi-gialli, frazione blu) di
    un'immagine Pillow o di byte JPEG/PNG."""
    from PIL import Image
    if isinstance(immagine, (bytes, bytearray)):
        immagine = Image.open(io.BytesIO(immagine))
    im = immagine.convert('RGB')
    im.thumbnail((LATO_ANALISI, LATO_ANALISI))
    larghezza, altezza = im.size
    zona = im.crop((0, int(altezza * TAGLIO_ALTO), larghezza, int(altezza * (1 - TAGLIO_BASSO))))
    dati = zona.convert('HSV').tobytes()
    totale = len(dati) // 3
    if not totale:
        return 0.0, 0.0, 0.0
    rossi = blu = 0
    for i in range(0, len(dati), 3):
        if dati[i + 1] < SOGLIA_S or dati[i + 2] < SOGLIA_V:
            continue
        tinta = dati[i] * 360 / 255
        if 70 <= tinta <= 170:
            continue            # verde: ECG, marcatori
        if 170 < tinta < 280:
            blu += 1            # azzurro-blu-viola
        else:
            rossi += 1          # rosso-arancio-giallo-magenta
    return (rossi + blu) / totale, rossi / totale, blu / totale


def classifica(immagine):
    """('color' | 'bmode' | 'incerto', frazione colorata)."""
    frazione, rossi, blu = misura(immagine)
    if frazione >= SOGLIA_COLOR and rossi >= SOGLIA_TINTA and blu >= SOGLIA_TINTA:
        return COLOR, frazione
    if frazione <= SOGLIA_BMODE:
        return BMODE, frazione
    return INCERTO, frazione
