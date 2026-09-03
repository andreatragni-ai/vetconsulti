"""
Produzione: tutto cio' che e' segreto o dipende dal server arriva
dall'ambiente. Il servizio systemd carica /etc/consulti/env e
/etc/consulti/secrets.env (vedi deploy/env.example e secrets.env.example).
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403


def _obbligatoria(nome):
    valore = os.environ.get(nome, '').strip()
    if not valore:
        raise ImproperlyConfigured(f'Variabile d\'ambiente {nome} mancante.')
    return valore


DEBUG = False
SECRET_KEY = _obbligatoria('DJANGO_SECRET_KEY')
ALLOWED_HOSTS = [h.strip() for h in _obbligatoria('DJANGO_ALLOWED_HOSTS').split(',') if h.strip()]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DJANGO_DB_NAME', 'consulti_db'),
        'USER': os.environ.get('DJANGO_DB_USER', 'consulti'),
        'PASSWORD': _obbligatoria('DJANGO_DB_PASSWORD'),
        'HOST': os.environ.get('DJANGO_DB_HOST', 'localhost'),
        'PORT': os.environ.get('DJANGO_DB_PORT', '5432'),
        # Ogni worker gunicorn tiene al massimo una connessione viva: con due
        # worker si resta lontanissimi dal max_connections di Postgres.
        'CONN_MAX_AGE': 60,
    }
}

# ── Dietro nginx ─────────────────────────────────────────────────────────────
# nginx termina il TLS e parla a gunicorn su socket unix; proxy_params
# imposta X-Forwarded-Proto sovrascrivendo cio' che manda il client, quindi
# fidarsi dell'header e' sicuro finche' gunicorn resta su socket e non su
# una porta TCP raggiungibile.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in ALLOWED_HOSTS if not h.startswith('.')]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_CONTENT_TYPE_NOSNIFF = True

# ── Posta SMTP ───────────────────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'authsmtp.securemail.pro')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False') == 'True'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '').strip()
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '').strip()
EMAIL_TIMEOUT = 20

CONSULTI_BASE_URL = os.environ.get('CONSULTI_BASE_URL', 'https://consulti.vetway.it')

# ── Storage S3 (Hetzner Object Storage) — predisposto, non attivo ────────────
# Per spostare gli allegati su S3 basta valorizzare le variabili qui sotto e
# togliere il commento al blocco. Attenzione: la view scarica_allegato con
# X-Accel-Redirect presuppone file su disco locale; con S3 va sostituita da
# un redirect a URL firmato (storage.url(nome) con querystring a scadenza).
#
# if os.environ.get('S3_BUCKET'):
#     STORAGES['default'] = {  # noqa: F405
#         'BACKEND': 'storages.backends.s3.S3Storage',
#         'OPTIONS': {
#             'bucket_name': os.environ['S3_BUCKET'],
#             'endpoint_url': os.environ.get('S3_ENDPOINT', 'https://fsn1.your-objectstorage.com'),
#             'access_key': os.environ['S3_ACCESS_KEY'],
#             'secret_key': os.environ['S3_SECRET_KEY'],
#             'region_name': os.environ.get('S3_REGION', 'fsn1'),
#             'default_acl': 'private',
#             'querystring_auth': True,
#             'querystring_expire': 600,
#             'file_overwrite': False,
#         },
#     }
