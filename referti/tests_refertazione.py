"""Test della pagina di refertazione, della firma, della rettifica e dello
storico delle versioni (F3). Fixture in conftest.py: mondo, caso_inviato,
caso_in_carico, pdf_finto, weasyprint_vero."""

from html.parser import HTMLParser

import pytest
from django.core import mail
from django.urls import reverse

from conftest import PDF_FINTO
from consulti.models import StatoRichiesta
from notifiche.models import InvioEmail, TipoInvio
from referti.models import Referto, VersioneReferto
from registro.models import Prestazione

TESTI = {'descrizione': 'Ritmo sinusale, FC 120 bpm.', 'conclusioni': 'ECG nella norma.',
         'raccomandazioni': 'Nessuna controindicazione.', 'cl_rischio_anestesia': 'BASSO'}


def _salva(client, richiesta, htmx=False, **dati):
    extra = {'HTTP_HX_REQUEST': 'true'} if htmx else {}
    return client.post(reverse('referti:salva_bozza', args=[richiesta.pk]), {**TESTI, **dati}, **extra)


@pytest.fixture
def refertatore_loggato(client, mondo):
    client.force_login(mondo.ref.user)
    return client


@pytest.fixture
def firmato(refertatore_loggato, caso_in_carico, pdf_finto):
    _salva(refertatore_loggato, caso_in_carico)
    refertatore_loggato.post(reverse('referti:firma', args=[caso_in_carico.pk]))
    caso_in_carico.refresh_from_db()
    mail.outbox.clear()
    return caso_in_carico


# ── Pagina ───────────────────────────────────────────────────────────────────

def test_pagina_decisione_su_caso_inviato(refertatore_loggato, caso_inviato):
    pagina = refertatore_loggato.get(reverse('referti:refertazione', args=[caso_inviato.pk])).content.decode()
    assert 'Prendi in carico' in pagina and 'Declina con un motivo' in pagina
    assert 'Non referto gatti.' in pagina                                    # frasi rapide
    allegato = caso_inviato.allegati.get()
    assert f'{reverse("scarica_allegato", args=[allegato.pk])}?inline=1' in pagina   # visore
    assert 'id="form-referto"' not in pagina


def test_pagina_editor_su_caso_in_carico(refertatore_loggato, caso_in_carico):
    pagina = refertatore_loggato.get(reverse('referti:refertazione', args=[caso_in_carico.pk])).content.decode()
    assert 'id="form-referto"' in pagina and 'hx-trigger="submit, salva-auto"' in pagina
    assert 'Rischio anestesiologico' in pagina and 'Non valutabile su questo tracciato' in pagina
    # La firma passa dalla modale del pacchetto, su una rotta separata.
    assert 'data-elimina-intestazione="Firma del referto"' in pagina
    assert 'data-elimina-tono="primary"' in pagina
    assert f'data-elimina-href="{reverse("referti:firma", args=[caso_in_carico.pk])}"' in pagina
    # La modale e' inclusa da base.html DOPO lo script della pagina: il JS che
    # salva prima di firmare deve ascoltare sul documento (bug trovato a mano).
    assert "document.addEventListener('submit'" in pagina
    assert pagina.index("document.addEventListener('submit'") < pagina.index('id="modalConfermaElimina"')
    assert 'Il caso non e&#x27; refertabile' in pagina or "Il caso non e' refertabile" in pagina


def test_allegato_inline_per_il_visore(refertatore_loggato, caso_inviato):
    allegato = caso_inviato.allegati.get()
    risp = refertatore_loggato.get(reverse('scarica_allegato', args=[allegato.pk]) + '?inline=1')
    assert risp.status_code == 200
    assert risp['Content-Disposition'].startswith('inline')
    assert risp['X-Frame-Options'] == 'SAMEORIGIN'
    risp = refertatore_loggato.get(reverse('scarica_allegato', args=[allegato.pk]))
    assert risp['Content-Disposition'].startswith('attachment')


# ── Bozza: salvare non firma ─────────────────────────────────────────────────

