# Backlog VetWay Consulti

Tre liste. "Adesso" ha al massimo tre voci. Una voce fatta si cancella, non si
spunta. Le idee grosse hanno un file loro in `docs/`.

## Adesso

- [2026-09-11] **F2 — Andre prova la richiesta guidata e conferma le scelte**
  (branch `feat/richiesta-guidata`, da `fix/esperto-per-tipo`; collaudo
  con `seed_demo` come `gbianchi`). Fatto: quattro passi (Paziente, Esame
  ed esperto, Carica gli esami, Invia) con indicatore, bozza che nasce al
  passo 2 e si riprende dal primo passo incompleto; caricamento per tipo
  con categoria dedotta dal file (`consulti/caricamento.py`); eco con una
  riga per voce del catalogo, a gruppi per finestra, immagini di
  riferimento, filmati liberi con nota, clip a pezzi con limite di peso
  (`ECO_CLIP_MAX_BYTE`) e transcodifica dopo il commit; riepilogo con
  prezzo e «Modifica»; il caso si chiama come il paziente. Criterio di
  fatto verde: `consulti/tests_percorso.py::test_criterio_di_fatto_f2`.
  Da confermare: (a) testi di etichette, suggerimenti e zone
  (`consulti/forms.py`, `consulti/views_percorso.py`, template in
  `consulti/templates/consulti/percorso/`); (b) «Motivo dell'esame» tolto
  dal form (colonna rimasta, vuota); (c) obbligatori solo nome, specie,
  sesso e quesito; eta' come data OPPURE anni interi; (d) una riga
  accetta solo cio' che il catalogo si aspetta (filmato o immagine; DICOM
  in entrambe), il referto Holter e quello dell'ecografo solo in PDF;
  (e) nota del filmato libero obbligatoria; (f) cambiare tipo di esame
  con file gia' caricati e' bloccato; (g) un esperto diventato assente
  dopo il passo 2 non blocca l'invio: il riepilogo lo segnala.
  Restano fuori: commenti con allegati; la pagina del refertatore con il
  visore piu' grande (passo successivo).
  **Smistamento automatico dell'eco** (branch `feat/smistamento`, dal
  collaudo dell'11/09: caricare riga per riga costava ~10 minuti). Fatto:
  zona unica che prende la cartella intera dell'esame (o i file, su
  iPad/iPhone), miniature fatte dal browser, smistamento per gradi
  (formato; B-mode/color dai pixel; lettura AI delle miniature con Claude
  Opus 5, structured output, «sconosciuto» invece di indovinare; ordine di
  acquisizione; assegnazione una riga = un file) in un thread dopo il
  commit, «tavolo di smistamento» con bollino sicuro / da verificare, i
  file da smistare a parte, spostamento per trascinamento o «Sposta in...»,
  e «Confermo lo smistamento» (nulla diventa ProiezioneCaricata prima);
  protocollo stampabile delle proiezioni (`/eco/protocollo/`, anche PDF).
  Da confermare ad Andre: (a) il modello e la spesa per esame (Opus 5,
  stima $ 0,2-0,4 per 26 miniature; `CONSULTI_MODELLO_SMISTAMENTO` per
  cambiarlo); (b) il taglio della fascia alta della miniatura prima
  dell'invio (`CONSULTI_SMISTAMENTO_TAGLIO_ALTO`, oggi 8 %) per non
  mandare nome del paziente e codice; (c) la frase nell'informativa
  privacy sul fornitore AI (da far validare al legale); (d) cosa deve
  fare il portale con i filmati che il browser non decodifica (AVI, WMV)
  se sul server non c'e' ffmpeg: oggi restano da smistare a mano.
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
- [2026-09-11] **Catalogo eco: le ultime lacune** (D6). Il catalogo di
  Andre e' in `eco/catalogo/catalogo_eco.json` (27 righe, 25 obbligatorie,
  62 immagini collegate; `manage.py carica_catalogo_eco`). Mancano le
  immagini di riferimento di SUB_B e SUB_C, quelle di SUB_LVOT_* e D2_PVPA
  sono parziali (vedi `nota_riferimento`), e le `istruzioni` sono punti
  elenco incollati senza punteggiatura: da rileggere nel file.

## Prossimo

- [2026-09-12] **Misurare davvero lo smistamento**: `manage.py
  valuta_smistamento` e' pronto (banco di 26 immagini ecografiche vere del
  catalogo, verita' dal catalogo, niente file del kit che hanno il nome
  scritto dentro) ma la chiave in `~/.zshrc` e' rifiutata dall'API
  (401 «API key is invalid», 11/09/2026). Con una chiave valida:
  `ANTHROPIC_API_KEY=... venv/bin/python manage.py valuta_smistamento
  --taglio 0 --json a.json` e poi `--taglio 0.08` e `--ordine protocollo`,
  per avere accuratezza, confusioni, «sicuri» sbagliati, token e costo per
  esame. Finche' non c'e' quel numero, lo smistamento AI resta da provare
  sul campo.
- [2026-09-11] Commenti con allegati sul caso (resto di F2).
- [2026-09-11] vetway-ui 0.3.0: portare nel pacchetto i componenti nati
  in `static/consulti/css/consulti.css` per F2 (`.passi`, `.schede-scelta`,
  `.zona-carica`, `.lista-controllo`, `.percorso-barra`) e una variabile
  del footer per togliere «Django + PostgreSQL»; poi il portale torna a
  usare l'include del pacchetto.

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
