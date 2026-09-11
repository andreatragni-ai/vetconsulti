# VetWay Consulti

Portale di teleconsulto cardiologico veterinario: cliniche e singoli
veterinari (liberi professionisti, anche cardiologi) caricano ECG, Holter
ed ecocardiografie, un refertatore referente li referta, il registro tiene
traccia delle prestazioni da fatturare.

## Chi chiede: clinica o libero professionista

Un `Richiedente` ha un `tipo`:

- **CLINICA** — lavora per una struttura (`clinica` obbligatoria). La
  fattura e' intestata alla clinica, i `DatiFatturazione` stanno sulla
  Clinica, l'approvazione dell'admin e' `Clinica.approvata`.
- **LIBERO_PROFESSIONISTA** — nessuna clinica. La fattura e' intestata a
  lui, i `DatiFatturazione` stanno sul Richiedente
  (`richiedente.dati_fatturazione`), l'approvazione e' `Richiedente.approvato`.

`Richiedente.approvazione_ok()`, `puo_richiedere`, `Richiesta.intestatario()`
e `Prestazione.intestatario()` nascondono la differenza a chi deve solo
sapere se si puo' inviare e a chi si fattura. Un refertatore puo' attivare
dal proprio profilo un Richiedente libero professionista (gia' approvato),
riusando i propri dati di fatturazione se li ha: stessa riga, non una copia.

Progetto gemello di VetCardio, ma indipendente: non importa nulla da `cardio`.

## Avvio in locale

```bash
python3.12 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e ../vetway-ui

# WeasyPrint sul Mac: pango/gobject stanno in /opt/homebrew/lib (brew install pango)
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib

venv/bin/python manage.py migrate
venv/bin/python manage.py seed_demo      # listino, catalogo eco, utenti e casi demo (solo DEBUG)
venv/bin/python manage.py runserver 127.0.0.1:8770
```

La variabile va nell'ambiente del comando (o esportata nella shell di
lavoro), non nei file di configurazione della shell. Senza,
`python -c "import weasyprint"` fallisce; dentro i processi Django funziona
comunque grazie al ripiego in `config/settings/base.py`, ma la variabile e'
il modo documentato. Il test che genera il PDF vero salta con un messaggio
chiaro se le librerie non si trovano.

Il catalogo delle proiezioni eco sta in `eco/catalogo/` (JSON + immagini
di riferimento) e `seed_demo` lo carica se il catalogo e' vuoto; dopo
averlo modificato: `venv/bin/python manage.py carica_catalogo_eco`
(idempotente, disattiva le voci tolte dal file).

`seed_demo` crea `admin/admin`, i refertatori `rferrari` (ECG+Holter) e
`lmonti` (eco), i richiedenti `gbianchi` (clinica) e `mrossi` (libero
professionista), password `prova12345`, e due casi gia' INVIATI da
`gbianchi` per collaudare la refertazione: un ECG a `rferrari` e un'eco a
`lmonti` con il referto dell'ecografo e tutte le proiezioni obbligatorie.
Gli allegati sono finti (PDF segnati DIMOSTRATIVO, PNG segnaposto:
`core/demo.py`). Un caso demo nuovo nasce solo se non ce n'e' uno aperto.

