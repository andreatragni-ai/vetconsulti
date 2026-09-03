"""Esporta in CSV le prestazioni di un mese, per chi fattura."""

import csv
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from registro.models import Prestazione


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
        qs = (Prestazione.objects.filter(data__year=anno, data__month=mese)
              .select_related('richiesta', 'clinica', 'richiedente__user', 'refertatore__user', 'fatturazione').order_by('data', 'id'))
        colonne = ['data', 'codice_richiesta', 'tipo_esame', 'intestatario', 'tipo_richiedente', 'refertatore', 'soggetto_emittente',
                   'imponibile', 'supplementi', 'aliquota_iva', 'totale', 'origine_prezzo',
                   'stato_fatturazione', 'numero_fattura']
        n = 0
        with open(opz['su'], 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(colonne)
            for p in qs:
                fatt = getattr(p, 'fatturazione', None)
                w.writerow([p.data.isoformat(), p.richiesta.codice, p.tipo_esame, p.intestatario().denominazione,
                            p.richiedente.tipo,
                            str(p.refertatore), p.soggetto_emittente, p.imponibile, p.supplementi,
                            p.aliquota_iva, p.totale, p.origine_prezzo,
                            fatt.stato if fatt else '', fatt.numero_fattura if fatt else ''])
                n += 1
        self.stdout.write(self.style.SUCCESS(f'{n} prestazioni scritte in {opz["su"]}.'))
