"""
File finti per i casi dimostrativi di `seed_demo`: un PDF segnato in grande
DIMOSTRATIVO (tracciato ECG sintetico o referto dell'ecografo inventato) e
immagini PNG segnaposto per le proiezioni eco. Nessun file reale di pazienti.

Il PDF e' costruito a mano (poche righe di PostScript-like PDF, font base
Helvetica): cosi' `seed_demo` non dipende da WeasyPrint e dalle librerie di
sistema che sul Mac vogliono DYLD_FALLBACK_LIBRARY_PATH.
"""

import io
import math


def _stringa_pdf(testo):
    return '(' + testo.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') + ')'


def _testo(x, y, dimensione, testo, font='F2', grigio=0.0, angolo=0):
    c, s = math.cos(math.radians(angolo)), math.sin(math.radians(angolo))
    return (f'BT /{font} {dimensione} Tf {grigio:.2f} g {c:.4f} {s:.4f} {-s:.4f} {c:.4f} {x:.1f} {y:.1f} Tm '
            f'{_stringa_pdf(testo)} Tj ET')


def _assembla(larghezza, altezza, contenuto):
    """Un PDF valido di una pagina con Helvetica e Helvetica-Bold."""
    flusso = contenuto.encode('latin-1')
    oggetti = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {larghezza} {altezza}] '
         f'/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>').encode(),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(flusso)).encode() + b' >>\nstream\n' + flusso + b'\nendstream',
    ]
    uscita = io.BytesIO()
    uscita.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    posizioni = []
    for i, corpo in enumerate(oggetti, start=1):
        posizioni.append(uscita.tell())
        uscita.write(f'{i} 0 obj\n'.encode() + corpo + b'\nendobj\n')
    inizio_xref = uscita.tell()
    uscita.write(f'xref\n0 {len(oggetti) + 1}\n0000000000 65535 f \n'.encode())
    for p in posizioni:
        uscita.write(f'{p:010d} 00000 n \n'.encode())
    uscita.write(f'trailer\n<< /Size {len(oggetti) + 1} /Root 1 0 R >>\nstartxref\n{inizio_xref}\n%%EOF\n'.encode())
    return uscita.getvalue()


def _battito(x0, y0, passo):
    """Punti di un complesso PQRST sintetico largo `passo` punti."""
    forma = [(0, 0), (.10, 0), (.14, 4), (.18, 0), (.26, 0), (.28, -5), (.31, 38), (.34, -10), (.37, 0),
             (.50, 0), (.56, 8), (.62, 9), (.68, 0), (1, 0)]
    return [(x0 + fx * passo, y0 + fy) for fx, fy in forma]


def pdf_ecg_dimostrativo(titolo='ECG DIMOSTRATIVO'):
    """A4 orizzontale: carta millimetrata, tre strisce di ritmo sinusale
    sintetico, la scritta DIMOSTRATIVO in diagonale."""
    larghezza, altezza = 842, 595
    mm = 72 / 25.4
    righe = []
    # Carta ECG: quadretti da 1 mm chiari, da 5 mm piu' marcati.
    for passo, spessore, colore in ((mm, 0.2, '1 0.88 0.88'), (5 * mm, 0.5, '0.95 0.65 0.65')):
        righe.append(f'{colore} RG {spessore} w')
        x = 0.0
        while x <= larghezza:
            righe.append(f'{x:.2f} 40 m {x:.2f} {altezza - 60} l S')
            x += passo
        y = 40.0
        while y <= altezza - 60:
            righe.append(f'0 {y:.2f} m {larghezza} {y:.2f} l S')
            y += passo
    righe.append(_testo(150, 110, 110, 'DIMOSTRATIVO', font='F1', grigio=0.82, angolo=22))
    # Tre strisce di ritmo: 25 mm/s, circa 100 bpm.
    righe.append('0 0 0 RG 0.9 w 1 J 1 j')
    for y0 in (430, 290, 150):
        punti = []
        x = 20.0
        while x < larghezza - 60:
            punti.extend(_battito(x, y0, 0.6 * 25 * mm))
            x += 0.6 * 25 * mm
        righe.append(f'{punti[0][0]:.2f} {punti[0][1]:.2f} m ' +
                     ' '.join(f'{px:.2f} {py:.2f} l' for px, py in punti[1:]) + ' S')
    righe.append(_testo(24, altezza - 32, 14, titolo, font='F1'))
    righe.append(_testo(24, altezza - 50, 9, 'Tracciato sintetico generato da seed_demo: nessun paziente reale. '
                                             '25 mm/s - 10 mm/mV - derivazione II.'))
    for y0, nome in ((430, 'II'), (290, 'II'), (150, 'II')):
        righe.append(_testo(24, y0 + 48, 9, nome, font='F1'))
    return _assembla(larghezza, altezza, '\n'.join(righe))


