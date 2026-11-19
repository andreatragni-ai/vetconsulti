import pytest
from django.contrib.auth.models import User

from accounts.models import Clinica, Richiedente
from consulti.models import Allegato, CategoriaAllegato, Richiesta, StatoAllegato
from core.tipi import TipoEsame
from django.core.files.uploadedfile import SimpleUploadedFile
from eco import transcodifica


@pytest.mark.django_db
def test_senza_ffmpeg_non_fallisce(settings):
    settings.FFMPEG_BIN = '/nessun/posto/ffmpeg'
    u = User.objects.create_user('v', 'v@x.it', 'pw')
    c = Clinica.objects.create(denominazione='C')
    r = Richiedente.objects.create(user=u, clinica=c)
    ric = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=r, clinica=c)
    a = Allegato.da_upload(ric, SimpleUploadedFile('clip.avi', b'x' * 100, 'video/avi'),
                           CategoriaAllegato.ECO_CLIP, u)
    from unittest import mock
    with mock.patch.object(transcodifica.logger, 'warning') as avviso:
        assert transcodifica.transcodifica(a) is False
    assert 'ffmpeg non trovato' in avviso.call_args[0][0]
    a.refresh_from_db()
    assert a.stato == StatoAllegato.CARICATO


# ── Catalogo: comando carica_catalogo_eco ────────────────────────────────────

@pytest.mark.django_db
def test_carica_catalogo_eco_dal_repo_e_idempotente():
    """Il catalogo di Andre in eco/catalogo/: 27 righe (25 obbligatorie, 2
    filmati liberi), 62 immagini di riferimento collegate. Rilanciato non
    duplica nulla e sostituisce le immagini."""
    import json
    from io import StringIO
    from django.core.management import call_command
    from eco.management.commands.carica_catalogo_eco import CATALOGO_PREDEFINITO
    from eco.models import ImmagineRiferimento, ProiezioneCatalogo

    righe = json.loads(CATALOGO_PREDEFINITO.read_text(encoding='utf-8'))['righe']
    collegamenti = sum(len(r.get('immagini_riferimento') or []) for r in righe)
    ProiezioneCatalogo.objects.create(codice='VECCHIA', nome='Voce della bozza', obbligatoria=True)
    out = StringIO()
    call_command('carica_catalogo_eco', stdout=out)
    assert ProiezioneCatalogo.objects.filter(attiva=True).count() == len(righe) == 27
    # Tre dal 15/11/2026 (erano 25): le altre restano nel catalogo, facoltative.
    assert ProiezioneCatalogo.objects.filter(attiva=True, obbligatoria=True).count() == 3
    assert list(ProiezioneCatalogo.objects.filter(libera=True).values_list('codice', flat=True)) == [
        'LIBERO_1', 'LIBERO_2']
    # 74 dall'11/09 sera: sottoxifoidea, misura LAD, vasi polmonari in M-mode e
    # polmonare da sinistra hanno avuto le loro immagini (tutte le obbligatorie ne hanno).
    assert ImmagineRiferimento.objects.count() == collegamenti == 73
    assert not ProiezioneCatalogo.objects.filter(
        attiva=True, libera=False, immagini__isnull=True).exists()
    # La voce che nel file non c'e' piu' si disattiva, non si cancella.
    assert not ProiezioneCatalogo.objects.get(codice='VECCHIA').attiva
    assert 'Disattivate' in out.getvalue() and 'VECCHIA' in out.getvalue()
    dx1 = ProiezioneCatalogo.objects.get(codice='DX1_B')
    assert [i.didascalia for i in dx1.immagini.all()] == ['Immagine ecografica', 'Posizione della sonda', 'Schema']
    assert dx1.istruzioni and dx1.deve_essere_visibile and dx1.serve_per
    sub = ProiezioneCatalogo.objects.get(codice='SUB_B')
    assert [i.didascalia for i in sub.immagini.all()] == [
        'Scansione sottoxifoidea', 'Posizione della sonda: dietro lo sterno']
    call_command('carica_catalogo_eco', stdout=StringIO())
    assert ProiezioneCatalogo.objects.count() == 28 and ImmagineRiferimento.objects.count() == 73


