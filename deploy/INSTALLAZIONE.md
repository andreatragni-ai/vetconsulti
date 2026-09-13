# Installazione una tantum sul server (consulti.vetway.it)

Stesso server di VetCardio (Ubuntu, nginx, Postgres 16, Certbot), raggiunto
via WireGuard su `10.10.0.1`. Tutto cio' che segue si fa **una volta**; i
deploy successivi sono `./deploy/deploy.sh`.

## 1. DNS

Record `A` per `consulti.vetway.it` → `167.233.170.45` (lo stesso di
`vetway.it` e `anest.vetway.it`), dal pannello di register.it (i DNS di
vetway.it stanno li'). Aspettare la propagazione prima di Certbot
(`dig +short consulti.vetway.it`).

## 2. Utente di sistema e cartelle

```bash
adduser --system --group --home /home/consulti --shell /bin/bash consulti
mkdir -p /home/consulti/app /home/consulti/vetway-ui /home/consulti/backup /etc/consulti
chown -R consulti:consulti /home/consulti
apt install -y python3-venv python3-dev libpq-dev ffmpeg \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0   # WeasyPrint
# Verificato il 13/09/2026: sul server mancavano solo ffmpeg (clip eco) e
# libharfbuzz-subset0; il resto c'era gia' per VetCardio e VetAnest.
```

## 3. Variabili d'ambiente

```bash
cp deploy/env.example /etc/consulti/env
cp deploy/secrets.env.example /etc/consulti/secrets.env
chown root:consulti /etc/consulti/*.env
chmod 640 /etc/consulti/*.env
# compilare secrets.env: DJANGO_SECRET_KEY, DJANGO_DB_PASSWORD, EMAIL_HOST_USER/PASSWORD,
# ANTHROPIC_API_KEY. Con `set -a; . file` i valori con spazi vanno fra virgolette.
```

## 4. Database Postgres 16 (locale)

```bash
sudo -u postgres psql <<'SQL'
CREATE USER consulti WITH PASSWORD '<la stessa di DJANGO_DB_PASSWORD>';
CREATE DATABASE consulti_db OWNER consulti ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8' TEMPLATE template0;
SQL
```

`en_US.UTF-8` come vetcardio_db e vetanest_db: il locale `it_IT` sul server
non e' installato e il CREATE fallirebbe. L'ordinamento alfabetico dei nomi
italiani non cambia in modo visibile.

## 5. Primo deploy e superuser

Il portale usa il pacchetto grafico condiviso `vetway-ui`, che sul Mac sta
nel repo fratello `../vetway-ui`. `deploy.sh` lo copia in
`/home/consulti/vetway-ui` (step 1b) e lo installa nel venv con
`pip install -e` prima di `migrate` (step 2): senza, gunicorn non parte
(`ModuleNotFoundError: vetway_ui`). In `requirements.txt` la riga del
pacchetto resta commentata finche' non c'e' un repo raggiungibile dal server.

```bash
./deploy/deploy.sh          # dal Mac: rsync app + vetway-ui, venv, migrate, collectstatic
ssh root@10.10.0.1
cd /home/consulti/app
set -a; . /etc/consulti/env; . /etc/consulti/secrets.env; set +a
DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@vetway.it \
DJANGO_SUPERUSER_PASSWORD='<password>' \
sudo -E -u consulti venv/bin/python manage.py createsuperuser --noinput
sudo -E -u consulti venv/bin/python manage.py carica_catalogo_eco
```

Il listino parte vuoto: senza un prezzo per tipo di esame un referto non si
firma. Si compila da **Gestione → Listino** entrando come admin (un prezzo
nuovo puo' partire da oggi). I refertatori si aggiungono da
**Gestione → Refertatori**: ricevono l'invito per email.

## 6. systemd

```bash
cp deploy/gunicorn-consulti.socket deploy/gunicorn-consulti.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gunicorn-consulti.socket gunicorn-consulti.service
systemctl status gunicorn-consulti
```

## 7. nginx e certificato

Nel blocco `http` di `/etc/nginx/nginx.conf` devono esistere le zone di
rate limit (se VetCardio e' sullo stesso server ci sono gia'):

```nginx
limit_req_zone $binary_remote_addr zone=vw_login:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=vw_reset:10m rate=3r/m;
limit_req_status 429;
```

Poi:

```bash
cp deploy/nginx-consulti.conf /etc/nginx/sites-available/consulti
# Prima di Certbot commentare temporaneamente il blocco `listen 443 ssl` e le
# righe ssl_*, e il secondo blocco server (il redirect): senza certificato
# `nginx -t` fallisce e il reload lascerebbe giu' anche VetCardio e VetAnest.
# Certbot le riscrive lui.
ln -s /etc/nginx/sites-available/consulti /etc/nginx/sites-enabled/consulti
nginx -t && systemctl reload nginx
certbot --nginx -d consulti.vetway.it
```

Attenzione: nginx carica **tutti** i file in `sites-enabled/`, anche i
backup. I backup vanno altrove.

## 8. Cron

Crontab dell'utente `consulti` (`crontab -u consulti -e`):

```cron
# Rilascia le prese in carico ferme oltre CONSULTI_ORE_PRESA_IN_CARICO
0 * * * * cd /home/consulti/app && set -a && . /etc/consulti/env && . /etc/consulti/secrets.env && set +a && venv/bin/python manage.py sorveglia_consulti >> logs/cron.log 2>&1

# Backup notturno del database e dei media (7 giorni di rotazione)
0 3 * * * pg_dump -Fc consulti_db > /home/consulti/backup/consulti_db_$(date +\%F).dump && tar czf /home/consulti/backup/media_$(date +\%F).tgz -C /home/consulti/app media && find /home/consulti/backup -mtime +7 -delete
```

Per `pg_dump` senza password: `~consulti/.pgpass` con
`localhost:5432:consulti_db:consulti:<password>` e `chmod 600`.

## 9. Verifica

```bash
curl -I https://consulti.vetway.it/accedi/          # 200
curl -I https://consulti.vetway.it/_media_interno/x # 404 (internal)
tail -f /home/consulti/app/logs/consulti.log
```
