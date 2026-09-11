"""
Smistamento automatico dei file di un'ecocardiografia sulle righe del
catalogo delle proiezioni (decisione di Andre dell'11/09/2026: caricare
riga per riga costava circa 10 minuti).

Chi carica trascina la cartella dell'esame (o sceglie i file); il portale
propone dove va ciascun file, chi carica controlla sul «tavolo di
smistamento» e conferma. Gli ecografi dei colleghi esportano filmati e JPEG,
non DICOM: nei file non c'e' il nome della proiezione, e lo si ricava per
gradi (motore.py): formato, colore dai pixel (colore.py), lettura AI della
miniatura (lettore.py), ordine di acquisizione, assegnazione una riga = un
file.

    dati.py        strutture pure (Riga, FileEsame, Lettura, Proposta)
    righe.py       tracciato e colore attesi di una riga, dal nome
    colore.py      B-mode o color Doppler dai pixel, senza AI
    lettore.py     lettura AI (API Anthropic, structured output, telemetria)
    motore.py      i cinque gradi, puro e deterministico
    tavolo.py      proposte, «Sposta in...», «Confermo lo smistamento»
    esecuzione.py  lo smistamento di una richiesta, in un thread

La misura onesta del riconoscimento sul banco di immagini vere del catalogo:
`manage.py valuta_smistamento` (eco/management/commands/).
"""
