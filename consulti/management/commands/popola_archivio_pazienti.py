"""
Porta in archivio i pazienti dei casi gia' inviati (una volta sola).

L'archivio pazienti (`consulti/anagrafica.py`) si riempie da solo a ogni
invio, ma i casi inviati PRIMA del 05/11/2026 non hanno lasciato nulla:
questo comando ripassa i casi dal piu' vecchio al piu' recente e chiama la
stessa funzione dell'invio, cosi' l'ultimo caso di ogni paziente e' quello
che decide i dati, come succederebbe andando avanti.

Si puo' rilanciare: un paziente gia' in archivio viene riconosciuto dalla
chiave e aggiornato, non duplicato. `--prova` non scrive niente.
"""

from django.core.management.base import BaseCommand
from django.db import models

from consulti import anagrafica
from consulti.models import PazienteArchivio, Richiesta, StatoRichiesta


class Command(BaseCommand):
    help = 'Crea le voci dell\'archivio pazienti dai casi gia\' inviati.'

    def add_arguments(self, parser):
        parser.add_argument('--prova', action='store_true', help='Mostra cosa farebbe senza scrivere.')

    def handle(self, *args, **opzioni):
        casi = (Richiesta.objects.exclude(stato=StatoRichiesta.BOZZA)
                .filter(paziente__isnull=False)
                .select_related('paziente', 'richiedente__clinica')
                .order_by(models.F('inviata_il').asc(nulls_first=True)))
        prima = PazienteArchivio.objects.count()
        fatti = 0
        for caso in casi:
            if opzioni['prova']:
                self.stdout.write(f'{caso.codice}: {caso.paziente.nome} '
                                  f'({caso.intestatario().denominazione})')
                fatti += 1
                continue
            if anagrafica.registra(caso) is not None:
                fatti += 1
        dopo = prima if opzioni['prova'] else PazienteArchivio.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'{fatti} casi ripassati, {dopo - prima} pazienti nuovi in archivio '
            f'({dopo} in tutto){" — prova, niente scritto" if opzioni["prova"] else ""}.'))
