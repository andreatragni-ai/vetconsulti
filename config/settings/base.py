"""
Settings comuni a sviluppo e produzione di VetWay Consulti.

Nessun segreto qui: questo file e' versionato. Cio' che cambia fra un
ambiente e l'altro (chiave, database, posta, host) sta in dev.py / prod.py
e, per la produzione, arriva dalle variabili d'ambiente lette da
/etc/consulti/env e /etc/consulti/secrets.env (vedi deploy/).
"""

import os
from pathlib import Path

# WeasyPrint su macOS con Homebrew richiede libgobject nel path dinamico.
if os.uname().sysname == 'Darwin':
    _brew_lib = '/opt/homebrew/lib'
    _dyld = os.environ.get('DYLD_LIBRARY_PATH', '')
    if _brew_lib not in _dyld:
        os.environ['DYLD_LIBRARY_PATH'] = f'{_brew_lib}:{_dyld}' if _dyld else _brew_lib

# config/settings/base.py -> config/settings -> config -> radice del progetto
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Il ripiego e' volutamente inservibile: in produzione prod.py pretende la
# variabile d'ambiente e si rifiuta di partire senza.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'NON-CONFIGURATA-vedi-config-settings')

DEBUG = False
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # Strato grafico condiviso: PRIMA delle app del portale, cosi' i template
    # e gli static dell'ospite hanno la precedenza in caso di omonimia.
    'vetway_ui',
    # Le nostre app. L'ordine conta poco, ma `core` prima delle altre rende
    # esplicito che e' la base condivisa.
    'core',
    'accounts',
    'listino',
    'consulti',
    'eco',
    'referti',
    'registro',
    'notifiche',
    'gestione',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.profilo',
                'core.context_processors.sessione_minuti',
                'core.context_processors.dettatura',
                'core.context_processors.navigazione',
                'core.context_processors.regole_password',
                'core.context_processors.assistenza',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'it-it'
TIME_ZONE = 'Europe/Rome'
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = False

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

# ── File caricati ────────────────────────────────────────────────────────────
# MEDIA_URL NON e' esposto da urls.py: gli allegati di un consulto sono dati
# clinici e passano SOLO da core.views_media.scarica_allegato, che verifica
# chi chiede. In produzione nginx serve /_media_interno/ come `internal`.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Backend di storage configurabile. In dev FileSystemStorage sotto media/.
# Per passare a S3 (Hetzner Object Storage) via django-storages, in prod.py
# si sostituisce 'default' — vedi il blocco commentato la'.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

LOGIN_URL = '/accedi/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accedi/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Sessione ─────────────────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 18000            # 300 minuti
SESSION_SAVE_EVERY_REQUEST = True     # rinnova il timeout a ogni richiesta

# ── Posta ────────────────────────────────────────────────────────────────────
DEFAULT_FROM_EMAIL = os.environ.get('EMAIL_FROM', 'VetWay Consulti <noreply@vetway.it>')
# L'app invia da noreply@ ma chi risponde deve arrivare a una persona.
EMAIL_REPLY_TO = os.environ.get('EMAIL_REPLY_TO', 'consulti@vetway.it')
SERVER_EMAIL = os.environ.get('EMAIL_SERVER', 'errori@vetway.it')
# Chi approva le iscrizioni: riceve un avviso a ogni nuovo richiedente.
# Non e' ADMINS (quelli sono gli errori 500, che vanno in un'altra casella).
EMAIL_GESTORE = os.environ.get('EMAIL_GESTORE', EMAIL_REPLY_TO)
ADMINS = [('Errori VetWay Consulti', os.environ.get('EMAIL_ERRORS', 'errori@vetway.it'))]
MANAGERS = ADMINS

# ── Parametri applicativi ────────────────────────────────────────────────────
# URL assoluto del portale, usato nei link dentro le email (non c'e' una
# request quando manda un cron).
CONSULTI_BASE_URL = os.environ.get('CONSULTI_BASE_URL', 'http://localhost:8000')

