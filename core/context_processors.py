"""
Variabili di contesto lette dal layout di vetway-ui e dalla navbar.

`navigazione` costruisce le voci della barra nella forma che vuole
`vetway_ui/partials/_navbar.html` (lista di dict url/label/icona/attiva):
la cornice e il CSS sono del pacchetto, chi vede cosa lo decide il portale,
in un posto solo.
"""

from django.conf import settings
from django.contrib.auth.password_validation import password_validators_help_texts
from django.urls import reverse


def profilo(request):
    utente = getattr(request, 'user', None)
    if not utente or not utente.is_authenticated:
        return {'refertatore': None, 'richiedente': None}
    return {
        'refertatore': getattr(utente, 'refertatore', None),
        'richiedente': getattr(utente, 'richiedente', None),
    }


def sessione_minuti(request):
    """Durata della sessione in minuti, per il conto alla rovescia di vetway-ui
    (data-sessione-minuti sul <body>, letto da vetway.js). Derivato da
    SESSION_COOKIE_AGE: se cambia la durata, l'avviso non mente."""
    return {'sessione_minuti': settings.SESSION_COOKIE_AGE // 60}


def dettatura(request):
    """Se ha senso mostrare il pulsante «Ripulisci» della dettatura vocale
    (templates/_campo_dettatura.html): serve la chiave AI sul server. Il
    microfono del browser funziona comunque, perche' non passa da noi."""
    return {'dettatura_ai': settings.CONSULTI_DETTATURA_AI}


def regole_password(request):
    """Le regole di AUTH_PASSWORD_VALIDATORS in italiano, per il partial
    vetway_ui/partials/_regole_password.html accanto ai campi password."""
    return {'regole_password': password_validators_help_texts()}


def assistenza(request):
    """A chi scrivere quando qualcosa non torna: lo mostrano le pagine di
    errore (403, 404). Uno solo, da settings, cosi' non finisce scritto a
    mano in tre template diversi."""
    return {'email_assistenza': settings.EMAIL_REPLY_TO}


def navigazione(request):
    utente = getattr(request, 'user', None)
    corrente = request.resolver_match.url_name if getattr(request, 'resolver_match', None) else ''

    def voce(nome_url, label, icona, attivi=()):
        attivi = attivi or (nome_url.split(':')[-1],)
        return {'url': reverse(nome_url), 'label': label, 'icona': icona, 'attiva': corrente in attivi}

    if not utente or not utente.is_authenticated:
        return {
            'nav_voci': [voce('accounts:accedi', 'Accedi', 'box-arrow-in-right'),
                         voce('accounts:registrati', 'Registrati', 'person-plus', ('registrati', 'registrati_tipo'))],
            'nav_menu_titolo': 'VetWay Consulti',
        }

    richiedente = getattr(utente, 'richiedente', None)
    refertatore = getattr(utente, 'refertatore', None)
    voci = []
    if refertatore:
        # Il contatore dice quanti casi aspettano una decisione (INVIATA):
        # la palla e' nel campo del refertatore.
        from consulti.models import Richiesta, StatoRichiesta
        da_decidere = Richiesta.objects.filter(refertatore=refertatore, stato=StatoRichiesta.INVIATA).count()
        etichetta = f'Casi ricevuti ({da_decidere})' if da_decidere else 'Casi ricevuti'
        voci.append(voce('consulti:casi_ricevuti', etichetta, 'clipboard2-pulse', ('casi_ricevuti', 'refertazione')))
    if richiedente:
        voci.append(voce('consulti:mie_richieste', 'Le mie richieste', 'inbox',
                         ('mie_richieste', 'dettaglio', 'passo_paziente', 'passo_esame', 'passo_carica',
                          'passo_riepilogo')))
        voci.append(voce('consulti:nuova', 'Nuova richiesta', 'plus-circle', ('nuova', 'nuova_esame')))
        voci.append(voce('accounts:profilo_richiedente', 'Profilo', 'person'))
    if refertatore:
        voci.append(voce('accounts:profilo_refertatore', 'Profilo refertatore', 'person-badge'))
    if utente.is_staff:
        # Una voce sola: dentro, le sezioni (gestione/_sezioni.html). L'admin
        # di Django non sta piu' nella barra (13/09/2026): e' per le
        # riparazioni, si raggiunge da /admin/ a mano.
        namespace = getattr(getattr(request, 'resolver_match', None), 'namespace', '')
        voci.append({'url': reverse('gestione:cruscotto'), 'label': 'Gestione', 'icona': 'speedometer2',
                     'attiva': namespace == 'gestione'})

    if richiedente:
        utente_url = reverse('accounts:profilo_richiedente')
    elif refertatore:
        utente_url = reverse('accounts:profilo_refertatore')
    else:
        utente_url = reverse('accounts:home')
    return {
        'nav_voci': voci,
        'nav_menu_titolo': 'VetWay Consulti',
        'utente_label': utente.get_full_name() or utente.get_username(),
        'utente_url': utente_url,
        'logout_url': reverse('accounts:esci'),
    }