@pytest.mark.django_db
def test_carica_catalogo_eco_rifiuta_un_file_sbagliato(tmp_path):
    import json
    from django.core.management import CommandError, call_command
    from eco.models import ProiezioneCatalogo
    file = tmp_path / 'catalogo.json'
    file.write_text(json.dumps({'righe': [
        {'codice': 'A', 'nome': 'A', 'finestra': 'NESSUNA', 'tipo_media': 'CLIP'},
        {'codice': 'B', 'nome': 'B', 'finestra': 'ALTRO', 'tipo_media': 'CLIP', 'libera': True, 'obbligatoria': True},
        {'codice': 'C', 'nome': 'C', 'finestra': 'ALTRO', 'tipo_media': 'CLIP', 'immagini_riferimento': ['no.jpg']},
    ]}))
    with pytest.raises(CommandError) as errore:
        call_command('carica_catalogo_eco', str(file))
    messaggio = str(errore.value)
    assert 'finestra sconosciuta' in messaggio and 'non puo\' essere obbligatorio' in messaggio
    assert 'no.jpg non trovata' in messaggio
    assert not ProiezioneCatalogo.objects.exists()


@pytest.mark.django_db
def test_carica_catalogo_eco_accetta_una_didascalia_esplicita(tmp_path):
    """Una voce puo' essere {"file", "didascalia"}: serve a citare la fonte di
    una figura presa da un articolo. La forma con il solo nome resta valida."""
    import json
    from PIL import Image
    from django.core.management import call_command
    from eco.models import ProiezioneCatalogo
    cartella = tmp_path / 'img'; cartella.mkdir()
    for nome in ('fig_mmode.jpg', 'fig_schema.jpg'):
        Image.new('RGB', (8, 8)).save(cartella / nome)
    file = tmp_path / 'catalogo.json'
    file.write_text(json.dumps({'righe': [{
        'codice': 'PVPA', 'nome': 'Vasi polmonari', 'finestra': 'PARASTERNALE_DESTRA', 'tipo_media': 'STATICA',
        'immagini_riferimento': [{'file': 'fig_mmode.jpg', 'didascalia': 'Birettoni et al., JVC 2016'}, 'fig_schema.jpg'],
    }]}))
    call_command('carica_catalogo_eco', str(file), '--immagini', str(cartella))
    immagini = list(ProiezioneCatalogo.objects.get(codice='PVPA').immagini.order_by('ordine'))
    assert [i.didascalia for i in immagini] == ['Birettoni et al., JVC 2016', 'Schema']


def _righe_catalogo():
    import json
    from eco.management.commands.carica_catalogo_eco import CATALOGO_PREDEFINITO
    with open(CATALOGO_PREDEFINITO, encoding='utf-8') as f:
        return json.load(f)['righe']


def test_i_filmati_del_catalogo_chiedono_cicli_e_un_massimo():
    """Quanto deve durare una clip si dice con le stesse parole ovunque, e le
    parole vengono dai due numeri di settings (17/11/2026: quattro cicli
    cardiaci interi, non piu' di cinque secondi). Se un giorno i numeri
    cambiano, questo test fa cadere anche il catalogo, che va riscritto:
    e' il punto, perche' le istruzioni le legge chi acquisisce."""
    from django.conf import settings as cfg
    attesa = (f'Filmato di almeno {cfg.ECO_CLIP_CICLI_MINIMI} cicli cardiaci interi, '
              f"non piu' di {cfg.ECO_CLIP_SECONDI_MAX} secondi.")
    filmati = [r for r in _righe_catalogo() if r['tipo_media'] == 'CLIP']
    assert len(filmati) == 14
    assert all(r['istruzioni'].startswith(attesa) for r in filmati)
    assert not any('circa' in r['istruzioni'] or 'decina' in r['istruzioni'] for r in _righe_catalogo())


