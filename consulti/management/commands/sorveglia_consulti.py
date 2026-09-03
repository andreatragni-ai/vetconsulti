"""
Rilascia le prese in carico ferme da troppo.

Un refertatore prende in carico un caso e poi non lo referta: e' malato,
ha dimenticato, non era il suo. Il caso resta bloccato e chi ha chiesto non
puo' girarlo a nessun altro. Ogni ora (cron) questo comando riporta a
INVIATA cio' che e' PRESA_IN_CARICO da oltre CONSULTI_ORE_PRESA_IN_CARICO
ore, lasciando traccia nell'audit, e sollecita il refertatore.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from consulti.models import Richiesta, StatoRichiesta


class Command(BaseCommand):
    help = 'Rilascia le prese in carico ferme oltre CONSULTI_ORE_PRESA_IN_CARICO ore.'

    def add_arguments(self, parser):
        parser.add_argument('--ore', type=int, default=None,
                            help='Scavalca CONSULTI_ORE_PRESA_IN_CARICO per questa esecuzione.')
        parser.add_argument('--prova', action='store_true', help='Mostra senza fare nulla.')

    def handle(self, *args, **opzioni):
        ore = opzioni['ore'] or getattr(settings, 'CONSULTI_ORE_PRESA_IN_CARICO', 24)
        soglia = timezone.now() - timedelta(hours=ore)
        ferme = Richiesta.objects.filter(stato=StatoRichiesta.PRESA_IN_CARICO, presa_in_carico_il__lt=soglia)
        if not ferme.exists():
            self.stdout.write(f'Nessuna presa in carico ferma da oltre {ore} ore.')
            return
        from notifiche.servizi import sollecita_refertatore
        for r in ferme:
            da_quanto = timezone.now() - r.presa_in_carico_il
            if opzioni['prova']:
                self.stdout.write(f'[prova] {r.codice}: presa in carico da {r.refertatore} da {da_quanto}.')
                continue
            r.rilascia_presa_in_carico(motivo=f'Rilascio automatico dopo {ore} ore senza referto.')
            sollecita_refertatore(r)
            self.stdout.write(self.style.WARNING(
                f'{r.codice}: rilasciata (era di {r.refertatore} da {da_quanto}), refertatore sollecitato.'))