def pdf_referto_ecografo_dimostrativo(titolo='Referto ecografo DIMOSTRATIVO'):
    """A4 verticale: un finto referto dell'ecografo con misure inventate."""
    larghezza, altezza = 595, 842
    righe = [_testo(60, 250, 90, 'DIMOSTRATIVO', font='F1', grigio=0.85, angolo=40)]
    righe.append(_testo(50, altezza - 60, 16, titolo, font='F1'))
    righe.append(_testo(50, altezza - 80, 9, 'Documento generato da seed_demo per il collaudo: '
                                              'misure inventate, nessun paziente reale.'))
    misure = [('IVSd', '0,52 cm'), ('LVIDd', '1,48 cm'), ('LVPWd', '0,50 cm'), ('IVSs', '0,78 cm'),
              ('LVIDs', '0,82 cm'), ('LVPWs', '0,79 cm'), ('FS', '44 %'), ('LA', '1,21 cm'),
              ('Ao', '0,92 cm'), ('LA/Ao', '1,32'), ('E mitrale', '0,78 m/s'), ('A mitrale', '0,60 m/s')]
    y = altezza - 130
    righe.append('0.4 G 0.5 w')
    for nome, valore in misure:
        righe.append(_testo(70, y, 11, nome, font='F1'))
        righe.append(_testo(220, y, 11, valore))
        righe.append(f'60 {y - 6:.1f} m 400 {y - 6:.1f} l S')
        y -= 26
    return _assembla(larghezza, altezza, '\n'.join(righe))


def png_proiezione_dimostrativa(nome_proiezione, larghezza=800, altezza=600):
    """Segnaposto di una proiezione eco: settore scuro come sull'ecografo,
    due ellissi per le camere, DIMOSTRATIVO e il nome della proiezione."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGB', (larghezza, altezza), (8, 10, 14))
    d = ImageDraw.Draw(img)
    cx, top = larghezza // 2, 30
    raggio = altezza - 60
    d.pieslice([cx - raggio, top - raggio, cx + raggio, top + raggio], 50, 130, fill=(46, 50, 56))
    d.ellipse([cx - 150, 220, cx - 10, 420], outline=(150, 150, 150), width=4)
    d.ellipse([cx + 10, 240, cx + 140, 400], outline=(120, 120, 120), width=4)

    def font(dimensione):
        try:
            return ImageFont.load_default(size=dimensione)
        except TypeError:  # Pillow senza FreeType: font bitmap fisso
            return ImageFont.load_default()

    d.text((cx, 95), 'DIMOSTRATIVO', fill=(230, 190, 60), font=font(64), anchor='mm')
    d.text((cx, altezza - 70), nome_proiezione[:60], fill=(220, 220, 220), font=font(26), anchor='mm')
    d.text((cx, altezza - 35), 'immagine segnaposto di seed_demo - nessun paziente reale',
           fill=(150, 150, 150), font=font(16), anchor='mm')
    uscita = io.BytesIO()
    img.save(uscita, format='PNG')
    return uscita.getvalue()
