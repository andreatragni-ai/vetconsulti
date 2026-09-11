"""La foto dell'esperto (collaudo dell'11/09/2026): si carica dall'admin o
dal profilo, si riduce al salvataggio, compare nella scheda del passo 2
(iniziali se manca) ed e' servita solo a chi e' autenticato."""

import io

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image


def _png(larghezza=1600, altezza=1200):
    uscita = io.BytesIO()
    Image.new('RGB', (larghezza, altezza), (40, 90, 120)).save(uscita, format='PNG')
    return SimpleUploadedFile('ritratto.png', uscita.getvalue(), content_type='image/png')


def test_la_foto_si_riduce_a_un_jpeg_di_480_px(mondo):
    mondo.ref.foto = _png()
    mondo.ref.save()
    mondo.ref.refresh_from_db()
    assert mondo.ref.foto.name.startswith('foto_refertatori/ritratto') and mondo.ref.foto.name.endswith('.jpg')
    with Image.open(mondo.ref.foto.path) as salvata:
        assert salvata.format == 'JPEG' and max(salvata.size) == 480 and salvata.size == (480, 360)


def test_iniziali_e_indirizzo_protetto(mondo):
    assert mondo.ref.iniziali == 'AT' and mondo.ref.url_foto == ''    # Anna Test, senza foto
    mondo.ref.foto = _png(100, 100)
    mondo.ref.save()
    assert mondo.ref.url_foto.startswith(reverse('foto_refertatore', args=[mondo.ref.pk]) + '?v=')
    assert '/media/' not in mondo.ref.url_foto


def test_la_foto_si_vede_solo_da_autenticati(client, mondo):
    mondo.ref.foto = _png(100, 100)
    mondo.ref.save()
    url = reverse('foto_refertatore', args=[mondo.ref.pk])
    assert client.get(url).status_code == 302                          # al login
    client.force_login(mondo.richiedente.user)
    risposta = client.get(url)
    assert risposta.status_code == 200 and risposta['X-Accel-Redirect'].startswith('/_media_interno/foto_refertatori/')
    assert client.get(reverse('foto_refertatore', args=[mondo.ref2.pk])).status_code == 404   # senza foto


def test_scheda_del_passo_2_con_foto_o_iniziali(client, mondo):
    mondo.ref.foto = _png(100, 100)
    mondo.ref.save()
    client.force_login(mondo.richiedente.user)
    schede = client.get(reverse('consulti:esperti'), {'tipo_esame': 'ECG'}).content.decode()
    assert f'<img src="{mondo.ref.url_foto}"' in schede.replace('&amp;', '&')
    assert '<span class="esperto-iniziali" aria-hidden="true">BT</span>' in schede   # Bruno Test, senza foto


def test_la_foto_si_carica_dal_profilo_e_si_toglie(client, mondo):
    client.force_login(mondo.ref.user)
    url = reverse('accounts:profilo_refertatore')
    pagina = client.get(url).content.decode()
    assert 'name="p-foto"' in pagina
    dati = {'p-titolo': 'Dott.', 'k-TOTAL_FORMS': '0', 'k-INITIAL_FORMS': '0'}
    # Il formset delle competenze vuole le sue righe: le prende dalla pagina.
    from accounts.models import CompetenzaRefertatore
    competenze = list(CompetenzaRefertatore.objects.filter(refertatore=mondo.ref).order_by('tipo_esame'))
    dati.update({'k-TOTAL_FORMS': str(len(competenze)), 'k-INITIAL_FORMS': str(len(competenze))})
    for i, c in enumerate(competenze):
        dati.update({f'k-{i}-id': c.pk, f'k-{i}-tipo_esame': c.tipo_esame})
        if c.referente:
            dati[f'k-{i}-referente'] = 'on'
    risposta = client.post(url, {**dati, 'p-foto': _png(900, 900)})
    assert risposta.status_code == 302
    mondo.ref.refresh_from_db()
    assert mondo.ref.foto and max(Image.open(mondo.ref.foto.path).size) == 480
    pagina = client.get(url).content.decode().replace('&amp;', '&')
    assert f'src="{mondo.ref.url_foto}"' in pagina and 'Togli la foto' in pagina
    assert '/media/foto_refertatori' not in pagina
    client.post(url, {**dati, 'p-foto-clear': 'on'})
    mondo.ref.refresh_from_db()
    assert not mondo.ref.foto


@pytest.mark.django_db
def test_admin_mostra_la_foto_senza_link_a_media(client, mondo):
    mondo.ref.foto = _png(100, 100)
    mondo.ref.save()
    admin = User.objects.create_superuser('capo', 'capo@x.it', 'pw')
    client.force_login(admin)
    pagina = client.get(reverse('admin:accounts_refertatore_change', args=[mondo.ref.pk])).content.decode()
    assert 'name="foto"' in pagina and mondo.ref.url_foto.split('?')[0] in pagina
    assert '/media/foto_refertatori' not in pagina
