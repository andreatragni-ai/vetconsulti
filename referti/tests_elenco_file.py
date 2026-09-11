"""L'elenco dei file nella pagina del refertatore (collaudo dell'11/09/2026):
nell'ordine del catalogo, non in quello di caricamento. Eco: referto
dell'ecografo in testa, poi un gruppo per finestra con prima i filmati e poi
le immagini, filmati liberi in fondo; ECG e Holter in ordine logico, senza
gruppi. Miniatura per le immagini, icona per filmati e PDF."""

import html
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import CompetenzaRefertatore
from consulti.elenco_file import gruppi_file, voci_in_ordine
from consulti.models import Allegato, CategoriaAllegato, Paziente, Richiesta
from core.tipi import TipoEsame
from eco.models import Finestra, ProiezioneCaricata, ProiezioneCatalogo, TipoMedia

PDF = b'%PDF-1.4 prova\n%%EOF\n'
PNG = b'\x89PNG\r\n\x1a\n finta'
MP4 = b'\x00\x00\x00\x18ftypmp42 finto'


def _allega(richiesta, nome, categoria, contenuto, mime, proiezione=None, nota=''):
    a = Allegato.da_upload(richiesta, SimpleUploadedFile(nome, contenuto, mime), categoria)
    if proiezione is not None:
        ProiezioneCaricata.objects.create(richiesta=richiesta, proiezione=proiezione, allegato=a, nota=nota)
    return a


@pytest.fixture
def eco_inviata(mondo):
    """Un'eco inviata a `ref` con i file caricati apposta in disordine."""
    CompetenzaRefertatore.objects.create(refertatore=mondo.ref, tipo_esame=TipoEsame.ECO, referente=True)
    crea = ProiezioneCatalogo.objects.create
    p = {
        'ps_clip': crea(codice='SX1_B', nome='Apicale 4 camere', finestra=Finestra.PARASTERNALE_SINISTRA,
                        tipo_media=TipoMedia.CLIP, obbligatoria=True, ordine=1),
        'pd_img': crea(codice='DX5', nome='LA/Ao', finestra=Finestra.PARASTERNALE_DESTRA,
                       tipo_media=TipoMedia.STATICA, obbligatoria=True, ordine=2),
        'pd_clip2': crea(codice='DX1_C', nome='4 camere color', finestra=Finestra.PARASTERNALE_DESTRA,
                         tipo_media=TipoMedia.CLIP, obbligatoria=True, ordine=20),
        'pd_clip1': crea(codice='DX1_B', nome='4 camere B-mode', finestra=Finestra.PARASTERNALE_DESTRA,
                         tipo_media=TipoMedia.CLIP, obbligatoria=True, ordine=10),
        'sub_img': crea(codice='SUB_PW', nome='LVOT pulsato', finestra=Finestra.SOTTOXIFOIDEA,
                        tipo_media=TipoMedia.STATICA, obbligatoria=True, ordine=5),
        'ps_img': crea(codice='D1_PW', nome='Transmitralico pulsato', finestra=Finestra.PARASTERNALE_SINISTRA,
                       tipo_media=TipoMedia.STATICA, obbligatoria=True, ordine=0),
        'libero': crea(codice='LIBERO_1', nome='Filmato libero 1', tipo_media=TipoMedia.CLIP, libera=True),
    }
    r = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=mondo.richiedente, clinica=mondo.clinica,
                                 refertatore=mondo.ref, quesito='Soffio?')
    Paziente.objects.create(richiesta=r, nome='Luna', specie='GATTO')
    # In disordine: il libero, un'immagine sinistra, una destra, il referto a meta', ...
    _allega(r, 'libero.mp4', CategoriaAllegato.ECO_CLIP, MP4, 'video/mp4', p['libero'], nota='jet?')
    _allega(r, 'ps_img.png', CategoriaAllegato.ECO_STATICA, PNG, 'image/png', p['ps_img'])
    _allega(r, 'pd_img.png', CategoriaAllegato.ECO_STATICA, PNG, 'image/png', p['pd_img'])
    _allega(r, 'referto.pdf', CategoriaAllegato.ECO_REFERTO_PDF, PDF, 'application/pdf')
    _allega(r, 'pd_clip2.mp4', CategoriaAllegato.ECO_CLIP, MP4, 'video/mp4', p['pd_clip2'])
    _allega(r, 'ps_clip.mp4', CategoriaAllegato.ECO_CLIP, MP4, 'video/mp4', p['ps_clip'])
    _allega(r, 'sub_img.png', CategoriaAllegato.ECO_STATICA, PNG, 'image/png', p['sub_img'])
    _allega(r, 'pd_clip1.mp4', CategoriaAllegato.ECO_CLIP, MP4, 'video/mp4', p['pd_clip1'])
    _allega(r, 'vecchio.txt', CategoriaAllegato.ALTRO, b'x', 'text/plain')
    r.stato, r.inviata_il = 'INVIATA', r.creata_il
    r.save()
    return r


