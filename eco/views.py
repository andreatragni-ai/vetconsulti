"""
Il protocollo stampabile delle proiezioni eco: il catalogo attivo per
finestra acustica, nell'ordine di acquisizione, con per ogni riga la prima
immagine di riferimento, il nome, filmato o immagine, come si acquisisce e
cosa deve vedersi. Da tenere accanto all'ecografo (decisione di Andre
dell'11/09/2026). Pagina per chi e' autenticato, con CSS di stampa A4, e
PDF con WeasyPrint.

Lo stesso ordine delle righe del passo 3 e dello smistamento automatico
(eco.models.in_ordine): acquisire in quest'ordine rende piu' preciso lo
smistamento, e la pagina lo dice.
"""

import base64

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import content_disposition_header

from .models import ORDINE_FINESTRE, Finestra, ProiezioneCatalogo, in_ordine

MEDIA = {'CLIP': ('camera-reels', 'Filmato'), 'STATICA': ('image', 'Immagine'),
         'ENTRAMBI': ('collection-play', 'Filmato o immagine')}
CONSIGLIO = ('Acquisisci nell\'ordine del protocollo: lo smistamento automatico dei file sara\' piu\' preciso.')


def _src_pdf(immagine):
    """L'immagine di riferimento come data URI ridotto (il PDF resta leggero
    e WeasyPrint non deve leggere da MEDIA_ROOT)."""
    from consulti.anteprime import AnteprimaNonValida, jpeg_ridotto
    try:
        with immagine.immagine.open('rb') as f:
            dati = jpeg_ridotto(f, lato_max=640)
    except (OSError, AnteprimaNonValida):
        return None
    return 'data:image/jpeg;base64,' + base64.standard_b64encode(dati).decode('ascii')


def contesto_protocollo(per_pdf=False):
    catalogo = in_ordine(ProiezioneCatalogo.objects.filter(attiva=True).prefetch_related('immagini'))
    numero = 0

    def riga(p):
        nonlocal numero
        numero += 1
        immagine = next(iter(p.immagini.all()), None)
        src = None
        if immagine is not None:
            src = _src_pdf(immagine) if per_pdf else reverse('immagine_riferimento', args=[immagine.pk])
        icona, media = MEDIA.get(p.tipo_media, MEDIA['ENTRAMBI'])
        return {'numero': numero, 'p': p, 'immagine': immagine, 'src': src, 'icona': icona, 'media': media}

    gruppi = []
    for finestra in ORDINE_FINESTRE:
        della = [p for p in catalogo if p.finestra == finestra and not p.libera]
        if della:
            gruppi.append({'etichetta': 'Altre proiezioni' if finestra == Finestra.ALTRO else Finestra(finestra).label,
                           'righe': [riga(p) for p in della]})
    liberi = [riga(p) for p in catalogo if p.libera]
    return {'gruppi': gruppi, 'liberi': liberi, 'consiglio': CONSIGLIO,
            'totale': sum(len(g['righe']) for g in gruppi),
            'obbligatorie': sum(1 for p in catalogo if p.obbligatoria)}


@login_required
def protocollo(request):
    return render(request, 'eco/protocollo.html', contesto_protocollo())


@login_required
def protocollo_pdf(request):
    from weasyprint import HTML
    html = render_to_string('eco/protocollo_pdf.html', contesto_protocollo(per_pdf=True))
    pdf = HTML(string=html).write_pdf()
    risposta = HttpResponse(pdf, content_type='application/pdf')
    risposta['Content-Disposition'] = content_disposition_header(True, 'protocollo_proiezioni_eco.pdf')
    return risposta
