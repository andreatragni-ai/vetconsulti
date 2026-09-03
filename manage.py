#!/usr/bin/env python
"""Punto d'ingresso dei comandi Django. Di default parla con le settings di
sviluppo: in produzione il servizio systemd imposta DJANGO_SETTINGS_MODULE
esplicitamente a config.settings.prod (vedi deploy/env.example)."""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django non trovato: attiva il venv (source venv/bin/activate) "
            "o controlla che le dipendenze siano installate."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
