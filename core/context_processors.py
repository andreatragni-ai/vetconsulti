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


def regole_password(request):
    """Le regole di AUTH_PASSWORD_VALIDATORS in italiano, per il partial
    vetway_ui/partials/_regole_password.html accanto ai campi password."""
    return {'regole_password': password_validators_help_texts()}


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
        voci.append(voce('consulti:mie_richieste', 'Le mie richieste', 'inbox', ('mie_richieste', 'dettaglio')))
        voci.append(voce('consulti:nuova', 'Nuova richiesta', 'plus-circle'))
        voci.append(voce('accounts:profilo_richiedente', 'Profilo', 'person'))
    elif utente.is_staff:
        voci.append(voce('consulti:mie_richieste', 'Richieste', 'inbox', ('mie_richieste', 'dettaglio')))
    if refertatore:
        voci.append(voce('accounts:profilo_refertatore', 'Profilo refertatore', 'person-badge'))
    if utente.is_staff:
        voci.append(voce('accounts:admin_refertatori', 'Refertatori', 'people',
                         ('admin_refertatori', 'admin_refertatore_aggiungi')))
        voci.append(voce('accounts:admin_richiedenti', 'Richiedenti', 'person-check'))
        voci.append({'url': reverse('admin:index'), 'label': 'Admin', 'icona': 'gear', 'attiva': False})

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
