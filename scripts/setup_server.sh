#!/bin/bash
# ============================================================================
# setup_server_kms.sh  —  dipasang di SERVER PRODUCTION (103.25.223.5)
# KMS Invoicing native: PostgreSQL db sendiri, systemd, nginx reverse proxy.
# Idempotent (aman diulang). Jalankan sebagai user login biasa, sudo dipakai
# hanya untuk apt/systemctl/nginx/psql postgres.
#
# Arsitektur port:
#   gunicorn  -> 127.0.0.1:8012   (HANYA lokal, tidak bisa diakses dari luar)
#   nginx     -> 0.0.0.0:8013     (publik, IP-only, tanpa domain/HTTPS)
# ============================================================================
set -euo pipefail

APP_DIR=/home/rifsanserver/kms-invoicing
APP_USER=rifsanserver
APP_PORT=8012          # gunicorn (lokal saja)
PUBLIC_PORT=8013       # nginx (publik) - pastikan belum dipakai aplikasi lain

DB_NAME=kms_invoicing  # JANGAN pakai db `kms` (KMS lama) atau db ERP
DB_USER=kms_inv
DB_HOST=127.0.0.1
DB_PORT=5432

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "=== 0/7 Prasyarat ==="
command -v uv >/dev/null 2>&1 || { echo "Install uv dulu: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
sudo -u postgres psql -tAc "select 1" >/dev/null || { echo "Butuh akses sudo -u postgres"; exit 1; }
ss -tln | grep -qE ":${PUBLIC_PORT} " && { echo "PORT ${PUBLIC_PORT} sudah dipakai! Ganti PUBLIC_PORT."; exit 1; }
ss -tln | grep -qE ":${APP_PORT} " && { echo "PORT ${APP_PORT} sudah dipakai! Ganti APP_PORT."; exit 1; }

echo "=== 1/7 Paket sistem ==="
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip postgresql-client nginx

echo "=== 2/7 Role & database PostgreSQL (terpisah) ==="
if sudo -u postgres psql -tAc "select 1 from pg_database where datname='${DB_NAME}'" | grep -q 1; then
  echo "    DB ${DB_NAME} sudah ada — dilewati (tidak dihapus)."
else
  DB_PASS=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
  END IF;
END
\$\$;
CREATE DATABASE ${DB_NAME} OWNER ${DB_USER} ENCODING 'UTF8';
SQL
  echo "$DB_PASS" > "$APP_DIR/.db_password"
  chmod 600 "$APP_DIR/.db_password"
  echo "    Password DB disimpan di $APP_DIR/.db_password"
  DB_PASS=""
fi

echo "=== 3/7 Direktori & virtualenv ==="
mkdir -p "$APP_DIR"/{private_uploads,logs,backups}
[ -d "$APP_DIR/.venv" ] || (cd "$APP_DIR" && uv venv .venv --python 3.10)
(cd "$APP_DIR" && uv pip install --python .venv/bin/python -r requirements.txt)

echo "=== 4/7 .env.production ==="
# Isi manual dulu di .env.production.template bila ingin password tetap sama.
if [ -f "$APP_DIR/.env.production" ]; then
  echo "    .env.production sudah ada — dilewati."
else
  LOCAL_IP=$(hostname -I | awk '{print $1}')
  SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
  DBP=$(cat "$APP_DIR/.db_password" 2>/dev/null || echo "ISI_PASSWORD_DB")
  cat > "$APP_DIR/.env.production" <<EOF
DEBUG=0
SECRET_KEY=${SECRET}
POSTGRES_DB=${DB_NAME}
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${DBP}
POSTGRES_HOST=${DB_HOST}
POSTGRES_PORT=${DB_PORT}
ALLOWED_HOSTS=103.25.223.5,${LOCAL_IP},localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://103.25.223.5:${PUBLIC_PORT},http://${LOCAL_IP}:${PUBLIC_PORT}
CONN_MAX_AGE=30
SECURE_SSL_REDIRECT=0
SESSION_COOKIE_SECURE=0
CSRF_COOKIE_SECURE=0
EOF
  chmod 600 "$APP_DIR/.env.production"
fi

echo "=== 5/7 systemd (system-level, pola galon.service) ==="
sudo tee /etc/systemd/system/kms-invoicing.service > /dev/null <<EOF
[Unit]
Description=KMS Invoicing (Django + Gunicorn)
Documentation=file://${APP_DIR}/INSTALL-NOTES.md
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONDONTWRITEBYTECODE=1"
EnvironmentFile=${APP_DIR}/.env.production
ExecStart=${APP_DIR}/.venv/bin/gunicorn config.wsgi:application \\
  --bind 127.0.0.1:${APP_PORT} \\
  --workers 2 --threads 2 --timeout 90 --graceful-timeout 30 \\
  --access-logfile ${APP_DIR}/logs/gunicorn-access.log \\
  --error-logfile ${APP_DIR}/logs/gunicorn-error.log
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
echo "    (service belum dijalankan; jalankan setelah migrate — langkah 7)"

echo "=== 6/7 nginx reverse proxy (IP-only, tanpa SSL) ==="
sudo tee /etc/nginx/sites-available/kms-invoicing > /dev/null <<EOF
server {
    listen ${PUBLIC_PORT};
    server_name _;
    client_max_body_size 12m;

    location /static/ {
        alias ${APP_DIR}/staticfiles/;
        access_log off;
        expires 7d;
    }
    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/kms-invoicing /etc/nginx/sites-enabled/kms-invoicing
# WAJIB: tes dulu sebelum reload, karena nginx error = SEMUA situs di server ikut down
if sudo nginx -t; then
  sudo systemctl reload nginx
  echo "    nginx reload OK"
else
  echo "    !!! nginx -t GAGAL — reload DIBATALKAN (situs lain aman). Perbaiki konfigurasi."
  exit 1
fi

echo "=== 7/7 Migrasi, static, start service ==="
cd "$APP_DIR"
set -a; . ./.env.production; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_roles
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl daemon-reload
sudo systemctl enable --now kms-invoicing
sleep 3
sudo systemctl is-active kms-invoicing
curl -s -o /dev/null -w "cek lokal  gunicorn :${APP_PORT} -> %{http_code}\n" "http://127.0.0.1:${APP_PORT}/"
curl -s -o /dev/null -w "cek publik nginx    :${PUBLIC_PORT} -> %{http_code}\n" "http://127.0.0.1:${PUBLIC_PORT}/"

echo ""
echo "SELESAI. Akses: http://103.25.223.5:${PUBLIC_PORT}/"
echo "Buat admin: cd $APP_DIR && set -a && . ./.env.production && set +a && .venv/bin/python manage.py createsuperuser"
