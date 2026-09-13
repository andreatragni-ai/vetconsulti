"""
Accesso, registrazione e profili.

## Conferma email e invito: stesso meccanismo

Tanto la conferma dell'email di un richiedente quanto l'invito a un nuovo
refertatore usano il token monouso di Django (default_token_generator):
scade, si invalida al primo uso perche' dipende da last_login e dalla
password, e non richiede una tabella nostra.

L'invito di un collega nella stessa clinica non puo' usare quel token —
l'utente da invitare non esiste ancora — e usa una firma a tempo:
`accounts/inviti.py`.

Le pagine dello staff (refertatori, iscrizioni, approvazioni) stanno in
`gestione/`.
"""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView
from django.core.mail import EmailMessage
from django.db import transaction
from django.forms import modelformset_factory
from django.http import Http404
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from notifiche import servizi

from . import inviti
from .forms import (ClinicaForm, CompetenzaForm, DatiFatturazioneForm, RefertatoreProfiloForm,
                    RegistrazioneForm, RichiedenteForm, competenze_complete)
from .models import (Clinica, CompetenzaRefertatore, Consenso, Richiedente, TipoConsenso,
                     TipoRichiedente, versione_consenso)

logger = logging.getLogger('accounts')
User = get_user_model()


class Accedi(LoginView):
    template_name = 'accounts/accedi.html'
    redirect_authenticated_user = True


class Esci(LogoutView):
    pass


@login_required
def home(request):
    """La radice smista per profilo: chi ha un solo profilo va dritto."""
    if hasattr(request.user, 'richiedente') or hasattr(request.user, 'refertatore'):
        return redirect('consulti:mie_richieste')
    if request.user.is_staff:
        return redirect('gestione:cruscotto')
    return render(request, 'accounts/senza_profilo.html')


@login_required
def password_cambiata(request):
    messages.success(request, 'Password cambiata.')
    return redirect('accounts:home')


# ── Registrazione richiedente ────────────────────────────────────────────────

def _link_token(request, utente, nome_url):
    uid = urlsafe_base64_encode(force_bytes(utente.pk))
    token = default_token_generator.make_token(utente)
    return request.build_absolute_uri(reverse(nome_url, args=[uid, token]))


TIPI_REGISTRAZIONE = {
    'clinica': TipoRichiedente.CLINICA,
    'libero-professionista': TipoRichiedente.LIBERO_PROFESSIONISTA,
}


def registrati(request, tipo=None):
    """Due passi: prima si dice chi si e' (clinica o libero professionista),
    poi si compila il form giusto. Il tipo viaggia nell'URL, cosi' la
    pagina di scelta e' un semplice link e il form non deve nascondere e
    mostrare campi a colpi di JavaScript."""
    if request.user.is_authenticated:
        return redirect('accounts:home')
    if tipo is None:
        return render(request, 'accounts/registrati_scelta.html')
    if tipo not in TIPI_REGISTRAZIONE:
        raise Http404
    return _registrazione(request, TIPI_REGISTRAZIONE[tipo])


def registrati_invitato(request, token):
    """Iscrizione da un link di invito: la clinica la decide il link.

    Il collega non sceglie la struttura e non ne propone una nuova, quindi
    non puo' sbagliare clinica ne' crearne un doppione. L'approvazione
    resta quella del soggetto fiscale: se la clinica e' gia' approvata,
    puo' inviare subito (decisione del 12/09/2026).
    """
    if request.user.is_authenticated:
        return redirect('accounts:home')
    try:
        clinica, invitante = inviti.leggi(token)
    except inviti.InvitoNonValido as e:
        return render(request, 'accounts/invito_non_valido.html', {'motivo': str(e)}, status=400)
    return _registrazione(request, TipoRichiedente.CLINICA,
                          clinica_invito=clinica, invitante=invitante)


