"""
Le persone del portale viste dalla Gestione: refertatori e iscrizioni.

## Perche' il refertatore nasce con una password casuale

PasswordResetForm.get_users() scarta chi ha una password inutilizzabile:
un account creato con set_unusable_password() non riceverebbe l'invito.
Quindi si mette una password casuale da `secrets` che nessuno conosce, e
il link di reset fa il resto.

## Chi fattura in proprio salva due righe insieme

Refertatore.clean() pretende i dati di fatturazione se emette in proprio,
e quel controllo gira gia' dentro form.is_valid(). Quindi i dati si salvano
PRIMA, dentro una transazione, e si annulla tutto se il resto del form ha
errori: niente righe orfane, e l'errore arriva sul campo giusto.
"""

import logging
import secrets

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.db import transaction
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.forms import CompetenzaForm, DatiFatturazioneForm, NuovoRefertatoreForm, competenze_complete
from accounts.models import (Clinica, CompetenzaRefertatore, Refertatore, Richiedente, SoggettoEmittente,
                             TipoRichiedente)
from listino.prezzi import PrezzoNonDisponibile, prezzo_effettivo
from notifiche import servizi

from .accesso import solo_gestione
from .forms import RefertatoreGestioneForm, UtenteForm

logger = logging.getLogger('accounts')
User = get_user_model()


def genera_password_casuale():
    """Password che nessuno deve conoscere: tiene l'account «con password
    utilizzabile» finche' l'utente non sceglie la sua dal link di invito."""
    return secrets.token_urlsafe(32)


def invia_invito(request, utente):
    """Riusa il reset password di Django con testi da invito."""
    form = PasswordResetForm({'email': utente.email})
    if not form.is_valid():
        return False
    try:
        form.save(
            request=request, use_https=request.is_secure(),
            subject_template_name='accounts/invito_subject.txt',
            email_template_name='accounts/invito_email.txt')
    except Exception:
        logger.exception('Invio invito fallito per %s', utente.username)
        return False
    return True


# ── Refertatori ──────────────────────────────────────────────────────────────

@solo_gestione
def refertatori(request):
    elenco = Refertatore.objects.select_related('user').prefetch_related('competenze')
    return render(request, 'gestione/refertatori.html', {'sezione': 'refertatori', 'refertatori': elenco})


@solo_gestione
def refertatore_nuovo(request):
    form = NuovoRefertatoreForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            utente = User.objects.create_user(
                username=d['username'], email=d['email'], password=genera_password_casuale(),
                first_name=d['first_name'], last_name=d['last_name'])
            ref = Refertatore.objects.create(
                user=utente, titolo=d['titolo'], specializzazione=d['specializzazione'],
                numero_iscrizione=d['numero_iscrizione'], ordine_provinciale=d['ordine_provinciale'])
            for tipo in d['tipi_referente']:
                CompetenzaRefertatore.objects.create(refertatore=ref, tipo_esame=tipo, referente=True)
        if invia_invito(request, utente):
            messages.success(request, f'{ref} aggiunto: l\'invito per scegliere la password e\' partito '
                                      f'verso {utente.email}. Completa qui prezzi e tempi.')
        else:
            messages.warning(request, f'{ref} aggiunto, ma l\'invito non e\' partito: riprova da questa pagina.')
        return redirect('gestione:refertatore', pk=ref.pk)
    return render(request, 'gestione/refertatore_nuovo.html', {'sezione': 'refertatori', 'form': form})


def _prezzi_di_listino():
    """{tipo: prezzo} per mostrare, accanto al campo vuoto, cosa vale «listino»."""
    from core.tipi import TipoEsame
    prezzi = {}
    for tipo in TipoEsame.values:
        try:
            prezzi[tipo] = prezzo_effettivo(tipo).imponibile
        except PrezzoNonDisponibile:
            prezzi[tipo] = None
    return prezzi