def test_eco_referto_in_testa_poi_finestre_filmati_prima_liberi_in_fondo(eco_inviata):
    gruppi = gruppi_file(eco_inviata)
    assert [g['etichetta'] for g in gruppi] == [
        'Referto dell\'ecografo', 'Parasternale destra', 'Sottoxifoidea',
        'Parasternale sinistra, apicale e craniale', 'Filmati liberi', 'Altri file']
    assert [v['allegato'].nome_originale for v in voci_in_ordine(eco_inviata)] == [
        'referto.pdf',
        'pd_clip1.mp4', 'pd_clip2.mp4', 'pd_img.png',     # destra: filmati (ordine del catalogo), poi immagini
        'sub_img.png',
        'ps_clip.mp4', 'ps_img.png',                      # sinistra: il filmato prima anche se ha ordine piu' alto
        'libero.mp4',
        'vecchio.txt']


def test_miniature_per_le_immagini_icone_per_filmati_e_pdf(eco_inviata):
    voci = {v['allegato'].nome_originale: v for v in voci_in_ordine(eco_inviata)}
    immagine = voci['pd_img.png']
    assert immagine['miniatura'] == reverse('scarica_allegato', args=[immagine['allegato'].pk]) + '?inline=1'
    assert voci['pd_clip1.mp4']['miniatura'] is None and voci['pd_clip1.mp4']['filmato']
    assert voci['referto.pdf']['miniatura'] is None and voci['referto.pdf']['genere'] == 'pdf'
    assert voci['libero.mp4']['nota'] == 'jet?' and voci['pd_img.png']['proiezione'] == 'LA/Ao'


def test_pagina_del_refertatore_nell_ordine_del_catalogo(client, mondo, eco_inviata):
    client.force_login(mondo.ref.user)
    pagina = html.unescape(client.get(reverse('referti:refertazione', args=[eco_inviata.pk])).content.decode())
    elenco = pagina[pagina.index('class="visore-elenco"'):pagina.index('class="visore-scena"')]
    titoli = re.findall(r'class="visore-gruppo"[^>]*>([^<]+)<', elenco)
    assert [t.strip() for t in titoli] == ['Referto dell\'ecografo', 'Parasternale destra', 'Sottoxifoidea',
                                          'Parasternale sinistra, apicale e craniale', 'Filmati liberi', 'Altri file']
    nomi = re.findall(r'<span class="nome">([^<]+)</span>', elenco)
    assert nomi == ['Referto ecografo (PDF)', '4 camere B-mode', '4 camere color', 'LA/Ao', 'LVOT pulsato',
                    'Apicale 4 camere', 'Transmitralico pulsato', 'Filmato libero 1', 'Altro']
    assert elenco.count('<img src=') == 3 and elenco.count('bi-camera-reels') == 4
    assert elenco.count('bi-file-earmark-pdf') == 1
    # Aperto all'arrivo: il referto dell'ecografo, e l'anteprima grande resta.
    referto = eco_inviata.allegati.get(categoria=CategoriaAllegato.ECO_REFERTO_PDF)
    assert re.search(rf'data-visore="vis-{referto.pk}"\s+class="visore-scheda attiva"', elenco)
    assert f'<div id="vis-{referto.pk}" class="w-100 attivo">' in pagina


def test_pagina_del_caso_stesso_ordine(client, mondo, eco_inviata):
    client.force_login(mondo.richiedente.user)
    pagina = html.unescape(client.get(reverse('consulti:dettaglio', args=[eco_inviata.pk])).content.decode())
    posizioni = [pagina.index(n) for n in ('referto.pdf', 'pd_clip1.mp4', 'pd_img.png', 'sub_img.png',
                                           'ps_clip.mp4', 'libero.mp4')]
    assert posizioni == sorted(posizioni) and '<tr class="riga-gruppo"><th colspan="4">Sottoxifoidea' in pagina


def test_ecg_prima_il_pdf_poi_le_foto_senza_gruppi(mondo, caso_inviato):
    foto = _allega(caso_inviato, 'foto.jpg', CategoriaAllegato.ECG_IMMAGINE, PNG, 'image/jpeg')
    Allegato.objects.filter(pk=foto.pk).update(caricato_il=caso_inviato.allegati.get(
        categoria=CategoriaAllegato.ECG_PDF).caricato_il.replace(year=2000))    # la foto e' la prima caricata
    gruppi = gruppi_file(caso_inviato)
    assert len(gruppi) == 1 and gruppi[0]['etichetta'] == ''
    assert [v['allegato'].categoria for v in gruppi[0]['voci']] == ['ECG_PDF', 'ECG_IMMAGINE']


def test_holter_prima_il_referto_poi_il_file_dell_apparecchio(mondo):
    CompetenzaRefertatore.objects.filter(refertatore=mondo.ref).update(tipo_esame=TipoEsame.HOLTER)
    r = Richiesta.objects.create(tipo_esame=TipoEsame.HOLTER, richiedente=mondo.richiedente, clinica=mondo.clinica,
                                 refertatore=mondo.ref)
    _allega(r, 'registrazione.hlt', CategoriaAllegato.HOLTER_FILE, b'HOLTER', 'application/octet-stream')
    _allega(r, 'referto.pdf', CategoriaAllegato.HOLTER_REFERTO, PDF, 'application/pdf')
    assert [v['allegato'].nome_originale for v in voci_in_ordine(r)] == ['referto.pdf', 'registrazione.hlt']


def test_gli_scartati_non_ci_sono(eco_inviata):
    Allegato.objects.filter(nome_originale='vecchio.txt').update(stato='SCARTATO')
    assert 'Altri file' not in [g['etichetta'] for g in gruppi_file(eco_inviata)]