def test_salvataggio_che_non_firma(refertatore_loggato, caso_in_carico):
    risp = _salva(refertatore_loggato, caso_in_carico, htmx=True)
    assert risp.status_code == 200 and 'Bozza salvata alle' in risp.content.decode()
    assert _salva(refertatore_loggato, caso_in_carico).status_code == 302
    referto = Referto.objects.get(richiesta=caso_in_carico)
    assert referto.conclusioni == 'ECG nella norma.'
    assert referto.classificazione == {'rischio_anestesia': 'BASSO'}
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.PRESA_IN_CARICO
    assert not referto.firmato and not referto.versioni.exists()
    assert not Prestazione.objects.exists() and not mail.outbox
    assert not caso_in_carico.audit.filter(azione__startswith='REFERTO').exists()


def test_salvataggio_voce_non_valida(refertatore_loggato, caso_in_carico):
    risp = _salva(refertatore_loggato, caso_in_carico, htmx=True, cl_rischio_anestesia='ALTISSIMO')
    assert risp.status_code == 400 and 'Non salvato' in risp.content.decode()


def test_solo_il_refertatore_assegnato_salva_e_firma(client, caso_in_carico, mondo, pdf_finto):
    for utente in (mondo.ref2.user, mondo.richiedente.user, mondo.staff, mondo.estraneo):
        client.force_login(utente)
        assert _salva(client, caso_in_carico).status_code == 404
        assert client.post(reverse('referti:firma', args=[caso_in_carico.pk])).status_code == 404
        assert client.get(reverse('referti:anteprima', args=[caso_in_carico.pk])).status_code == 404
    assert not Referto.objects.filter(richiesta=caso_in_carico, conclusioni__gt='').exists()


# ── Firma ────────────────────────────────────────────────────────────────────

def test_firma_bloccata_con_conclusioni_vuote(refertatore_loggato, caso_in_carico, pdf_finto):
    _salva(refertatore_loggato, caso_in_carico, conclusioni='   ')
    risp = refertatore_loggato.post(reverse('referti:firma', args=[caso_in_carico.pk]), follow=True)
    assert 'Le conclusioni sono vuote' in risp.content.decode()
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.PRESA_IN_CARICO
    assert not VersioneReferto.objects.exists() and not Prestazione.objects.exists()


def test_firma_chiude_registra_e_manda_il_pdf(refertatore_loggato, caso_in_carico, pdf_finto):
    _salva(refertatore_loggato, caso_in_carico)
    risp = refertatore_loggato.post(reverse('referti:firma', args=[caso_in_carico.pk]))
    assert risp.status_code == 302
    caso_in_carico.refresh_from_db()
    assert caso_in_carico.stato == StatoRichiesta.REFERTATA
    referto = caso_in_carico.referto
    v1 = referto.versioni.get()
    assert v1.numero == 1 and v1.conclusioni == 'ECG nella norma.' and v1.pdf and referto.pdf.name == v1.pdf.name
    assert Prestazione.objects.filter(richiesta=caso_in_carico).count() == 1
    azioni = list(caso_in_carico.audit.values_list('azione', flat=True))
    assert azioni[-3:] == ['REFERTATA', 'REFERTO_FIRMATO', 'PRESTAZIONE_REGISTRATA']
    # Email al richiedente con il PDF allegato, registrata.
    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert email.to == ['vet@x.it'] and 'Referto pronto' in email.subject
    assert email.attachments == [(f'{caso_in_carico.codice}_v1.pdf', PDF_FINTO, 'application/pdf')]
    assert f'/consulti/{caso_in_carico.pk}/' in email.body
    invio = InvioEmail.objects.get(tipo=TipoInvio.REFERTO_PRONTO)
    assert invio.esito == 'OK' and invio.allegati == f'{caso_in_carico.codice}_v1.pdf'
    # Una seconda firma non duplica niente.
    refertatore_loggato.post(reverse('referti:firma', args=[caso_in_carico.pk]))
    assert Prestazione.objects.count() == 1 and VersioneReferto.objects.count() == 1 and len(mail.outbox) == 1


