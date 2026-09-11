"""
Sorveglianza dei casi aperti (cron, ogni ora). Due compiti:

1. **Rilascio.** Un refertatore prende in carico un caso e poi non lo
   referta: e' malato, ha dimenticato, non era il suo. Il caso resta
   bloccato. Cio' che e' PRESA_IN_CARICO da oltre CONSULTI_ORE_PRESA_IN_CARICO
   ore torna INVIATA, con traccia nell'audit, e il refertatore riceve
   l'avviso del rilascio.

2. **Sollecito a meta' tempo.** Per ogni caso INVIATA o PRESA_IN_CARICO,
   passata la meta' del tempo di risposta dichiarato dall'esperto
   (`regole.ore_risposta_dichiarate`: la competenza, altrimenti 48 ore, 4 per
   un'urgenza) parte UN promemoria. Idempotente: il promemoria lascia un
   evento SOLLECITO nell'audit e non si ripete finche' il caso non viene
   rinviato (una riassegnazione riparte da zero, con il nuovo esperto).

`--prova` mostra cosa farebbe senza toccare nulla e senza inviare email.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from consulti import regole
from consulti.models import Richiesta, StatoRichiesta


def sollecito_gia_partito(richiesta):
    return richiesta.audit.filter(azione='SOLLECITO', quando__gte=richiesta.inviata_il).exists()


class Command(BaseCommand):
    help = 'Rilascia le prese in carico ferme e sollecita i refertatori a meta\' del tempo di risposta.'

    def add_arguments(self, parser):
        parser.add_argument('--ore', type=int, default=None,
                            help='Scavalca CONSULTI_ORE_PRESA_IN_CARICO per questa esecuzione.')
        parser.add_argument('--prova', action='store_true', help='Mostra senza fare nulla e senza inviare.')

    def handle(self, *args, **opzioni):
        prova = opzioni['prova']
        rilasciate = self._rilascia(opzioni['ore'] or getattr(settings, 'CONSULTI_ORE_PRESA_IN_CARICO', 24), prova)
        self._sollecita(escludi=rilasciate, prova=prova)

    def _rilascia(self, ore, prova):
        from notifiche.servizi import avvisa_presa_rilasciata
        soglia = timezone.now() - timedelta(hours=ore)
        ferme = Richiesta.objects.filter(stato=StatoRichiesta.PRESA_IN_CARICO, presa_in_carico_il__lt=soglia)
        fatte = set()
        if not ferme.exists():
            self.stdout.write(f'Nessuna presa in carico ferma da oltre {ore} ore.')
            return fatte
        for r in ferme:
            da_quanto = timezone.now() - r.presa_in_carico_il
            if prova:
                self.stdout.write(f'[prova] {r.codice}: presa in carico da {r.refertatore} da {da_quanto}: '
                                  f'verrebbe rilasciata.')
                continue
            r.rilascia_presa_in_carico(motivo=f'Rilascio automatico dopo {ore} ore senza referto.')
            avvisa_presa_rilasciata(r, ore)
            fatte.add(r.pk)
            self.stdout.write(self.style.WARNING(
                f'{r.codice}: rilasciata (era di {r.refertatore} da {da_quanto}), refertatore avvisato.'))
        return fatte

    def _sollecita(self, escludi, prova):
        from notifiche.servizi import sollecita_refertatore
        adesso = timezone.now()
        aperte = (Richiesta.objects.filter(stato__in=[StatoRichiesta.INVIATA, StatoRichiesta.PRESA_IN_CARICO],
                                           refertatore__isnull=False, inviata_il__isnull=False)
                  .exclude(pk__in=escludi).select_related('refertatore__user'))
        quanti = 0
        for r in aperte:
            ore = regole.ore_risposta_dichiarate(r)
            meta = r.inviata_il + timedelta(hours=ore / 2)
            if adesso < meta or sollecito_gia_partito(r):
                continue
            quanti += 1
            if prova:
                self.stdout.write(f'[prova] {r.codice}: {r.refertatore} verrebbe sollecitato '
                                  f'(inviato {r.inviata_il:%d/%m %H:%M}, risposta in {ore} h).')
                continue
            ok = sollecita_refertatore(r, ore)
            r.registra('SOLLECITO', None, ore_dichiarate=ore, email_inviata=ok)
            self.stdout.write(f'{r.codice}: sollecito a {r.refertatore} ({"inviato" if ok else "email NON partita"}).')
        if not quanti:
            self.stdout.write('Nessun caso da sollecitare.')
