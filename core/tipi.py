"""
Tipi di esame comuni a tutto il portale.

Vivono qui e non in `consulti` perche' li usano anche listino, accounts
(competenze del refertatore), registro e referti: un'app di dominio che
importa da un'altra app di dominio crea dipendenze circolari alla prima
occasione. `core` non ha modelli, quindi importarla e' sempre sicuro.
"""

from django.db import models


class TipoEsame(models.TextChoices):
    ECG = 'ECG', 'Elettrocardiogramma'
    HOLTER = 'HOLTER', 'Holter'
    ECO = 'ECO', 'Ecocardiografia'