def test_firma_vera_con_weasyprint(refertatore_loggato, caso_in_carico, weasyprint_vero):
    """Il PDF generato davvero (salta con un messaggio chiaro senza le librerie)."""
    _salva(refertatore_loggato, caso_in_carico)
    refertatore_loggato.post(reverse('referti:firma', args=[caso_in_carico.pk]))
    v1 = VersioneReferto.objects.get()
    contenuto = v1.pdf.read()
    assert contenuto.startswith(b'%PDF') and len(contenuto) > 2000
    nome, allegato, mime = mail.outbox[0].attachments[0]
    assert mime == 'application/pdf' and allegato == contenuto


# ── Rettifica e storico ──────────────────────────────────────────────────────

def test_rettifica_versione_nuova_senza_prestazione_nuova(refertatore_loggato, firmato):
    v1 = VersioneReferto.objects.get()
    pdf_v1 = v1.pdf.name
    pagina = refertatore_loggato.get(reverse('referti:refertazione', args=[firmato.pk])).content.decode()
    assert 'Prepara una rettifica' in pagina and 'Motivo della rettifica' in pagina
    _salva(refertatore_loggato, firmato, conclusioni='ECG nella norma. Rivisto: BAV di I grado.',
           motivo_rettifica='Sfuggito il PR lungo.')
    # Salvare la bozza di rettifica non tocca la versione firmata.
    assert VersioneReferto.objects.count() == 1
    risp = refertatore_loggato.post(reverse('referti:rettifica', args=[firmato.pk]))
    assert risp.status_code == 302
    referto = Referto.objects.get(richiesta=firmato)
    assert referto.versione == 2 and referto.motivo_rettifica == ''
    v2 = referto.versioni.get(numero=2)
    assert v2.motivo_rettifica == 'Sfuggito il PR lungo.' and 'BAV' in v2.conclusioni and v2.pdf
    assert referto.pdf.name == v2.pdf.name
    # La versione 1 e' intatta, con il suo PDF.
    v1.refresh_from_db()
    assert v1.conclusioni == 'ECG nella norma.' and v1.pdf.name == pdf_v1 and v1.pdf.name != v2.pdf.name
    assert Prestazione.objects.filter(richiesta=firmato).count() == 1
    evento = firmato.audit.get(azione='REFERTO_RETTIFICATO')
    assert evento.dettaglio['versione'] == 2 and evento.dettaglio['motivo'] == 'Sfuggito il PR lungo.'
    assert len(mail.outbox) == 1 and 'rettificato' in mail.outbox[0].subject
    assert 'Sfuggito il PR lungo.' in mail.outbox[0].body
    assert mail.outbox[0].attachments[0][0] == f'{firmato.codice}_v2.pdf'
    assert InvioEmail.objects.filter(tipo=TipoInvio.REFERTO_RETTIFICATO, esito='OK').count() == 1


def test_rettifica_vuole_motivo_e_un_testo_diverso(refertatore_loggato, firmato):
    _salva(refertatore_loggato, firmato, conclusioni='Altro testo.', motivo_rettifica='')
    refertatore_loggato.post(reverse('referti:rettifica', args=[firmato.pk]))
    assert VersioneReferto.objects.count() == 1
    _salva(refertatore_loggato, firmato, motivo_rettifica='Nessun cambiamento')  # TESTI = quelli firmati
    risp = refertatore_loggato.post(reverse('referti:rettifica', args=[firmato.pk]), follow=True)
    assert 'identico' in risp.content.decode()
    assert VersioneReferto.objects.count() == 1 and not mail.outbox


def test_versione_firmata_non_si_riscrive(firmato):
    v1 = VersioneReferto.objects.get()
    v1.conclusioni = 'riscritta'
    with pytest.raises(ValueError):
        v1.save()


# ── Lato richiedente ─────────────────────────────────────────────────────────