@solo_gestione
def refertatore(request, pk):
    ref = get_object_or_404(Refertatore.objects.select_related('user', 'dati_fatturazione'), pk=pk)
    Competenze = modelformset_factory(CompetenzaRefertatore, form=CompetenzaForm, extra=0)
    dati = request.POST or None
    form_u = UtenteForm(dati, instance=ref.user, prefix='u')
    form_r = RefertatoreGestioneForm(dati, request.FILES or None, instance=ref, prefix='r')
    formset = Competenze(dati, queryset=competenze_complete(ref), prefix='k')
    form_f = DatiFatturazioneForm(dati, instance=ref.dati_fatturazione, prefix='f')

    if request.method == 'POST':
        with transaction.atomic():
            dati_ok = True
            if form_r.in_proprio:
                dati_ok = form_f.is_valid()
                if dati_ok:
                    form_r.instance.dati_fatturazione = form_f.save()
            if dati_ok and form_u.is_valid() and form_r.is_valid() and formset.is_valid():
                form_u.save()
                form_r.save()
                formset.save()
                messages.success(request, f'{ref} salvato.')
                return redirect('gestione:refertatore', pk=pk)
            transaction.set_rollback(True)
        messages.error(request, 'Non salvato: correggi i campi segnati.')

    prezzi = _prezzi_di_listino()
    righe = [{'form': f, 'listino': prezzi.get(f.instance.tipo_esame)} for f in formset]
    return render(request, 'gestione/refertatore.html', {
        'sezione': 'refertatori', 'ref': ref, 'form_u': form_u, 'form_r': form_r, 'formset': formset,
        'righe': righe, 'form_f': form_f, 'in_proprio': form_r.in_proprio,
        'mai_entrato': ref.user.last_login is None,
        'casi_aperti': ref.richieste.filter(stato__in=('INVIATA', 'PRESA_IN_CARICO')).count(),
    })


@solo_gestione
@require_POST
def refertatore_invito(request, pk):
    ref = get_object_or_404(Refertatore.objects.select_related('user'), pk=pk)
    if invia_invito(request, ref.user):
        messages.success(request, f'Invito rimandato a {ref.user.email}.')
    else:
        messages.error(request, 'L\'invito non e\' partito: controlla l\'email e riprova.')
    return redirect('gestione:refertatore', pk=pk)


# ── Iscrizioni ───────────────────────────────────────────────────────────────

@solo_gestione
def iscrizioni(request):
    """Prima chi aspetta, poi chi e' gia' dentro. Per ognuno le tre cose che
    servono a decidere: chi e', dove lavora, se ha dato i dati fiscali."""
    cliniche = Clinica.objects.prefetch_related('richiedenti__user', 'dati_fatturazione').order_by('denominazione')
    liberi = (Richiedente.objects.filter(tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
              .select_related('user').order_by('user__last_name'))
    return render(request, 'gestione/iscrizioni.html', {
        'sezione': 'iscrizioni',
        'cliniche_attesa': [c for c in cliniche if not c.approvata],
        'liberi_attesa': [r for r in liberi if not r.approvato],
        'cliniche_ok': [c for c in cliniche if c.approvata],
        'liberi_ok': [r for r in liberi if r.approvato],
    })


@solo_gestione
@require_POST
def clinica_approva(request, pk):
    """Approvare la clinica abilita tutti i suoi colleghi in un colpo, quindi
    l'avviso va a ognuno di loro e non solo a chi si e' iscritto per primo.

    Chi non ha ancora confermato l'email resta fuori: «puoi inviare» a chi
    non riesce nemmeno ad accedere e' un invito a sbattere contro il login.
    Lo scopre da se' entrando, che e' comunque il passo successivo.
    """
    clinica = get_object_or_404(Clinica, pk=pk)
    clinica.approvata = True
    clinica.save(update_fields=['approvata'])
    avvisati = 0
    for richiedente in clinica.richiedenti.select_related('user').filter(user__is_active=True):
        if servizi.avvisa_richiedente_approvato(richiedente):
            avvisati += 1
    messages.success(request, f'Clinica «{clinica.denominazione}» approvata. '
                              f'Avvisat{"o" if avvisati == 1 else "i"} {avvisati} collegh{"a" if avvisati == 1 else "i"} per email.')
    return redirect('gestione:iscrizioni')


@solo_gestione
@require_POST
def richiedente_approva(request, pk):
    richiedente = get_object_or_404(Richiedente, pk=pk, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA)
    richiedente.approvato = True
    richiedente.save(update_fields=['approvato'])
    if servizi.avvisa_richiedente_approvato(richiedente):
        messages.success(request, f'«{richiedente.denominazione}» approvato e avvisato per email.')
    else:
        messages.warning(request, f'«{richiedente.denominazione}» approvato, '
                                  'ma l\'email di avviso non e\' partita.')
    return redirect('gestione:iscrizioni')
