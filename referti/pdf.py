"""Rendering del referto in PDF con WeasyPrint. L'import di weasyprint e'
dentro la funzione: sul Mac senza le librerie di sistema l'app deve
comunque partire."""

from django.core.files.base import ContentFile
from django.template.loader import render_to_string


def html_referto(referto):
    richiesta = referto.richiesta
    return render_to_string('referti/referto_pdf.html', {
        'referto': referto, 'richiesta': richiesta, 'paziente': getattr(richiesta, 'paziente', None),
        'intestatario': richiesta.intestatario(), 'clinica': richiesta.clinica,
        'dati_fiscali': richiesta.intestatario().dati_fatturazione_predefiniti,
        'refertatore': richiesta.refertatore,
    })


def genera_pdf(referto):
    from weasyprint import HTML
    return HTML(string=html_referto(referto)).write_pdf()


def genera_e_salva(referto):
    contenuto = genera_pdf(referto)
    referto.pdf.save(f'{referto.richiesta.codice}_v{referto.versione}.pdf', ContentFile(contenuto), save=True)
    return referto.pdf
