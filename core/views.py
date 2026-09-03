"""Pagine legali pubbliche. Nessun login: chi si registra deve poterle
leggere prima di spuntare le caselle."""

from django.conf import settings
from django.shortcuts import render


def privacy(request):
    return render(request, 'core/privacy.html', {'versione': settings.VERSIONE_PRIVACY})


def termini(request):
    return render(request, 'core/termini.html', {'versione': settings.VERSIONE_TERMINI})