# Dopo quante ore una presa in carico senza referto viene rilasciata dal
# comando sorveglia_consulti, cosi' il caso torna disponibile.
CONSULTI_ORE_PRESA_IN_CARICO = int(os.environ.get('CONSULTI_ORE_PRESA_IN_CARICO', '24'))

# Versione dei testi legali (core/templates/core/privacy.html e termini.html).
# E' il valore che finisce in Consenso.versione: cambiare il testo vuol dire
# cambiare la data qui, e da quel momento il consenso va richiesto di nuovo.
# La lettera dopo la data: secondo cambiamento del testo nello stesso giorno
# (12/09: le miniature dell'eco al mattino, il testo dettato al pomeriggio).
VERSIONE_PRIVACY = '2026-09-12b'
VERSIONE_TERMINI = '2026-09-02'

# Binario ffmpeg per la transcodifica delle clip eco. Se manca, eco.transcodifica
# logga un avviso e lascia l'allegato com'e': non e' un errore bloccante.
FFMPEG_BIN = os.environ.get('FFMPEG_BIN', 'ffmpeg')

# Limite sul totale di un caricamento a pezzi (file Holter grezzi, clip eco).
UPLOAD_MAX_BYTE = int(os.environ.get('UPLOAD_MAX_BYTE', 300 * 1024 * 1024))
# Limite per un allegato caricato in una POST singola (PDF, immagini).
ALLEGATO_MAX_BYTE = int(os.environ.get('ALLEGATO_MAX_BYTE', 50 * 1024 * 1024))
# Limite per una clip eco (filmato di una proiezione). Si chiedono filmati di
# massimo 10 secondi; senza ffmpeg la durata non si misura, quindi il
# freno e' il peso: 100 MB bastano per 10 s anche in DICOM poco compresso.
ECO_CLIP_MAX_BYTE = int(os.environ.get('ECO_CLIP_MAX_BYTE', 100 * 1024 * 1024))

# ── Dettatura vocale: «Ripulisci» con l'AI (consulti/dettatura.py) ───────────
# Il riconoscimento vocale e' quello del BROWSER (gratis, l'audio non esce dal
# computer del collega): all'API va SOLO il testo, per la forma. Senza chiave
# in ANTHROPIC_API_KEY, o con CONSULTI_DETTATURA_AI=False, il pulsante
# «Ripulisci» non compare e il microfono funziona comunque.
CONSULTI_DETTATURA_AI = os.environ.get('CONSULTI_DETTATURA_AI', 'True') == 'True'
# Claude Sonnet 5 e non Opus 5 (il modello dello smistamento): qui non ci sono
# immagini ne' giudizio clinico — punteggiatura, sigle e unita' di misura su
# poche righe — e il collega aspetta davanti allo schermo, quindi contano
# latenza e costo ($ 2/$ 10 per milione di token contro $ 5/$ 25: una
# ripulitura sta sotto il decimo di centesimo). Il rischio di un modello piu'
# piccolo e' diverso da quello dello smistamento: la' un «sicuro» sbagliato
# puo' sfuggire, qui il collega rilegge il proprio testo e ha «Annulla
# ripulitura». Da confermare ad Andre dopo la prova sul campo.
CONSULTI_MODELLO_DETTATURA = os.environ.get('CONSULTI_MODELLO_DETTATURA', 'claude-sonnet-5')
CONSULTI_DETTATURA_EFFORT = os.environ.get('CONSULTI_DETTATURA_EFFORT', 'low')
CONSULTI_DETTATURA_TIMEOUT = float(os.environ.get('CONSULTI_DETTATURA_TIMEOUT', '60'))