def test_le_zone_e_il_catalogo_dicono_la_stessa_regola():
    from consulti.regole import frase_durata_clip
    from consulti.views_percorso import TESTI_ZONA
    frase = frase_durata_clip()
    assert 'cicli cardiaci interi' in frase and 'secondi' in frase
    assert frase in TESTI_ZONA['CLIP'][2] and frase in TESTI_ZONA['ENTRAMBI'][2]
    assert not any('circa' in t for testi in TESTI_ZONA.values() for t in testi)


def test_il_catalogo_chiede_tre_filmati(settings):
    """La decisione del 15/11/2026: obbligatori il referto dell'ecografo e
    TRE clip B-mode. Le altre 22 proiezioni restano nel catalogo, ma
    facoltative. Se un giorno si cambia idea, si cambia qui e nel JSON."""
    righe = _righe_catalogo()
    obbligatorie = [r for r in righe if r.get('obbligatoria')]
    assert [r['codice'] for r in obbligatorie] == ['DX1_B', 'DX3_B', 'SX1_B']
    assert all(r['tipo_media'] == 'CLIP' for r in obbligatorie)
    assert len([r for r in righe if not r.get('obbligatoria') and not r.get('libera')]) == 22
    # Nessuna delle tre e' un filmato libero, e l'ordine e' quello dell'esame.
    assert [r['ordine'] for r in obbligatorie] == sorted(r['ordine'] for r in obbligatorie)


# ── Durata e codec: cosa arriva dall'ecografo (17/11/2026) ──────────────────

def test_sonda_senza_ffprobe_non_rompe_niente(settings):
    """Sul Mac di sviluppo ffprobe non c'e': `sonda` torna None e chi la
    chiama tira dritto, come fa gia' la transcodifica."""
    from eco import transcodifica
    settings.FFMPEG_BIN = '/nessun/posto/ffmpeg'
    assert transcodifica.ffprobe_disponibile() is None
    assert transcodifica.sonda('/qualsiasi/file.avi') is None