def test_il_richiedente_vede_solo_le_versioni_firmate(client, refertatore_loggato, firmato, mondo, settings):
    settings.DEBUG = True  # consegna da Django (FileResponse), non X-Accel: si legge il contenuto
    _salva(refertatore_loggato, firmato, conclusioni='BOZZA SEGRETA DI RETTIFICA', motivo_rettifica='x')
    client.force_login(mondo.richiedente.user)
    pagina = client.get(reverse('consulti:dettaglio', args=[firmato.pk])).content.decode()
    assert 'ECG nella norma.' in pagina and 'BOZZA SEGRETA' not in pagina
    assert 'Rischio anestesiologico' in pagina and 'Basso' in pagina
    assert 'ha firmato il referto (versione 1)' in pagina                      # racconto dell'audit
    assert 'Scarica il PDF' in pagina
    # Il PDF firmato si scarica; la bozza (anteprima) no.
    referto = firmato.referto
    risp = client.get(reverse('referti:stampa', args=[referto.pk]))
    assert risp.status_code == 200 and b''.join(risp.streaming_content) == PDF_FINTO
    assert client.get(reverse('referti:anteprima', args=[firmato.pk])).status_code == 404


def test_il_richiedente_scarica_anche_le_versioni_precedenti(client, refertatore_loggato, firmato, mondo):
    _salva(refertatore_loggato, firmato, conclusioni='Nuove conclusioni.', motivo_rettifica='Correzione.')
    refertatore_loggato.post(reverse('referti:rettifica', args=[firmato.pk]))
    v1, v2 = VersioneReferto.objects.order_by('numero')
    client.force_login(mondo.richiedente.user)
    pagina = client.get(reverse('consulti:dettaglio', args=[firmato.pk])).content.decode()
    assert 'Nuove conclusioni.' in pagina and 'Versioni precedenti' in pagina and 'Correzione.' in pagina
    for v in (v1, v2):
        url = reverse('referti:stampa_versione', args=[v.pk])
        assert url in pagina
        risp = client.get(url)
        assert risp.status_code == 200 and f'{firmato.codice}_v{v.numero}.pdf' in risp['Content-Disposition']
    client.force_login(mondo.estraneo)
    assert client.get(reverse('referti:stampa_versione', args=[v1.pk])).status_code == 404


def test_richiedente_non_scarica_una_bozza(client, refertatore_loggato, caso_in_carico, mondo):
    _salva(refertatore_loggato, caso_in_carico)
    client.force_login(mondo.richiedente.user)
    referto = Referto.objects.get(richiesta=caso_in_carico)
    assert client.get(reverse('referti:stampa', args=[referto.pk])).status_code == 404


# ── PDF ──────────────────────────────────────────────────────────────────────

class _Profondita(HTMLParser):
    """Registra se <h2>Paziente</h2> sta dentro div.testata."""

    def __init__(self):
        super().__init__()
        self.pila, self.paziente_in_testata = [], None

    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            self.pila.append(dict(attrs).get('class', ''))
        self._h2 = tag == 'h2'

    def handle_endtag(self, tag):
        if tag == 'div' and self.pila:
            self.pila.pop()

    def handle_data(self, data):
        if getattr(self, '_h2', False) and data.strip() == 'Paziente':
            self.paziente_in_testata = 'testata' in self.pila
            self._h2 = False


def test_pdf_testata_chiusa_e_classificazione_leggibile(firmato):
    """Bug corretto: il div.testata del PDF non era chiuso e tutto il referto
    finiva dentro la testata (flex). E la classificazione usciva come chiave
    JSON grezza invece che con l'etichetta."""
    from referti.pdf import html_referto
    referto = firmato.referto
    html = html_referto(referto, referto.ultima_versione)
    p = _Profondita()
    p.feed(html)
    assert p.paziente_in_testata is False
    assert 'Rischio anestesiologico' in html and '>Basso<' in html and 'rischio_anestesia' not in html
    assert 'BOZZA' not in html and 'versione 1' in html
    assert 'BOZZA NON FIRMATA' in html_referto(referto)       # anteprima della copia di lavoro
