# Backlog VetWay Consulti

Tre liste. "Adesso" ha al massimo tre voci. Una voce fatta si cancella, non si
spunta. Le idee grosse hanno un file loro in `docs/`.

## Adesso

- [2026-09-08] **F2 — Flusso di caricamento per tipo**: pagina guidata
  ECG / Holter / Eco (catalogo proiezioni con istruzioni e immagini di
  riferimento, clip a pezzi con transcodifica in background), commenti con
  allegati. Fatto = un richiedente `seed_demo` completa un invio per ciascun
  tipo con test verdi.
- [2026-09-08] **F3 — Refertazione**: pagina del refertatore (presa in
  carico, declina, non refertabile, editor per tipo, firma, PDF), avviso
  "referto pronto", storico versioni. Fatto = `lmonti` referta un'eco di
  `gbianchi` e la mail parte in console.
- [2026-09-08] **Confermare il catalogo proiezioni eco** (D6): Andre rivede
  `eco/fixtures/proiezioni_bozza.json` e fornisce le immagini di riferimento.

## Prossimo

- [2026-09-08] vetway-ui e' su GitHub: scommentare la riga in
  `requirements.txt` (`@v0.2.0`) e semplificare `deploy.sh` (step 1b).
- [2026-09-08] Suite contro Postgres locale (db `consulti_dev`) prima del
  primo deploy: sqlite perdona, Postgres no.
- [2026-09-08] `DJANGO_SETTINGS_MODULE=config.settings.prod manage.py check
  --deploy` e `collectstatic` in locale con `deploy/env.example`.
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
