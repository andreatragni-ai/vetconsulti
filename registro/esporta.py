"""Le righe del CSV delle prestazioni: le usano il comando
`esporta_prestazioni` e il pulsante «Scarica CSV» della Gestione, cosi' il
file e' identico da tutte e due le parti."""

import csv

COLONNE = ['data', 'codice_richiesta', 'tipo_esame', 'intestatario', 'tipo_richiedente', 'refertatore',
           'soggetto_emittente', 'imponibile', 'supplementi', 'aliquota_iva', 'totale', 'origine_prezzo',
           'stato_fatturazione', 'numero_fattura']


def del_mese(anno, mese):
    from .models import Prestazione
    return (Prestazione.objects.filter(data__year=anno, data__month=mese)
            .select_related('richiesta__paziente', 'clinica', 'richiedente__user', 'refertatore__user',
                            'fatturazione')
            .order_by('data', 'id'))


def scrivi_csv(prestazioni, file):
    w = csv.writer(file, delimiter=';')
    w.writerow(COLONNE)
    n = 0
    for p in prestazioni:
        fatt = getattr(p, 'fatturazione', None)
        w.writerow([p.data.isoformat(), p.richiesta.codice, p.tipo_esame, p.intestatario().denominazione,
                    p.richiedente.tipo, str(p.refertatore), p.soggetto_emittente, p.imponibile, p.supplementi,
                    p.aliquota_iva, p.totale, p.origine_prezzo,
                    fatt.stato if fatt else '', fatt.numero_fattura if fatt else ''])
        n += 1
    return n