# ── Smistamento automatico dei file dell'eco (eco/smistamento/) ──────────────
# La lettura AI delle miniature usa l'API Anthropic con la chiave in
# ANTHROPIC_API_KEY (ambiente; MAI nel repo). Senza chiave, o con
# CONSULTI_SMISTAMENTO_AI=False, lo smistamento si ferma a formato e colore
# e le righe le sceglie chi carica.
CONSULTI_SMISTAMENTO_AI = os.environ.get('CONSULTI_SMISTAMENTO_AI', 'True') == 'True'
# Modello con visione: Claude Opus 5. Misure e costi per esame sul banco di
# prova: `manage.py valuta_smistamento` (docstring del comando e docs/BACKLOG.md).
CONSULTI_MODELLO_SMISTAMENTO = os.environ.get('CONSULTI_MODELLO_SMISTAMENTO', 'claude-opus-5')
CONSULTI_SMISTAMENTO_EFFORT = os.environ.get('CONSULTI_SMISTAMENTO_EFFORT', 'medium')
# Tempo massimo per una richiesta all'API (8 miniature con il ragionamento
# del modello possono volere piu' di un minuto; lo smistamento gira in un
# thread e la pagina aspetta con htmx, quindi si puo' essere larghi).
CONSULTI_SMISTAMENTO_TIMEOUT = float(os.environ.get('CONSULTI_SMISTAMENTO_TIMEOUT', '180'))
# Frazione dell'altezza tolta in alto alla miniatura prima di mandarla all'AI
# (intestazione dell'ecografo: nome del paziente, codice). 0 = niente taglio.
CONSULTI_SMISTAMENTO_TAGLIO_ALTO = float(os.environ.get('CONSULTI_SMISTAMENTO_TAGLIO_ALTO', '0.08'))
CONSULTI_SMISTAMENTO_PER_RICHIESTA = 8          # miniature per richiesta all'API
# Esemplari: l'immagine di riferimento di ogni riga viaggia con la richiesta
# (prefisso in cache), cosi' il modello confronta invece di leggere solo la
# descrizione. SPENTO: misurato sul banco (3 semi, 12/09/2026) non migliora la
# riga giusta (10,3 -> 10,7 su 17, dentro il rumore), fa dire «sconosciuto» la
# meta' delle volte ma sbaglia di piu' (2,7 -> 5,0 file messi nella riga
# sbagliata) e costa il 30 % in piu'. Il codice resta: si riaccende qui e si
# rimisura con `manage.py valuta_smistamento --esemplari si`.
CONSULTI_SMISTAMENTO_ESEMPLARI = os.environ.get('CONSULTI_SMISTAMENTO_ESEMPLARI', 'False') == 'True'
CONSULTI_SMISTAMENTO_ESEMPLARI_PX = int(os.environ.get('CONSULTI_SMISTAMENTO_ESEMPLARI_PX', '320'))
CONSULTI_SMISTAMENTO_IN_THREAD = True           # i test lo spengono (conftest.py)
# Prezzi in dollari per milione di token (ingresso, uscita), per la stima del
# costo nella telemetria. Da aggiornare se cambiano i listini.
CONSULTI_PREZZI_MODELLI = {
    'claude-opus-5': (5.0, 25.0),
    'claude-sonnet-5': (2.0, 10.0),
    'claude-haiku-4-5': (1.0, 5.0),
}

# Django usa il tag 'error', Bootstrap la classe 'danger': senza questa
# mappatura il messaggio di errore e' invisibile.
from django.contrib.messages import constants as _msg  # noqa: E402
MESSAGE_TAGS = {_msg.ERROR: 'danger'}

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'},
    },
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {name} {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'level': 'DEBUG',
        },
        'mail_admins': {
            'class': 'django.utils.log.AdminEmailHandler',
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'include_html': True,
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / 'consulti.log'),
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
            'level': 'INFO',
        },
    },
    'loggers': {
        'consulti': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'accounts': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'notifiche': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'referti': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'registro': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'eco': {'handlers': ['console', 'file'], 'level': 'INFO', 'propagate': False},
        'django.request': {
            'handlers': ['console', 'file', 'mail_admins'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