def _registrazione(request, tipo_richiedente, clinica_invito=None, invitante=None):
    """Il corpo dell'iscrizione, comune al percorso normale e all'invito."""
    form = RegistrazioneForm(request.POST or None, tipo=tipo_richiedente,
                             clinica_invito=clinica_invito)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            utente = form.save(commit=False)
            utente.is_active = False  # finche' non conferma l'email
            utente.save()
            clinica = clinica_invito
            if clinica is None and tipo_richiedente == TipoRichiedente.CLINICA:
                clinica = form.cleaned_data.get('clinica')
                if clinica is None:
                    clinica = Clinica.objects.create(
                        denominazione=form.cleaned_data['nuova_clinica'],
                        comune=form.cleaned_data.get('nuova_clinica_comune', ''),
                        provincia=form.cleaned_data.get('nuova_clinica_provincia', '').upper(),
                        approvata=False)
            richiedente = Richiedente.objects.create(
                user=utente, tipo=tipo_richiedente, clinica=clinica,
                telefono=form.cleaned_data.get('telefono', ''),
                ruolo=form.cleaned_data['ruolo'],
                numero_iscrizione=form.cleaned_data.get('numero_iscrizione', ''),
                ordine_provinciale=form.cleaned_data.get('ordine_provinciale', ''))
            # Dati di fatturazione predefiniti sul soggetto giusto. None se il
            # blocco e' stato saltato (si compila dal profilo prima del primo
            # invio) o se la clinica li aveva gia'.
            dati = form.dati_fatturazione
            if dati is not None:
                if tipo_richiedente == TipoRichiedente.CLINICA:
                    if clinica.dati_fatturazione_predefiniti is not None:
                        dati.predefinita = False  # la clinica ne ha gia' una: si conserva senza scavalcarla
                    dati.clinica = clinica
                else:
                    dati.richiedente = richiedente
                dati.save()
            for tipo_consenso in (TipoConsenso.PRIVACY, TipoConsenso.TERMINI):
                Consenso.objects.create(user=utente, tipo=tipo_consenso,
                                        versione=versione_consenso(tipo_consenso))

        _invia_conferma_email(request, utente)
        servizi.avvisa_gestore_iscrizione(richiedente, invitante=invitante)
        return render(request, 'accounts/registrazione_inviata.html', {'email': utente.email})
    return render(request, 'accounts/registrati.html', {
        'form': form, 'tipo': tipo_richiedente,
        'clinica_invito': clinica_invito, 'invitante': invitante})


def _invia_conferma_email(request, utente):
    link = _link_token(request, utente, 'accounts:conferma_email')
    corpo = render_to_string('accounts/email_conferma.txt', {'utente': utente, 'link': link})
    try:
        EmailMessage(
            subject='VetWay Consulti — conferma la tua email',
            body=corpo, to=[utente.email],
            reply_to=[settings.EMAIL_REPLY_TO]).send()
    except Exception:
        logger.exception('Invio conferma email fallito per %s', utente.username)


def conferma_email(request, uidb64, token):
    try:
        utente = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        utente = None
    if utente is None or not default_token_generator.check_token(utente, token):
        return render(request, 'accounts/conferma_email_non_valida.html', status=400)
    if not utente.is_active:
        utente.is_active = True
        utente.save(update_fields=['is_active'])
    login(request, utente)
    messages.success(request, 'Email confermata. Completa il profilo per chiedere un consulto.')
    return redirect('accounts:profilo_richiedente')


# ── Profilo richiedente ──────────────────────────────────────────────────────

