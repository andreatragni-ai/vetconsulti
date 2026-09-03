#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
# Deploy VetWay Consulti → server di produzione (tunnel WireGuard 10.10.0.1)
# Uso: ./deploy/deploy.sh
#
# Sincronizza TUTTA la working copy (non app per app: e' stato il modo in cui
# VetCardio si e' trovata piu' volte con un settings nuovo e un'app mancante),
# con esclusioni esplicite per cio' che non deve MAI viaggiare: venv, git,
# database locale, media, log, segreti.
# ══════════════════════════════════════════════════════════════════════
set -e

SERVER="root@10.10.0.1"
REMOTE="/home/consulti/app"
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${YELLOW}═══ Deploy VetWay Consulti ═══${NC}"
echo "Locale: $LOCAL"
echo "Server: $SERVER:$REMOTE"
echo ""

# 0. Pre-volo: i test devono passare qui prima di toccare il server.
echo -e "${YELLOW}[0/5] Test locali...${NC}"
if ! (cd "$LOCAL" && venv/bin/python -m pytest -q); then
  echo -e "${RED}═══ Deploy abortito: test rossi ═══${NC}"
  exit 1
fi

# 1. Sync della working copy.
echo -e "${YELLOW}[1/5] Sync working copy...${NC}"
rsync -avz --delete \
  --exclude='venv/' \
  --exclude='.git/' \
  --exclude='.gitignore' \
  --exclude='db_dev.sqlite3' \
  --exclude='*.sqlite3' \
  --exclude='media/' \
  --exclude='staticfiles/' \
  --exclude='logs/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='.env' \
  --exclude='*.env' \
  --exclude='secrets.env' \
  --exclude='config/settings/local.py' \
  --exclude='.DS_Store' \
  --exclude='.claude/' \
  "$LOCAL/" "$SERVER:$REMOTE/"

# 1b. Sync pacchetto vetway-ui (strato grafico condiviso: template base, CSS,
#     vendor). Vive in un repo a parte, fratello di questo (../vetway-ui), e
#     sul server in /home/consulti/vetway-ui, installato nel venv in modalita'
#     editable nello step 2. Senza il pacchetto gunicorn non parte
#     (ModuleNotFoundError: vetway_ui), quindi va PRIMA di migrate/collectstatic.
echo -e "${YELLOW}[1b/5] Sync pacchetto vetway-ui...${NC}"
rsync -avz --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.egg-info' \
  --exclude='build/' \
  --exclude='.DS_Store' \
  "$LOCAL/../vetway-ui/" "$SERVER:/home/consulti/vetway-ui/"

# 2-4. Dipendenze, migrazioni, statici, permessi.
echo -e "${YELLOW}[2/5] Dipendenze, migrazioni, statici...${NC}"
ssh "$SERVER" "
  set -e
  cd $REMOTE
  [ -d venv ] || python3 -m venv venv
  venv/bin/pip install -q -r requirements.txt 2>&1 | tail -2
  # vetway-ui: dalla copia sincronizzata nello step 1b (requirements.txt lo
  # tiene commentato finche' non c'e' un repo raggiungibile dal server).
  venv/bin/pip install -q -e /home/consulti/vetway-ui 2>&1 | tail -2
  set -a; . /etc/consulti/env; . /etc/consulti/secrets.env; set +a
  # || exit 1 non e' pignoleria: un deploy che stampa 'completato' dopo una
  # migrazione fallita a meta' riavvia gunicorn su codice che si aspetta
  # colonne inesistenti (successo reale su VetCardio, 24/08/2026).
  venv/bin/python manage.py migrate --no-input 2>&1 || exit 1
  venv/bin/python manage.py collectstatic --noinput 2>&1 | tail -1
  mkdir -p media logs
  chown -R consulti:consulti $REMOTE /home/consulti/vetway-ui
"

# 5. Restart.
echo -e "${YELLOW}[5/5] Restart gunicorn-consulti...${NC}"
ssh "$SERVER" "systemctl restart gunicorn-consulti && systemctl is-active gunicorn-consulti"

echo ""
echo -e "${GREEN}═══ Deploy completato ═══${NC}"