@pytest.mark.django_db
def test_misura_scrive_durata_e_codec(mondo, tmp_path, monkeypatch):
    """Quello che ffprobe trova finisce sull'allegato: la durata serve
    all'avviso, il codec a sapere cosa mandano gli ecografi (del Mindray
    sappiamo, di Esaote no)."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from consulti.models import Allegato, CategoriaAllegato, Richiesta
    from core.tipi import TipoEsame
    from eco import transcodifica

    caso = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=mondo.richiedente,
                                    clinica=mondo.clinica, refertatore=mondo.ref)
    allegato = Allegato.da_upload(caso, SimpleUploadedFile('c.avi', b'finta', 'video/x-msvideo'),
                                  CategoriaAllegato.ECO_CLIP, mondo.richiedente.user)
    monkeypatch.setattr(transcodifica, 'sonda', lambda percorso: {
        'codec': 'msmpeg4v3', 'durata_s': 7.5, 'larghezza': 1260, 'altezza': 910, 'fps': 30.0})
    assert transcodifica.misura(allegato)['codec'] == 'msmpeg4v3'
    allegato.refresh_from_db()
    assert allegato.codec == 'msmpeg4v3' and float(allegato.durata_s) == 7.5
    # 7,5 s sono piu' del massimo: la pagina lo dice, nessuno blocca niente.
    assert allegato.durata_oltre_il_massimo
    allegato.durata_s = 1.6
    assert not allegato.durata_oltre_il_massimo


@pytest.mark.django_db
def test_la_durata_non_riguarda_le_immagini(mondo):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from consulti.models import Allegato, CategoriaAllegato, Richiesta
    from core.tipi import TipoEsame
    caso = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=mondo.richiedente,
                                    clinica=mondo.clinica, refertatore=mondo.ref)
    statica = Allegato.da_upload(caso, SimpleUploadedFile('i.png', b'\x89PNG', 'image/png'),
                                 CategoriaAllegato.ECO_STATICA, mondo.richiedente.user)
    statica.durata_s = 99
    assert not statica.durata_oltre_il_massimo


@pytest.mark.django_db
def test_la_transcodifica_cancella_l_originale(mondo, monkeypatch):
    """Convertita la clip, l'AVI di partenza non deve restare orfano sul
    disco (17/11/2026: pesava cinque volte l'MP4 e portava il nome del
    cliente stampato nei fotogrammi). Senza ffmpeg sul Mac si finge: il
    comando «scrive» un MP4 finto dove ffmpeg scriverebbe il suo."""
    import subprocess
    from django.core.files.uploadedfile import SimpleUploadedFile
    from consulti.models import Allegato, CategoriaAllegato, Richiesta, StatoAllegato
    from core.tipi import TipoEsame
    from eco import transcodifica

    caso = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=mondo.richiedente,
                                    clinica=mondo.clinica, refertatore=mondo.ref)
    allegato = Allegato.da_upload(caso, SimpleUploadedFile('c.avi', b'RIFF finto', 'video/x-msvideo'),
                                  CategoriaAllegato.ECO_CLIP, mondo.richiedente.user)
    originale = allegato.file.name
    deposito = allegato.file.storage
    assert deposito.exists(originale)

    def ffmpeg_finto(comando, **kw):
        with open(comando[-1], 'wb') as f:
            f.write(b'\x00\x00\x00\x18ftypmp42 convertito')
        return subprocess.CompletedProcess(comando, 0)

    monkeypatch.setattr(transcodifica, 'ffmpeg_disponibile', lambda: True)
    monkeypatch.setattr(transcodifica.subprocess, 'run', ffmpeg_finto)
    assert transcodifica.transcodifica(allegato)
    allegato.refresh_from_db()
    assert allegato.stato == StatoAllegato.TRANSCODIFICATO and allegato.file.name.endswith('.mp4')
    assert deposito.exists(allegato.file.name)
    assert not deposito.exists(originale)           # l'AVI non c'e' piu'
    assert caso.audit.filter(azione='ALLEGATO_TRANSCODIFICATO').exists()


@pytest.mark.django_db
def test_se_la_transcodifica_fallisce_l_originale_resta(mondo, monkeypatch):
    import subprocess
    from django.core.files.uploadedfile import SimpleUploadedFile
    from consulti.models import Allegato, CategoriaAllegato, Richiesta, StatoAllegato
    from core.tipi import TipoEsame
    from eco import transcodifica

    caso = Richiesta.objects.create(tipo_esame=TipoEsame.ECO, richiedente=mondo.richiedente,
                                    clinica=mondo.clinica, refertatore=mondo.ref)
    allegato = Allegato.da_upload(caso, SimpleUploadedFile('c.avi', b'RIFF finto', 'video/x-msvideo'),
                                  CategoriaAllegato.ECO_CLIP, mondo.richiedente.user)
    originale = allegato.file.name

    def ffmpeg_rotto(comando, **kw):
        raise subprocess.CalledProcessError(1, comando, stderr=b'Unknown codec')

    monkeypatch.setattr(transcodifica, 'ffmpeg_disponibile', lambda: True)
    monkeypatch.setattr(transcodifica.subprocess, 'run', ffmpeg_rotto)
    assert not transcodifica.transcodifica(allegato)
    allegato.refresh_from_db()
    assert allegato.stato == StatoAllegato.CARICATO and allegato.file.name == originale
    assert allegato.file.storage.exists(originale)
    assert caso.audit.filter(azione='ALLEGATO_NON_CONVERTITO').exists()
