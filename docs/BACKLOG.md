# Backlog VetWay Consulti

Tre liste. "Adesso" ha al massimo tre voci. Una voce fatta si cancella, non si
spunta. Le idee grosse hanno un file loro in `docs/`.

## Adesso

- [2026-09-08] **F2 — Flusso di caricamento per tipo**: pagina guidata
  ECG / Holter / Eco (catalogo proiezioni con istruzioni e immagini di
  riferimento, clip a pezzi con transcodifica in background), commenti con
  allegati. Fatto = un richiedente `seed_demo` completa un invio per ciascun
  tipo con test verdi.
- [2026-09-11] **F3 — Andre conferma le scelte della refertazione**
  (branch `feat/refertazione`, da provare su `runserver` con `seed_demo`):
  (a) blocco per tipo minimo — ECG solo rischio anestesiologico con le voci
  di VetCardio, Holter ed eco solo le tre caselle (`referti/blocchi.py`);
  (b) "non refertabile" chiude il caso SENZA prestazione, e l'email dice
  "non ti viene addebitato"; (c) testi delle email in
  `notifiche/templates/notifiche/*.txt` e frasi rapide in
  `consulti/motivi.py`; (d) tempo di risposta non dichiarato = 48 h, 4 h
  se urgente (`regole.ore_risposta_dichiarate`). Fatto = scelte confermate
  o corrette, poi merge in `main`.
- [2026-09-08] **Confermare il catalogo proiezioni eco** (D6): Andre rivede
  `eco/fixtures/proiezioni_bozza.json` e fornisce le immagini di riferimento.

## Prossimo

- [2026-09-11] Misure ECG strutturate nel referto: quando il lettore SEIVA
  di VetCardio e' pronto, le sue voci entrano nel blocco ECG di
  `referti/blocchi.py` (e, se serve, in `referti/blocchi/_ecg.html`).

- [2026-09-08] vetway-ui e' su GitHub: scommentare la riga in
  `requirements.txt` (`@v0.2.0`) e semplificare `deploy.sh` (step 1b).
- [2026-09-08] Staging: record DNS `consulti.vetway.it` + INSTALLAZIONE.md
  sul server, collaudo con `seed_demo` per qualche giorno prima di aprire.
- [2026-09-08] Privacy e termini: bozze reali da far validare a un legale
  (oggi placeholder linkati dalle checkbox di registrazione).
- [2026-09-08] 2FA per i refertatori (F5).

## Un giorno

- F4 — Cruscotto prestazioni, stati di fatturazione da interfaccia, export
  mensile, dati fiscali dei refertatori che emettono in proprio.
- Gestionale fatture in casa (XML FatturaPA + PEC allo SDI): da validare col
  commercialista prima di scrivere codice.
- Storage S3 Hetzner (blocco predisposto in `prod.py`), monitoraggio, backup
  verificati (F5).
