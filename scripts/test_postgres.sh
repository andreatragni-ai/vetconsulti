#!/bin/bash
# Suite di test contro Postgres locale con i settings di PRODUZIONE.
# Sqlite (dev) perdona vincoli e tipi che Postgres rifiuta: prima di un
# deploy la suite va fatta girare anche qui. Prima volta: `createdb consulti_dev`.
# Postgres locale (Homebrew) e' la 14 mentre il server ha la 16: per i test
# basta e avanza, ma non e' identico.
#
# Uso: scripts/test_postgres.sh            (tutta la suite)
#      scripts/test_postgres.sh consulti   (una sola app, o qualsiasi arg di pytest)

set -e
cd "$(dirname "$0")/.."

export DJANGO_SECRET_KEY="chiave-solo-per-i-test-locali-0123456789abcdefghijklmnopqrstuvwxyz"
export DJANGO_ALLOWED_HOSTS="localhost"
export DJANGO_DB_NAME="${DJANGO_DB_NAME:-consulti_dev}"
export DJANGO_DB_USER="${DJANGO_DB_USER:-$USER}"
export DJANGO_DB_PASSWORD="${DJANGO_DB_PASSWORD:-x}"   # Homebrew: auth trust, ignorata
export DJANGO_DB_HOST="${DJANGO_DB_HOST:-localhost}"
export EMAIL_HOST_USER="x"
export EMAIL_HOST_PASSWORD="x"
export CONSULTI_BASE_URL="http://localhost"

exec venv/bin/python -m pytest --ds=config.settings.prod -p no:cacheprovider "$@"
