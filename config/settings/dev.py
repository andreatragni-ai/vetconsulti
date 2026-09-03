"""Sviluppo locale: sqlite, DEBUG, email stampate in console."""

from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = 'chiave-di-sviluppo-non-usare-in-produzione'
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_dev.sqlite3',  # noqa: F405
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Link nelle email: il runserver locale.
CONSULTI_BASE_URL = os.environ.get('CONSULTI_BASE_URL', 'http://localhost:8000')  # noqa: F405
