"""Chi entra nella Gestione: solo lo staff.

Chi non e' staff riceve 404, non un rimando al login: stessa regola dei
casi (consulti/permessi.py), non si conferma che la pagina esista. Chi non
ha fatto l'accesso va invece al login, come ovunque nel portale.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404


def solo_gestione(vista):
    @login_required
    @wraps(vista)
    def avvolta(request, *args, **kwargs):
        if not request.user.is_staff:
            raise Http404
        return vista(request, *args, **kwargs)
    return avvolta
