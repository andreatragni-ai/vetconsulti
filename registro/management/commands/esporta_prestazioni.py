"""Esporta in CSV le prestazioni di un mese, per chi fattura. Stesso file
del pulsante «Scarica CSV» in Gestione → Prestazioni (registro/esporta.py)."""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from registro.esporta import del_mese, scrivi_csv


class Command(BaseCommand):
    help = 'Esporta le prestazioni di un mese in CSV. Es.: esporta_prestazioni --mese 2026-09 --su sett.csv'

    def add_arguments(self, parser):
        parser.add_argument('--mese', required=True, help='AAAA-MM')
        parser.add_argument('--su', required=True, help='File CSV di destinazione')

    def handle(self, *args, **opz):
        try:
            anno, mese = (int(x) for x in opz['mese'].split('-'))
            date(anno, mese, 1)
        except (ValueError, TypeError):
            raise CommandError('Formato --mese non valido: usa AAAA-MM.')
        with open(opz['su'], 'w', newline='', encoding='utf-8') as f:
            n = scrivi_csv(del_mese(anno, mese), f)
        self.stdout.write(self.style.SUCCESS(f'{n} prestazioni scritte in {opz["su"]}.'))
