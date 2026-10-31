# Deploy KMS Invoicing — PRODUCTION (native, IP-only)

**Server**: 103.25.223.5 (Ubuntu 24.04, Apache2, root)
**Status**: ✅ TERPASANG & BERJALAN
**Akses**: http://103.25.223.5:8013/

---

## Ringkasan arsitektur

```
Internet/LAN
    |
    v
Apache2 :8013  (vhost /etc/apache2/sites-available/kms-invoicing.conf)
    |  /static/  -> /opt/kms-invoicing/staticfiles/  (langsung Apache)
    |  lainnya   -> proxy 127.0.0.1:8012
    v
gunicorn :8012  (systemd: kms-invoicing.service, 2 worker x 2 thread)
    |
    v
PostgreSQL 18.3 :5433  (cluster terpisah "18/kms", DB kms_invoicing)
```

**PENTING — isolasi dari aplikasi lain di server yang sama:**

| Aplikasi | Port | Database | Keterangan |
|---|---|---|---|
| KMS Invoicing (ini) | 8013 / 8012 | `kms_invoicing` @ PG18:5433 | TERISOLASI |
| HRIS API | 8000 | — | tidak tersentuh |
| ERP | (server lain) | `kp2` @ PG12:5432 | **TIDAK DISENTUH** |
| erp-wa-gateway | 3020 | — | tidak tersentuh |
| Webmin | 10000 | — | tidak tersentuh |
| Apache default | 80 | — | tidak tersentuh |

PostgreSQL 12 (port 5432) tetap apa adanya — dipakai ERP (`kp2`). KMS pakai cluster PG18 baru di port 5433.

---

## Kredensial

| Item | Nilai | Lokasi |
|---|---|---|
| Login aplikasi | `admin` / lihat file | `/root/.kms_admin_password` |
| DB app user | `kms_inv` | `/opt/kms-invoicing/.env.production` |
| DB password | — | `/opt/.kms_db_password` |
| SECRET_KEY | — | `/opt/kms-invoicing/.env.production` |

Semua file di atas `chmod 600`.

---

## Perintah operasional (di prod)

```bash
# status & log
systemctl status kms-invoicing
journalctl -u kms-invoicing -f
tail -f /opt/kms-invoicing/logs/gunicorn-error.log

# restart / reload
systemctl restart kms-invoicing
systemctl reload kms-invoicing      # graceful

# database
pg_lsclusters                        # cek cluster 12/main :5432 dan 18/kms :5433
su - postgres -c "psql -p 5433 -d kms_invoicing"   # masuk psql DB KMS

# Django
cd /opt/kms-invoicing
set -a && . ./.env.production && set +a
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py changepassword admin
```

---

## Backup & restore

```bash
# backup DB KMS (tidak menyentuh PG12/ERP)
cd /opt/kms-invoicing
set -a && . ./.env.production && set +a
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -p 5433 -U kms_inv -d kms_invoicing \
  -Fc -f /opt/kms-invoicing/backups/kms-$(date +%F-%H%M).dump

# backup lampiran
tar czf /opt/kms-invoicing/backups/evidence-$(date +%F-%H%M).tar.gz \
  -C /opt/kms-invoicing private_uploads

# RESTORE
set -a && . ./.env.production && set +a
PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -h 127.0.0.1 -p 5433 -U kms_inv -d kms_invoicing \
  --clean --if-exists --no-owner --no-acl backups/kms-XXXX.dump
```

**Setelah restore**, pastikan kepemilikan tabel kembali ke `kms_inv`:
```bash
su - postgres -c "psql -p 5433 -d kms_invoicing -c \"
DO \\\$\\\$ DECLARE r record; BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO kms_inv', r.tablename); END LOOP;
  FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname='public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO kms_inv', r.sequencename); END LOOP;
END \\\$\\\$;\""
```

---

## Update kode (dari GitHub)

```bash
cd /opt/kms-invoicing
git pull
set -a && . ./.env.production && set +a
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py collectstatic --noinput
systemctl restart kms-invoicing
```

---

## Catatan penting

1. **Akses via HTTP tanpa TLS.** Karena tanpa domain/HTTPS, `SESSION_COOKIE_SECURE`,
   `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS` dimatikan di `.env.production`.
   Artinya password terkirim tanpa enkripsi. **Rekomendasi**: aktifkan HTTPS bila
   sudah ada domain, atau batasi akses via firewall ke IP kantor saja.
2. **UFW aktif** dengan policy DROP. Port 8013 sudah diizinkan. Untuk membatasi,
   ganti rule menjadi: `ufw delete allow 8013/tcp && ufw allow from <IP_KANTOR> to any port 8013`.
3. **Jangan `ufw disable`** atau `systemctl restart postgresql` — itu akan mematikan
   ERP/HRIS juga.
4. **Jangan menyentuh** `/etc/postgresql/12/` atau database `kp2` — milik ERP.
5. File `INSTALL-NOTES.md` di repo menggambarkan setup dev (Docker era). Dokumen ini
   adalah acuan untuk prod.

---

## Yang perlu dilengkapi nanti

- [ ] Restore data master (barang, supplier, harga) — DB sekarang kosong
- [ ] Ganti password admin (`/root/.kms_admin_password` → password pilihan sendiri)
- [ ] Pertimbangkan HTTPS (butuh domain) atau batasi UFW ke IP kantor
- [ ] Backup otomatis harian (cron)