@login_required
def profilo_richiedente(request):
    richiedente = getattr(request.user, 'richiedente', None)
    if richiedente is None:
        messages.error(request, 'Il tuo account non e\' un richiedente.')
        return redirect('accounts:home')

    clinica = richiedente.clinica
    e_clinica = not richiedente.e_libero_professionista
    dati = richiedente.dati_fatturazione_predefiniti

    form_r = RichiedenteForm(request.POST or None, instance=richiedente, prefix='r')
    form_c = ClinicaForm(request.POST or None, instance=clinica, prefix='c') if e_clinica else None
    form_f = DatiFatturazioneForm(request.POST or None, instance=dati, prefix='f')

    if request.method == 'POST':
        quale = request.POST.get('salva')
        if quale == 'richiedente' and form_r.is_valid():
            form_r.save()
            messages.success(request, 'Dati personali salvati.')
            return redirect('accounts:profilo_richiedente')
        if quale == 'clinica' and form_c is not None and form_c.is_valid():
            c = form_c.save()
            if richiedente.clinica_id != c.id:
                richiedente.clinica = c
                richiedente.save(update_fields=['clinica'])
            messages.success(request, 'Dati della clinica salvati.')
            return redirect('accounts:profilo_richiedente')
        if quale == 'fatturazione':
            if e_clinica and clinica is None:
                messages.error(request, 'Prima salva la clinica.')
            elif form_f.is_valid():
                f = form_f.save(commit=False)
                if e_clinica:
                    f.clinica = clinica
                else:
                    f.richiedente = richiedente
                f.predefinita = True
                f.save()
                # Un refertatore che chiede consulti a proprio nome ha gli stessi
                # dati fiscali da entrambe le parti: una riga sola, collegata.
                refertatore = getattr(request.user, 'refertatore', None)
                if refertatore is not None and not e_clinica and refertatore.dati_fatturazione_id is None:
                    refertatore.dati_fatturazione = f
                    refertatore.save(update_fields=['dati_fatturazione'])
                messages.success(request, 'Dati di fatturazione salvati.')
                return redirect('accounts:profilo_richiedente')

    consensi = Consenso.objects.filter(user=request.user)
    # Link per invitare un collega nella stessa clinica: si rigenera a ogni
    # visita (e' una firma, non una riga da conservare) e vale 14 giorni.
    # Solo per chi lavora in una struttura: un libero professionista non ha
    # nessuno da far entrare.
    link_invito = ''
    if e_clinica and clinica is not None:
        link_invito = request.build_absolute_uri(
            reverse('accounts:registrati_invitato', args=[inviti.crea(clinica, request.user)]))
    return render(request, 'accounts/profilo_richiedente.html', {
        'richiedente': richiedente, 'form_r': form_r, 'form_c': form_c, 'form_f': form_f,
        'consensi': consensi, 'clinica': clinica, 'e_clinica': e_clinica,
        'intestatario': richiedente.soggetto_fatturazione,
        'link_invito': link_invito, 'giorni_invito': inviti.GIORNI_VALIDITA,
    })


# ── Profilo refertatore ──────────────────────────────────────────────────────

@login_required
def profilo_refertatore(request):
    refertatore = getattr(request.user, 'refertatore', None)
    if refertatore is None:
        messages.error(request, 'Il tuo account non e\' un refertatore.')
        return redirect('accounts:home')

    CompetenzeFormSet = modelformset_factory(CompetenzaRefertatore, form=CompetenzaForm, extra=0)
    queryset = competenze_complete(refertatore)
    form_p = RefertatoreProfiloForm(request.POST or None, request.FILES or None,
                                    instance=refertatore, prefix='p')
    formset = CompetenzeFormSet(request.POST or None, queryset=queryset, prefix='k')

    if request.method == 'POST' and form_p.is_valid() and formset.is_valid():
        form_p.save()
        formset.save()
        messages.success(request, 'Profilo aggiornato.')
        return redirect('accounts:profilo_refertatore')

    return render(request, 'accounts/profilo_refertatore.html', {
        'refertatore': refertatore, 'form_p': form_p, 'formset': formset,
        'richiedente': getattr(request.user, 'richiedente', None),
    })


@login_required
@require_POST
def refertatore_diventa_richiedente(request):
    """Un refertatore che vuole anche chiedere consulti a proprio nome.

    Nasce gia' approvato: chi lo ha invitato come refertatore lo ha gia'
    guardato in faccia. Se ha dati di fatturazione propri (emette in
    proprio) si collegano alla nuova veste — una riga sola, non una copia:
    cambiare l'indirizzo in un posto deve cambiarlo anche nell'altro.
    """
    refertatore = getattr(request.user, 'refertatore', None)
    if refertatore is None:
        raise Http404
    if hasattr(request.user, 'richiedente'):
        messages.info(request, 'Sei gia\' anche richiedente.')
        return redirect('accounts:profilo_richiedente')
    with transaction.atomic():
        richiedente = Richiedente.objects.create(
            user=request.user, tipo=TipoRichiedente.LIBERO_PROFESSIONISTA, approvato=True,
            numero_iscrizione=refertatore.numero_iscrizione,
            ordine_provinciale=refertatore.ordine_provinciale)
        dati = refertatore.dati_fatturazione
        if dati is not None and dati.clinica_id is None and dati.richiedente_id is None:
            dati.richiedente = richiedente
            dati.predefinita = True
            dati.save(update_fields=['richiedente', 'predefinita'])
    messages.success(request, 'Ora puoi anche chiedere consulti a tuo nome.')
    return redirect('accounts:profilo_richiedente')
