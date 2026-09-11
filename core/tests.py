"""Test di seed_demo (casi dimostrativi inviabili, idempotenza), dei file
finti di core/demo.py e del criterio di «fatto» di F3 nel backlog:
`lmonti` referta un'eco di `gbianchi` e la mail parte con il PDF."""

from io import StringIO

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.urls import reverse

from consulti.models import Richiesta, StatoRichiesta
from core import demo
from core.tipi import TipoEsame


def _seed(settings):
    settings.DEBUG = True
    out = StringIO()
    call_command('seed_demo', stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_seed_demo_crea_casi_inviabili_e_non_duplica(settings):
    from eco.models import ProiezioneCatalogo
    out = _seed(settings)
    ecg = Richiesta.objects.get(tipo_esame=TipoEsame.ECG)
    eco = Richiesta.objects.get(tipo_esame=TipoEsame.ECO)
    assert ecg.stato == eco.stato == StatoRichiesta.INVIATA
    assert ecg.richiedente.user.username == eco.richiedente.user.username == 'gbianchi'
    assert ecg.refertatore.user.username == 'rferrari' and eco.refertatore.user.username == 'lmonti'
    # L'eco e' passata da perche_non_puoi_inviare: referto dell'ecografo e ogni proiezione obbligatoria.
    obbligatorie = set(ProiezioneCatalogo.objects.filter(obbligatoria=True, attiva=True).values_list('id', flat=True))
    assert obbligatorie and obbligatorie <= set(eco.proiezioni.values_list('proiezione_id', flat=True))
    assert eco.allegati.filter(categoria='ECO_REFERTO_PDF').exists()
    assert ecg.allegati.get().file.read().startswith(b'%PDF')
    assert ecg.codice in out and eco.codice in out
    # Rilanciato: nessun duplicato.
    _seed(settings)
    assert Richiesta.objects.count() == 2
    # Refertato quello ECG, un nuovo giro ne prepara un altro.
    Richiesta.objects.filter(pk=ecg.pk).update(stato=StatoRichiesta.REFERTATA)
    _seed(settings)
    assert Richiesta.objects.filter(tipo_esame=TipoEsame.ECG).count() == 2
    assert Richiesta.objects.filter(tipo_esame=TipoEsame.ECO).count() == 1


@pytest.mark.django_db
def test_seed_demo_rifiuta_senza_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command('seed_demo', stdout=StringIO())


def test_file_dimostrativi_validi():
    from PIL import Image
    import io
    for contenuto in (demo.pdf_ecg_dimostrativo(), demo.pdf_referto_ecografo_dimostrativo()):
        assert contenuto.startswith(b'%PDF-1.4') and contenuto.rstrip().endswith(b'%%EOF')
        assert b'(DIMOSTRATIVO) Tj' in contenuto
        # La tabella xref punta davvero all'inizio degli oggetti.
        inizio = int(contenuto.rsplit(b'startxref', 1)[1].split()[0])
        assert contenuto[inizio:inizio + 4] == b'xref'
    png = demo.png_proiezione_dimostrativa('Parasternale destra')
    assert Image.open(io.BytesIO(png)).size == (800, 600)


@pytest.mark.django_db
def test_criterio_di_fatto_f3(client, settings, pdf_finto):
    """lmonti prende in carico l'eco di gbianchi, scrive, firma; parte la mail
    «referto pronto» con il PDF; gbianchi vede il referto e scarica il PDF;
    poi una rettifica."""
    from referti.models import VersioneReferto
    from registro.models import Prestazione
    _seed(settings)
    eco = Richiesta.objects.get(tipo_esame=TipoEsame.ECO)
    from django.contrib.auth.models import User
    lmonti, gbianchi = User.objects.get(username='lmonti'), User.objects.get(username='gbianchi')

    client.force_login(lmonti)
    assert 'Casi ricevuti (1)' in client.get(reverse('consulti:casi_ricevuti')).content.decode()
    client.post(reverse('consulti:prendi_in_carico', args=[eco.pk]))
    client.post(reverse('referti:salva_bozza', args=[eco.pk]), {
        'descrizione': 'Ventricolo sinistro non dilatato, pareti nei limiti.',
        'conclusioni': 'Esame ecocardiografico nei limiti per specie ed eta\'.', 'raccomandazioni': ''})
    client.post(reverse('referti:firma', args=[eco.pk]))
    eco.refresh_from_db()
    assert eco.stato == StatoRichiesta.REFERTATA
    assert Prestazione.objects.filter(richiesta=eco).count() == 1
    pronto = mail.outbox[-1]
    assert pronto.to == ['gbianchi@esempio.it'] and pronto.attachments[0][0] == f'{eco.codice}_v1.pdf'

    client.force_login(gbianchi)
    pagina = client.get(reverse('consulti:dettaglio', args=[eco.pk])).content.decode()
    assert 'nei limiti per specie' in pagina and 'Scarica il PDF' in pagina
    v1 = VersioneReferto.objects.get(referto__richiesta=eco)
    assert client.get(reverse('referti:stampa_versione', args=[v1.pk])).status_code == 200

    client.force_login(lmonti)
    client.post(reverse('referti:salva_bozza', args=[eco.pk]), {
        'descrizione': 'Ventricolo sinistro non dilatato, pareti nei limiti.',
        'conclusioni': 'Esame nei limiti. Lieve rigurgito mitralico fisiologico.', 'raccomandazioni': '',
        'motivo_rettifica': 'Aggiunto il rigurgito mitralico.'})
    client.post(reverse('referti:rettifica', args=[eco.pk]))
    assert VersioneReferto.objects.filter(referto__richiesta=eco).count() == 2
    assert Prestazione.objects.filter(richiesta=eco).count() == 1
    assert 'rettificato' in mail.outbox[-1].subject and mail.outbox[-1].to == ['gbianchi@esempio.it']
