"""
La Gestione: le pagine dello staff dentro il portale, al posto dell'admin
di Django per il lavoro di tutti i giorni (decisione di Andre, 13/09/2026:
l'admin di Django era confuso e pieno di nozioni inutili).

Cosa fa lo staff qui e non altrove:
- vede tutti i casi inviati e interviene nelle emergenze (affidare un caso a
  un altro esperto, annullarlo): sempre con un motivo, con le transizioni
  del modello e quindi con l'audit (consulti.models.Richiesta);
- approva le iscrizioni, gestisce i refertatori, il listino e le prestazioni.

L'admin di Django resta per le riparazioni, fuori dalla barra.
"""

import logging

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Clinica, Refertatore, Richiedente, TipoRichiedente
from consulti.models import Richiesta, StatoRichiesta, TransizioneNonValida
from consulti.racconto import racconta
from notifiche import servizi

from . import casi as q
from .accesso import solo_gestione

logger = logging.getLogger('consulti')


def _iscrizioni_in_attesa():
    return (Clinica.objects.filter(approvata=False).count()
            + Richiedente.objects.filter(tipo=TipoRichiedente.LIBERO_PROFESSIONISTA, approvato=False).count())


# ── Cruscotto ────────────────────────────────────────────────────────────────

@solo_gestione
def cruscotto(request):
    """Cosa chiede attenzione adesso. Ogni riquadro porta dove si agisce;
    se non c'e' niente da fare lo dice, invece di mostrare zeri."""
    aperti = q.elenco('aperti')
    oggi = timezone.localdate()
    return render(request, 'gestione/cruscotto.html', {
        'sezione': 'cruscotto',
        'in_ritardo': [r for r in aperti if r.in_ritardo],
        'urgenti': [r for r in aperti if r.urgenza and not r.in_ritardo and r.stato != StatoRichiesta.DECLINATA],
        'declinati': [r for r in aperti if r.stato == StatoRichiesta.DECLINATA],
        'n_aperti': len(aperti),
        'iscrizioni': _iscrizioni_in_attesa(),
        'email_ko': q.email_non_partite(),
        'assenti': [r for r in Refertatore.objects.filter(attivo=True).select_related('user')
                    if r.assente_il(oggi)],
    })


# ── Casi ─────────────────────────────────────────────────────────────────────

@solo_gestione
def casi(request):
    filtro = request.GET.get('filtro', 'aperti')
    if filtro not in q.FILTRI:
        filtro = 'aperti'
    cerca = request.GET.get('q', '')
    return render(request, 'gestione/casi.html', {
        'sezione': 'casi', 'righe': q.elenco(filtro, cerca), 'filtro': filtro, 'cerca': cerca,
        'filtri': q.FILTRI,
    })


@solo_gestione
def caso(request, pk):
    richiesta = get_object_or_404(q.inviati(), pk=pk)
    richiesta = q.con_scadenza([richiesta])[0]
    eventi = richiesta.audit.select_related('utente')
    return render(request, 'gestione/caso.html', {
        'sezione': 'casi',
        'richiesta': richiesta,
        'racconto': racconta(eventi, per_staff=True),
        # Il motivo delle azioni della gestione non va nel racconto del
        # richiedente: qui si legge dall'audit.
        'decisioni': [e for e in eventi if e.azione in ('SPOSTATA_DA_GESTIONE', 'ANNULLATA_DA_GESTIONE')],
        'email': richiesta.invii_email.all(),
        'spostabile': richiesta.stato in Richiesta.STATI_SPOSTABILI,
        'esperti': q.esperti_per(richiesta) if richiesta.stato in Richiesta.STATI_SPOSTABILI else [],
    })


@solo_gestione
@require_POST
def sposta(request, pk):
    richiesta = get_object_or_404(q.inviati(), pk=pk)
    refertatore = Refertatore.objects.filter(pk=request.POST.get('refertatore') or None).first()
    motivo = request.POST.get('motivo', '')
    precedente = richiesta.refertatore
    try:
        richiesta.sposta_da_gestione(refertatore, motivo, request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('gestione:caso', pk=pk)
    if precedente is not None and precedente.pk != refertatore.pk:
        servizi.avvisa_caso_tolto(richiesta, precedente)
    servizi.avvisa_caso_arrivato(richiesta)
    servizi.avvisa_richiedente_spostato(richiesta)
    messages.success(request, f'{richiesta.codice} affidato a {refertatore}. Avvisati il nuovo esperto e '
                              f'chi ha chiesto{" (e chi lo aveva prima)" if precedente else ""}.')
    return redirect('gestione:caso', pk=pk)


@solo_gestione
@require_POST
def annulla(request, pk):
    richiesta = get_object_or_404(q.inviati(), pk=pk)
    motivo = request.POST.get('motivo', '')
    esperto = richiesta.refertatore if richiesta.stato != StatoRichiesta.DECLINATA else None
    try:
        richiesta.annulla_da_gestione(motivo, request.user)
    except TransizioneNonValida as e:
        messages.error(request, str(e))
        return redirect('gestione:caso', pk=pk)
    servizi.avvisa_caso_annullato(richiesta, motivo.strip(), refertatore=esperto)
    messages.success(request, f'{richiesta.codice} annullato. Chi ha chiesto riceve il motivo per email.')
    return redirect('gestione:caso', pk=pk)
