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
  Rifiniture del collaudo dell'11/09 (branch `feat/rifiniture-collaudo`, da
  questo): specie solo cane/gatto; razza da elenco per specie
  (`consulti/razze.py`, copiato da VetCardio); data di nascita come testo
  gg/mm/aaaa; maiuscole su nome e cognome (`consulti/nomi.py`); foto
  dell'esperto; filmati «massimo 10 secondi»; urgenze a 4 ore e solo a chi
  le accetta; file del refertatore in ordine di catalogo
  (`consulti/elenco_file.py`); dati in lettura come testo
  (`templates/_dato.html`). Da confermare: (h) una razza fuori elenco si
  accetta con l'avviso «Non e' nell'elenco»; (i) `accetta_urgenze` per tipo
  di esame sulla competenza, spento in partenza; (l) una parola gia' con
  maiuscole («McDonald», anche «ROSSI») non si tocca. Dopo il merge:
  `migrate` e `carica_catalogo_eco`.
- [2026-09-11] **F3 — Andre conferma le scelte della refertazione**
  (branch `feat/refertazione`, da provare su `runserver` con `seed_demo`):
  (a) blocco per tipo minimo — ECG solo rischio anestesiologico con le voci
  di VetCardio, Holter ed eco solo le tre caselle (`referti/blocchi.py`);
  (b) "non refertabile" chiude il caso SENZA prestazione, e l'email dice
  "non ti viene addebitato"; (c) testi delle email in
  `notifiche/templates/notifiche/*.txt` e frasi rapide in
  `consulti/motivi.py`; (d) tempo di risposta non dichiarato = 48 h; un
  caso urgente sempre 4 h, deciso l'11/09 (`regole.ore_risposta`). Fatto =
  scelte confermate o corrette, poi merge in `main`.
- [2026-09-11] **Catalogo eco: le ultime lacune** (D6). Il catalogo di
  Andre e' in `eco/catalogo/catalogo_eco.json` (27 righe, 25 obbligatorie,
  62 immagini collegate; `manage.py carica_catalogo_eco`). Mancano le
  immagini di riferimento di SUB_B e SUB_C, quelle di SUB_LVOT_* e D2_PVPA
  sono parziali (vedi `nota_riferimento`), e le `istruzioni` sono punti
  elenco incollati senza punteggiatura: da rileggere nel file.

## Prossimo

- [2026-09-11] Commenti con allegati sul caso (resto di F2).
- [2026-09-11] vetway-ui 0.3.0: portare nel pacchetto i componenti nati
  in `static/consulti/css/consulti.css` per F2 (`.passi`, `.schede-scelta`,
  `.zona-carica`, `.lista-controllo`, `.percorso-barra`), l'elenco filtrato
  (`.elenco-filtrato` + `static/consulti/js/elenco_filtrato.js`), una
  variante «testo» di `partials/_campo.html` senza il bordo da input (oggi
  `templates/_dato.html` + `.dato-*`) e una variabile del footer per
  togliere «Django + PostgreSQL»; poi il portale torna a usare gli include
  del pacchetto.
- [2026-09-11] Miniature dei filmati nel visore del refertatore: le produce
  il lavoro sullo smistamento; `consulti/elenco_file.py` ha gia' il campo
  `miniatura` per voce.
- [2026-09-11] Anche «Assente dal/al» nel profilo del refertatore e' un
  type="date": su Safari vuoto sembra compilato come la data di nascita.
  Stessa cura (testo gg/mm/aaaa) se ad Andre da' fastidio.
- [2026-09-11] Termini del servizio: dire che l'urgenza promette la
  risposta entro 4 ore (oggi dicono solo «supplemento di listino»), da
  far rileggere al legale con il resto.

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
