"""Listino e prestazioni visti dalla Gestione.

Il listino si legge com'e' oggi e si cambia da una data (listino/cambi.py):
mai una modifica sul posto. Le prestazioni sono fatti immutabili
(registro/models.py): qui cambia solo lo stato della fatturazione.
"""

import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.tipi import TipoEsame
from listino.cambi import CambioNonValido, cambia_prezzo, cambia_supplemento
from listino.models import Supplemento, VoceListino
from registro.esporta import del_mese, scrivi_csv
from registro.models import Prestazione, StatoFatturazione, StatoFatturazioneScelte

from .accesso import solo_gestione

MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre',
        'ottobre', 'novembre', 'dicembre']


def _decimale(testo):
    try:
        valore = Decimal((testo or '').replace(',', '.').strip())
    except InvalidOperation:
        return None
    return valore if valore >= 0 else None


def _data(testo):
    try:
        return date.fromisoformat(testo or '')
    except ValueError:
        return None


# ── Listino ──────────────────────────────────────────────────────────────────

@solo_gestione
def listino(request):
    oggi = timezone.localdate()
    tipi = []
    for valore, etichetta in TipoEsame.choices:
        voci = list(VoceListino.objects.filter(tipo_esame=valore).order_by('-valido_dal'))
        in_vigore = next((v for v in voci if v.in_vigore(oggi)), None)
        futuri = [v for v in voci if v.valido_dal > oggi]
        tipi.append({'valore': valore, 'etichetta': etichetta, 'in_vigore': in_vigore, 'futuri': futuri,
                     'storico': [v for v in voci if v is not in_vigore and v not in futuri]})
    supplementi = list(Supplemento.objects.order_by('tipo', '-valido_dal'))
    return render(request, 'gestione/listino.html', {
        'sezione': 'listino', 'tipi': tipi, 'oggi': oggi,
        'supplementi_in_vigore': [s for s in supplementi if s.in_vigore(oggi)],
        'supplementi_futuri': [s for s in supplementi if s.valido_dal > oggi],
    })


@solo_gestione
@require_POST
def listino_cambia(request, tipo):
    if tipo not in TipoEsame.values:
        return redirect('gestione:listino')
    prezzo, aliquota, dal = _decimale(request.POST.get('prezzo')), _decimale(request.POST.get('aliquota')), \
        _data(request.POST.get('dal'))
    if prezzo is None or aliquota is None or dal is None:
        messages.error(request, 'Prezzo, IVA e data devono essere compilati (es. 45,00 · 22 · una data).')
        return redirect('gestione:listino')
    try:
        voce = cambia_prezzo(tipo, prezzo, aliquota, dal)
    except CambioNonValido as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f'{voce.get_tipo_esame_display()}: € {voce.prezzo} dal '
                                  f'{voce.valido_dal:%d/%m/%Y}.')
    return redirect('gestione:listino')


@solo_gestione
@require_POST
def supplemento_cambia(request, pk):
    supplemento = get_object_or_404(Supplemento, pk=pk)
    dal = _data(request.POST.get('dal'))
    valore = _decimale(request.POST.get('valore'))
    if dal is None or valore is None:
        messages.error(request, 'Valore e data devono essere compilati.')
        return redirect('gestione:listino')
    in_percentuale = supplemento.percentuale is not None
    try:
        nuovo = cambia_supplemento(supplemento, dal, importo=None if in_percentuale else valore,
                                   percentuale=valore if in_percentuale else None)
    except CambioNonValido as e:
        messages.error(request, str(e))
    else:
        quanto = f'{nuovo.percentuale}%' if in_percentuale else f'€ {nuovo.importo}'
        messages.success(request, f'{nuovo.descrizione}: {quanto} dal {nuovo.valido_dal:%d/%m/%Y}.')
    return redirect('gestione:listino')


# ── Prestazioni ──────────────────────────────────────────────────────────────

def _mese_richiesto(request):
    oggi = timezone.localdate()
    try:
        anno, mese = (int(x) for x in request.GET.get('mese', '').split('-'))
        date(anno, mese, 1)
    except (ValueError, TypeError):
        anno, mese = oggi.year, oggi.month
    return anno, mese


def _spostato(anno, mese, passi):
    indice = anno * 12 + (mese - 1) + passi
    return indice // 12, indice % 12 + 1


@solo_gestione
def prestazioni(request):
    anno, mese = _mese_richiesto(request)
    if request.GET.get('csv'):
        buffer = io.StringIO()
        scrivi_csv(del_mese(anno, mese), buffer)
        risposta = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
        risposta['Content-Disposition'] = f'attachment; filename="prestazioni_{anno}-{mese:02d}.csv"'
        return risposta
    righe = list(del_mese(anno, mese))
    stato = request.GET.get('stato', '')
    if stato:
        righe = [p for p in righe if getattr(getattr(p, 'fatturazione', None), 'stato', '') == stato]
    totali = (Prestazione.objects.filter(data__year=anno, data__month=mese)
              .exclude(fatturazione__stato=StatoFatturazioneScelte.STORNATA)
              .values('soggetto_emittente').annotate(totale=Sum('totale'), imponibile=Sum('imponibile'))
              .order_by('soggetto_emittente'))
    prima, dopo = _spostato(anno, mese, -1), _spostato(anno, mese, 1)
    return render(request, 'gestione/prestazioni.html', {
        'sezione': 'prestazioni', 'righe': righe, 'totali': list(totali),
        'titolo_mese': f'{MESI[mese - 1]} {anno}', 'mese': f'{anno}-{mese:02d}',
        'mese_prima': f'{prima[0]}-{prima[1]:02d}', 'mese_dopo': f'{dopo[0]}-{dopo[1]:02d}',
        'stato': stato, 'stati': StatoFatturazioneScelte.choices,
    })


@solo_gestione
@require_POST
def fatturazione_cambia(request, pk):
    """Cambia solo lo stato della fatturazione, mai i numeri della prestazione."""
    prestazione = get_object_or_404(Prestazione, pk=pk)
    fatt, _ = StatoFatturazione.objects.get_or_create(prestazione=prestazione)
    nuovo = request.POST.get('stato')
    if nuovo not in StatoFatturazioneScelte.values:
        messages.error(request, 'Stato non valido.')
    else:
        fatt.stato = nuovo
        fatt.numero_fattura = request.POST.get('numero_fattura', '').strip()[:50]
        fatt.data_fattura = _data(request.POST.get('data_fattura'))
        fatt.save()
        messages.success(request, f'{prestazione.richiesta.codice}: {fatt.get_stato_display().lower()}.')
    # Si torna al mese della prestazione: mai a un indirizzo preso dal form.
    return redirect(f'{reverse("gestione:prestazioni")}?mese={prestazione.data:%Y-%m}')
