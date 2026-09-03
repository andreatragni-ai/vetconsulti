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
venv/bin/python manage.py migrate
venv/bin/python manage.py loaddata eco/fixtures/proiezioni_bozza.json

# Superuser senza prompt
DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@example.com \
DJANGO_SUPERUSER_PASSWORD=admin venv/bin/python manage.py createsuperuser --noinput

venv/bin/python manage.py runserver
```

`manage.py` usa `config.settings.dev` (sqlite `db_dev.sqlite3`, email in
console). In produzione `DJANGO_SETTINGS_MODULE=config.settings.prod` con le
variabili di `deploy/env.example` e `deploy/secrets.env.example`.

Test: `venv/bin/python -m pytest`.

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
  dati di fatturazione" nel blocco `avvisi`, footer con `_footer.html`
  (`privacy_url`, `prodotto="VetWay Consulti"`) piu' i termini;
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
  campo di FORM (`campo=form.x`); `vetway_ui/partials/_campo.html` e' un
  partial ETICHETTA/VALORE in lettura (`label`, `val`, `multiline`).

WeasyPrint su macOS vuole le librerie Homebrew (`brew install pango`);
`ffmpeg` e' facoltativo (senza, le clip eco restano nell'originale).

## Struttura

| Cartella | Cosa |
|---|---|
| `config/` | settings (`base` / `dev` / `prod`), urls, wsgi |
| `core/` | `TipoEsame`, context processor del profilo, consegna protetta dei file (`scarica_allegato`) |
| `accounts/` | Refertatore + competenze, Clinica, DatiFatturazione (validazioni in `fiscale.py`; un solo soggetto fra clinica e richiedente), Richiedente (CLINICA / LIBERO_PROFESSIONISTA), Consenso; login, registrazione a due passi con conferma email, reset password, profili, area staff (refertatori, richiedenti da approvare) |
| `listino/` | VoceListino, Supplemento, `prezzi.prezzo_effettivo()` |
| `consulti/` | Richiesta (codice `TC-AAAA-NNNN`, transizioni con audit), Paziente, Allegato, Commento, EventoAudit append-only; `regole.py`, `upload_chunk.py`, comando `sorveglia_consulti` |
| `eco/` | catalogo proiezioni (fixture `proiezioni_bozza.json`, **da confermare**), ProiezioneCaricata, `transcodifica.py` |
| `referti/` | Referto con `firma()`, template PDF WeasyPrint, view di stampa protetta |
| `registro/` | Prestazione immutabile (`clinica` nulla per il libero professionista, `intestatario()`), StatoFatturazione, `registra_prestazione()`, comando `esporta_prestazioni` (colonne `intestatario`, `tipo_richiedente`) |
| `notifiche/` | InvioEmail e le tre email (testi in `templates/notifiche/*.txt`) |
| `deploy/` | systemd, nginx, env di esempio, `deploy.sh`, `INSTALLAZIONE.md` |

I file caricati non sono mai serviti come statici: passano da
`/allegati/<id>/scarica/` (FileResponse in dev, `X-Accel-Redirect` verso
`/_media_interno/` in produzione).

## Cosa manca (fasi successive)

- **F2 — Flusso di caricamento per tipo**: pagina guidata per ECG / Holter /
  Eco (catalogo proiezioni con istruzioni e immagini di riferimento, clip a
  pezzi con transcodifica in background), commenti con allegati.
- **F3 — Refertazione**: pagina del refertatore (presa in carico, declina,
  non refertabile, editor referto per tipo, firma, PDF), avviso "referto
  pronto" al richiedente, storico versioni del referto.
- **F4 — Amministrazione e fatturazione**: cruscotto prestazioni, stati di
  fatturazione da interfaccia, export mensile, dati di fatturazione dei
  refertatori che emettono in proprio.
- **F5 — Produzione**: storage S3 Hetzner (blocco predisposto in
  `prod.py`), 2FA per i refertatori, monitoraggio, backup verificati.
