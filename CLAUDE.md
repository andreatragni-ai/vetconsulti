# VetWay Consulti

Portale di teleconsulto cardiologico veterinario (ECG, Holter, eco): cliniche e
liberi professionisti caricano gli esami, un refertatore referta, il registro
tiene le prestazioni da fatturare. Progetto gemello di VetCardio (`../vetcardio`)
ma **indipendente: non importa mai da `cardio`**. Lo sviluppa Andre da solo, a
sessioni brevi: ogni sessione deve lasciare il repo in uno stato ripartibile.

## Stato (aggiornare quando cambia)

- **Non e' in produzione.** Verificato l'08/09/2026: sul server (10.10.0.1)
  non esistono utente `consulti`, db, vhost nginx, ne' il record DNS di
  `consulti.vetway.it`. Tutto `deploy/` e' scritto ma mai eseguito.
- Obiettivo: poche cliniche amiche entro 1-2 mesi (ottobre-novembre 2026).
  Priorita': F2 (caricamento per tipo) e F3 (refertazione). F4 (fatturazione)
  puo' aspettare. Il lavoro e' in `docs/BACKLOG.md`.
- Il catalogo delle proiezioni eco e' quello di Andre (11/09/2026): 27 righe,
  25 obbligatorie + 2 filmati liberi, in `eco/catalogo/catalogo_eco.json` con le
  immagini di riferimento in `eco/catalogo/img/` (dalla sua presentazione). Si
  ricarica con `manage.py carica_catalogo_eco`. Le decisioni e i punti aperti
  stanno nella sua nota Obsidian "Telemedicina" (vault Second brain).
- F3 (refertazione) costruita sul branch `feat/refertazione` l'11/09/2026,
  non ancora in `main`: aspetta le conferme elencate in `docs/BACKLOG.md`.

## Avvio e collaudo

    export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib   # WeasyPrint sul Mac (vedi sotto)
    venv/bin/python manage.py migrate && venv/bin/python manage.py seed_demo
    venv/bin/python manage.py runserver 127.0.0.1:8770
    venv/bin/python -m pytest          # pochi secondi, deve essere verde prima di ogni commit

`seed_demo` (solo DEBUG) crea listino, catalogo eco (se vuoto) e utenti:
`admin/admin`, refertatori `rferrari` (ECG+Holter) e `lmonti` (eco),
richiedenti `gbianchi` (clinica) e `mrossi` (libero professionista), password
`prova12345`; e due casi gia' INVIATI da `gbianchi`: un ECG a `rferrari` e
un'eco a `lmonti` (allegati finti segnati DIMOSTRATIVO, `core/demo.py`). Un
caso demo nuovo nasce solo se non ce n'e' uno aperto: rilanciare dopo averlo
refertato ne prepara un altro. Le email escono in console (anche il PDF
allegato). Grafica dal pacchetto `../vetway-ui` installato con `pip install -e`.

**WeasyPrint sul Mac**: senza `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`
`python -c "import weasyprint"` non trova pango/gobject. Dentro i processi
Django funziona anche senza (ripiego in `config/settings/base.py`), ma la
variabile e' il modo documentato: niente modifiche ai file della shell.
Senza librerie il test del PDF vero salta con un messaggio che lo dice.

## Regole

- **Migrazioni libere fino al go-live**: si possono cancellare e rigenerare;
  `db_dev.sqlite3` si ricrea con `migrate` + `seed_demo`. Si congelano al
  primo deploy con dati veri (segnarlo qui quel giorno).
- Commit `tipo(area): cosa cambia per chi usa il portale`, in italiano
  (`feat` `fix` `docs` `test` `refactor` `chore`). Un branch `feat/...` per
  cosa; `main` sempre verde. Push a fine sessione, anche `wip`.
- Testi in italiano con apostrofo ASCII al posto delle accentate (`e'`,
  `piu'`, `gia'`) in codice, commenti, commit e docs: convenzione storica.
- Ogni bug corretto lascia un test nel `tests.py` dell'app.
- UI solo con classi, partial e variabili `--ovic-*` di vetway-ui: nessun
  colore letterale. Attenzione all'omonimia `_campo_form.html` (form) vs
  `_dato.html` (lettura, come testo: nel portale sostituisce
  `vetway_ui/partials/_campo.html`, che ha il bordo da input).
- Nessun deploy, DNS, o comando sul server senza che Andre lo chieda in
  quella sessione. Il primo deploy sara' una staging non pubblicizzata.

## Zone fragili (leggere prima di toccare)

- `accounts/fiscale.py`: validazioni CF/P.IVA/SDI; un solo soggetto fiscale
  fra clinica e richiedente. `Richiedente.tipo` decide a chi si fattura.
- `consulti/regole.py`: transizioni di stato della Richiesta con
  `EventoAudit` append-only. Non aggiungere stati senza un test per ogni
  transizione. Un caso urgente scade in 4 ore e va solo a chi accetta le
  urgenze per quel tipo (`rifiuta_urgenza`, test in
  `consulti/tests_urgenze.py`).
- `registro/`: `Prestazione` e' immutabile una volta registrata.
- `core/views_media.py` + `consulti/upload_chunk.py`: gli allegati non sono
  mai serviti come statici (FileResponse in dev, X-Accel-Redirect in prod).
  `?inline=1` li mostra nel visore (iframe della stessa origine, SAMEORIGIN).
- `consulti/permessi.py`: solo il refertatore assegnato agisce, il
  richiedente sul suo caso, lo staff legge e lascia ACCESSO_STAFF, gli altri 404.
- `referti/models.py`: salvare la bozza non firma MAI; `firma()` e
  `rettifica()` sono le sole strade per una `VersioneReferto` (immutabile);
  la prestazione si registra una volta sola, alla prima firma. Il JS della
  pagina di refertazione salva prima di confermare la firma: la modale del
  pacchetto e' inclusa DOPO `extra_js`, quindi si ascolta sul documento.
- `config/settings/prod.py`: tutto dall'ambiente, `check --deploy` pulito.

Struttura delle app e dettagli: `README.md`. Installazione server:
`deploy/INSTALLAZIONE.md`. Skill globale `vetcardio-django` per il gemello.
