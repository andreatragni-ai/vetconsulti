"""Invito di un collega nella stessa clinica.

## Un invito e' un messaggio, non uno stato da tenere

Nessuna tabella: il link porta una firma di Django (`signing.dumps`) con la
clinica e chi invita, e vale `GIORNI_VALIDITA` giorni. Stesso spirito del
token di conferma email e dell'invito al refertatore (accounts.views): se il
link scade o viene manomesso non c'e' niente da ripulire.

Il prezzo e' che un singolo link non si revoca (solo cambiando SECRET_KEY,
che butterebbe giu' anche le sessioni): chi ha il link puo' iscriversi alla
clinica finche' non scade. Accettabile perche' iscriversi non basta a
spedire nulla — resta l'approvazione del soggetto fiscale
(`Richiedente.approvazione_ok`) e il richiedente compare fra i colleghi
della clinica in `gestione/richiedenti/`, dove uno di troppo si vede. Il
giorno che servira' sapere chi ha invitato chi e chi ha accettato, questo
modulo diventera' un modello.
"""

from django.core import signing

from .models import Clinica

SALE = 'accounts.invito-collega'
GIORNI_VALIDITA = 14
_MAX_AGE = GIORNI_VALIDITA * 24 * 60 * 60


class InvitoNonValido(Exception):
    """Link scaduto, manomesso, o clinica che non esiste piu'."""


def crea(clinica, invitante):
    """Token da mettere nel link. `invitante` serve solo a dire al collega
    chi lo ha invitato: se quell'utente sparisce, l'invito resta valido."""
    return signing.dumps({'c': clinica.pk, 'da': invitante.pk}, salt=SALE)


def leggi(token):
    """→ (Clinica, utente invitante o None). Solleva InvitoNonValido."""
    try:
        dati = signing.loads(token, salt=SALE, max_age=_MAX_AGE)
    except signing.SignatureExpired:
        raise InvitoNonValido(
            f'L\'invito e\' scaduto: vale {GIORNI_VALIDITA} giorni. '
            'Chiedi al collega di generarne uno nuovo.')
    except (signing.BadSignature, TypeError, ValueError):
        raise InvitoNonValido('Il link dell\'invito non e\' valido: forse si e\' rotto nel copiarlo.')
    clinica = Clinica.objects.filter(pk=dati.get('c')).first()
    if clinica is None:
        raise InvitoNonValido('La clinica dell\'invito non esiste piu\'.')
    from django.contrib.auth import get_user_model
    invitante = get_user_model().objects.filter(pk=dati.get('da')).first()
    return clinica, invitante