Collaudo della richiesta guidata (F2): come `gbianchi`, «Nuova richiesta»
-> paziente -> esame ed esperto (la bozza nasce qui) -> carica gli esami
(trascinare o toccare le zone; per l'eco una riga per proiezione) ->
riepilogo e invio. L'email «caso arrivato» esce in console.

`manage.py` usa `config.settings.dev` (sqlite `db_dev.sqlite3`, email in
console). In produzione `DJANGO_SETTINGS_MODULE=config.settings.prod` con le
variabili di `deploy/env.example` e `deploy/secrets.env.example`.

Test: `venv/bin/python -m pytest`. Prima di un deploy, anche contro Postgres
con i settings di produzione: `scripts/test_postgres.sh` (una volta:
`createdb consulti_dev`). Il controllo dei settings di produzione senza
server: `set -a; . deploy/env.example; set +a` piu' i quattro segreti finti,
poi `DJANGO_SETTINGS_MODULE=config.settings.prod manage.py check --deploy`.

## Grafica: pacchetto vetway-ui

Lo strato grafico (Bootstrap, Icons e HTMX serviti in locale, `vetway.css`,
template base, partial generici) e' il pacchetto condiviso **vetway-ui**,
repo fratello in `../vetway-ui`, agganciato al tag `v0.1.0`:

```bash
venv/bin/pip install -e ../vetway-ui      # in sviluppo
```

`"vetway_ui"` sta in `INSTALLED_APPS` prima delle app del portale. In
`requirements.txt` la riga `vetway-ui @ git+ssh://...@v0.1.0` e' commentata
(TODO: URL del repo); sul server `deploy/deploy.sh` copia `../vetway-ui` in
`/home/consulti/vetway-ui` e fa `pip install -e` prima di `migrate`.

Come lo usa il portale:

- `templates/base.html` e' l'host sopra `vetway_ui/base.html`: testata
  (`.consulti-testata`), navbar con il partial `_navbar.html` del pacchetto
  e le voci da `core.context_processors.navigazione`, avviso "completa i
  dati di fatturazione" nel blocco `avvisi`, footer con lo stesso markup
  di `_footer.html` (`.ovic-footer`) ma senza «Django + PostgreSQL», con
  privacy e termini (torna all'include quando vetway-ui 0.3.0 lo permette);
  `data-sessione-minuti` da `core.context_processors.sessione_minuti`.
- `templates/auth_base.html` e' l'host sopra `vetway_ui/auth_base.html`
  (login, scelta registrazione, reset password, esiti).
- Le pagine usano le classi del pacchetto (`.ovic-card` / `.card-header-ovic`
  / `.card-body-ovic`, `.tbl-risultati`, `.btn-nuova`, `.btn-testata-ghost`,
  `.btn-sel`, `.sezione-sottotitolo`, `.campo-label`/`.campo-valore`) e i
  partial `_campo.html` (etichetta/valore in lettura),
  `_modal_conferma_elimina.html` (annulla richiesta, elimina allegato),
  `_regole_password.html` + `_genera_password.html` (registrazione, reset,
  cambio password).
- Cio' che e' solo del portale sta in `static/consulti/css/consulti.css`,
  caricato nel blocco `host_head`: stati della richiesta, testata, avviso,
  blocchi del form di registrazione, testi legali. Nessun colore letterale:
  solo variabili `--ovic-*` del pacchetto e `--bs-*` di Bootstrap.
- **Attenzione all'omonimia**: `templates/_campo_form.html` del portale e' un
  campo di FORM (`campo=form.x`); `templates/_dato.html` e' un dato in SOLA
  LETTURA come testo (`label`, `val`, `multiline`, `url`) e dall'11/09/2026
  prende il posto di `vetway_ui/partials/_campo.html`, che disegna il valore
  con il bordo di un input (la variante e' da portare in vetway-ui 0.3.0).

WeasyPrint su macOS vuole le librerie Homebrew (`brew install pango`);
`ffmpeg` e' facoltativo (senza, le clip eco restano nell'originale).

## Struttura

| Cartella | Cosa |
|---|---|
| `config/` | settings (`base` / `dev` / `prod`), urls, wsgi |
| `core/` | `TipoEsame`, context processor del profilo e della navbar (contatore dei casi da decidere), consegna protetta dei file (`scarica_allegato`, `?inline=1` per il visore), `seed_demo` e i file finti di `demo.py` |
| `accounts/` | Refertatore (con foto, `foto.py` la riduce; servita da `core.views_media.foto_refertatore`) + competenze (prezzo, tempo di risposta, `accetta_urgenze`), Clinica, DatiFatturazione (validazioni in `fiscale.py`; un solo soggetto fra clinica e richiedente), Richiedente (CLINICA / LIBERO_PROFESSIONISTA), Consenso; login, registrazione a due passi con conferma email, reset password, profili, area staff (refertatori, richiedenti da approvare) |
| `listino/` | VoceListino, Supplemento, `prezzi.prezzo_effettivo()` |
| `consulti/` | Richiesta (codice `TC-AAAA-NNNN`, `titolo` «Luna · Ecocardiografia», transizioni con audit, `riassegna` dopo un declino), Paziente, Allegato, Commento, EventoAudit append-only; richiesta guidata in quattro passi (`percorso.py`, `views_percorso.py`, template `percorso/`, `static/consulti/js/carica.js`), `razze.py` (razze per specie copiate da VetCardio, campo con `static/consulti/js/elenco_filtrato.js`), `nomi.py` (maiuscole su nome e cognome), `caricamento.py` (zona + tipo di file -> categoria, ProiezioneCaricata, sostituzione), `elenco_file.py` (i file di un caso in ordine di catalogo per il visore e la pagina del caso), `regole.py` (invio con `elementi_obbligatori`, riassegnazione, tempo di risposta: 4 ore se urgente, urgenze solo a chi le accetta), `permessi.py` (chi agisce), `motivi.py` (frasi per declinare / non refertabile), `racconto.py` (audit leggibile), `views_decisione.py` (casi ricevuti, prendi in carico, declina, non refertabile), `upload_chunk.py`, comando `sorveglia_consulti` (rilascio + sollecito a meta' tempo) |
| `eco/` | catalogo proiezioni (`catalogo/catalogo_eco.json` + `catalogo/img/`, comando `carica_catalogo_eco`; finestre acustiche, filmati liberi, ImmagineRiferimento), ProiezioneCaricata, `transcodifica.py` |
| `referti/` | Referto (copia di lavoro) con `firma()` e `rettifica()`, VersioneReferto (istantanea firmata + PDF), `blocchi.py` (voci per tipo: il punto di aggancio delle misure ECG), pagina di refertazione con visore allegati e bozza automatica, PDF WeasyPrint, stampa protetta delle versioni |
| `registro/` | Prestazione immutabile (`clinica` nulla per il libero professionista, `intestatario()`), StatoFatturazione, `registra_prestazione()`, comando `esporta_prestazioni` (colonne `intestatario`, `tipo_richiedente`) |
| `notifiche/` | InvioEmail e le email quando la palla cambia mano: caso arrivato, sollecito, rilascio (al refertatore); referto pronto e rettificato con il PDF allegato, caso declinato, non refertabile (al richiedente). Testi in `templates/notifiche/*.txt` |
| `deploy/` | systemd, nginx, env di esempio, `deploy.sh`, `INSTALLAZIONE.md` |

I file caricati non sono mai serviti come statici: passano da
`/allegati/<id>/scarica/` (FileResponse in dev, `X-Accel-Redirect` verso
`/_media_interno/` in produzione).

## Cosa manca (fasi successive)

- **F2 — Richiesta guidata**: costruita (branch `feat/richiesta-guidata`),
  in attesa delle conferme di Andre in `docs/BACKLOG.md`. Mancano i
  commenti con allegati.
- **F3 — Refertazione**: costruita (branch `feat/refertazione`), in attesa
  delle conferme di Andre elencate in `docs/BACKLOG.md`. Mancano le misure
  ECG strutturate, che arriveranno dal lettore SEIVA di VetCardio.
- **F4 — Amministrazione e fatturazione**: cruscotto prestazioni, stati di
  fatturazione da interfaccia, export mensile, dati di fatturazione dei
  refertatori che emettono in proprio.
- **F5 — Produzione**: storage S3 Hetzner (blocco predisposto in
  `prod.py`), 2FA per i refertatori, monitoraggio, backup verificati.
