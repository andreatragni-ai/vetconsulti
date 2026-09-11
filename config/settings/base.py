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
                'core.context_processors.navigazione',
                'core.context_processors.regole_password',
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
VERSIONE_PRIVACY = '2026-09-02'
VERSIONE_TERMINI = '2026-09-02'

# Binario ffmpeg per la transcodifica delle clip eco. Se manca, eco.transcodifica
# logga un avviso e lascia l'allegato com'e': non e' un errore bloccante.
FFMPEG_BIN = os.environ.get('FFMPEG_BIN', 'ffmpeg')

# Limite sul totale di un caricamento a pezzi (file Holter grezzi, clip eco).
UPLOAD_MAX_BYTE = int(os.environ.get('UPLOAD_MAX_BYTE', 300 * 1024 * 1024))
# Limite per un allegato caricato in una POST singola (PDF, immagini).
ALLEGATO_MAX_BYTE = int(os.environ.get('ALLEGATO_MAX_BYTE', 50 * 1024 * 1024))
# Limite per una clip eco (filmato di una proiezione). Si chiedono filmati di
# una decina di secondi; senza ffmpeg la durata non si misura, quindi il
# freno e' il peso: 100 MB bastano per 10 s anche in DICOM poco compresso.
ECO_CLIP_MAX_BYTE = int(os.environ.get('ECO_CLIP_MAX_BYTE', 100 * 1024 * 1024))

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
