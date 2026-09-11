"""Rendering del referto in PDF con WeasyPrint.

Due sorgenti di testo: una `VersioneReferto` (il documento firmato, quello
che esce dal portale) oppure la copia di lavoro `Referto` (anteprima del
refertatore, stampata con la scritta BOZZA). L'import di weasyprint e'
dentro la funzione: sul Mac senza le librerie di sistema l'app deve
comunque partire (in locale serve DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib).
"""

from pathlib import Path

from django.core.files.base import ContentFile
from django.template.loader import render_to_string

from .blocchi import classificazione_leggibile


def _uri_firma(refertatore):
    """L'immagine della firma come URI file:// per WeasyPrint; None se non
    c'e'. Con uno storage non su disco (S3) si usa l'URL."""
    if refertatore is None or not refertatore.firma:
        return None
    try:
        return Path(refertatore.firma.path).as_uri()
    except NotImplementedError:
        return refertatore.firma.url


def html_referto(referto, versione=None):
    """HTML del referto. Con `versione` stampa quella (firmata); senza,
    la copia di lavoro come anteprima non firmata."""
    richiesta = referto.richiesta
    testo = versione if versione is not None else referto
    firmato = versione is not None
    refertatore = richiesta.refertatore
    return render_to_string('referti/referto_pdf.html', {
        'referto': referto, 'testo': testo, 'firmato': firmato, 'versione': versione,
        'richiesta': richiesta, 'paziente': getattr(richiesta, 'paziente', None),
        'intestatario': richiesta.intestatario(), 'clinica': richiesta.clinica,
        'dati_fiscali': richiesta.intestatario().dati_fatturazione_predefiniti,
        'refertatore': refertatore,
        'firma_uri': _uri_firma(refertatore) if firmato else None,
        'classificazione': classificazione_leggibile(richiesta.tipo_esame, testo.classificazione),
    })


def genera_pdf(referto, versione=None):
    from weasyprint import HTML
    return HTML(string=html_referto(referto, versione)).write_pdf()


def nome_file(versione):
    return f'{versione.referto.richiesta.codice}_v{versione.numero}.pdf'


def genera_e_salva(versione):
    """Genera il PDF di una versione firmata e lo lega alla versione e, se e'
    l'ultima, al referto (stesso file, non una copia)."""
    referto = versione.referto
    contenuto = genera_pdf(referto, versione)
    versione.pdf.save(nome_file(versione), ContentFile(contenuto), save=True)
    if versione.numero == referto.versione:
        referto.pdf.name = versione.pdf.name
        referto.save(update_fields=['pdf'])
    return versione.pdf


def contenuto_pdf(versione):
    """I byte del PDF di una versione, generandolo se manca (es. WeasyPrint
    non disponibile al momento della firma). None se non si riesce."""
    if not versione.pdf:
        try:
            genera_e_salva(versione)
        except Exception:
            return None
    with versione.pdf.open('rb') as f:
        return f.read()
