# Catatan Instalasi KMS Invoicing — NATIVE (tanpa Docker)

Lokasi app : /home/rifsanserver/kms-invoicing
Versi paket: /srv/sambashare/KMS-Django-PostgreSQL-V1.5.zip
             (README internal: "V1.6 · Tabel Ringkas, Status & Filter Bulanan")
Status     : Docker SUDAH DIHAPUS (container, image, volume, compose.yaml, Dockerfile).
             Deploy native: venv + gunicorn + systemd user service + PostgreSQL host.

## Akses aplikasi

- URL lokal : http://127.0.0.1:8002/
- URL LAN   : http://192.168.100.116:8002/
- Superuser : admin / kPOvtnxO6mx6iw
- Operator  : admin.operasional / 4COT5Z4ev01lIw   (grup Admin Operasional)

## Database (PostgreSQL host, bukan Docker)

- Server   : 127.0.0.1:5432  (PostgreSQL 18.6, service `postgresql`)
- Database : kms_invoicing      <-- KHUSUS aplikasi ini
- Role     : kms_inv (owner semua tabel)
- Password : lihat .env (POSTGRES_PASSWORD)

PENTING: database `kms` di host yang sama adalah milik proyek KMS LAMA
(repo apps/ modular, 38 tabel, 13 MB). JANGAN ditimpa/dihapus.

## Service (systemd user, tanpa sudo)

    systemctl --user status kms-invoicing
    systemctl --user restart kms-invoicing
    systemctl --user stop kms-invoicing
    journalctl --user -u kms-invoicing -f        # log
    systemctl --user enable|disable kms-invoicing

Unit: /home/rifsanserver/.config/systemd/user/kms-invoicing.service
Linger=yes → service tetap hidup setelah logout dan start saat boot.
Gunicorn: 0.0.0.0:8002, 2 worker, timeout 120.

## Perintah harian (dari /home/rifsanserver/kms-invoicing)

    .venv/bin/python manage.py migrate
    .venv/bin/python manage.py collectstatic --noinput
    .venv/bin/python manage.py shell
    .venv/bin/python manage.py seed_dummy --orders 60     # data dummy (file lokal, bukan dari paket)
    systemctl --user restart kms-invoicing

Venv: .venv (Python 3.10.12, dibuat dengan `uv venv`; python3 host tanpa pip).

## Backup & restore

Backup (tanpa perlu password postgres):

    cd /home/rifsanserver/kms-invoicing
    .venv/bin/python - <<'PY'
    import os, subprocess, datetime, dotenv
    dotenv.load_dotenv('.env')
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    env = dict(os.environ, PGPASSWORD=os.environ['POSTGRES_PASSWORD'])
    out = f'backups/kms-native-{ts}.dump'
    subprocess.run(['pg_dump','-h','127.0.0.1','-p','5432','-U',os.environ['POSTGRES_USER'],
                    '-d',os.environ['POSTGRES_DB'],'-Fc','-f',out], env=env, check=True)
    print(out)
    PY

Backup lampiran:

    tar czf backups/evidence-$(date +%F-%H%M).tar.gz private_uploads

Restore (kosongkan dulu tabel aplikasi, atau buat DB baru):

    PGPASSWORD=<pw> pg_restore -h 127.0.0.1 -U kms_inv -d kms_invoicing \
      --clean --if-exists --no-owner --no-acl backups/<file>.dump

Setelah restore, PASTIKAN kepemilikan tabel & sequence kembali ke kms_inv
(restore bisa membuat objek milik role lain → INSERT gagal "permission denied"):

    PGPASSWORD=<pw_postgres> psql -h 127.0.0.1 -U postgres -d kms_invoicing <<'SQL'
    DO $$ DECLARE r record; BEGIN
      FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO kms_inv', r.tablename); END LOOP;
      FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname='public' LOOP
        EXECUTE format('ALTER SEQUENCE public.%I OWNER TO kms_inv', r.sequencename); END LOOP;
    END $$;
    SQL

## Mengosongkan transaksi (sisakan master saja)

Tabel master : core_partner, core_product, core_supplierprice, core_supplierproduct,
               core_invoiceprofile, core_invoicecounter, auth_user, auth_group
Tabel transaksi (boleh dikosongkan): core_procurement, core_orderitem, core_invoice,
               core_payment, core_ledgerentry, core_wallet, core_kitchenentry,
               core_attachment, core_financialevidence, core_auditevent

    PGPASSWORD=<pw> psql -h 127.0.0.1 -U kms_inv -d kms_invoicing <<'SQL'
    BEGIN;
    TRUNCATE core_ledgerentry, core_payment, core_invoice, core_procurement,
             core_orderitem, core_kitchenentry, core_attachment,
             core_financialevidence, core_wallet, core_auditevent
      RESTART IDENTITY CASCADE;
    INSERT INTO core_wallet (name) VALUES ('KMS') ON CONFLICT DO NOTHING;
    COMMIT;
    SQL
    rm -rf private_uploads/*      # opsional: hapus file lampiran

## Catatan penting

1. static/src/input.css (sumber Tailwind) TIDAK boleh ada saat collectstatic
   (ManifestStaticFilesStorage ikut @import "tailwindcss" yang tidak terpasang).
   Sudah dihapus dari folder static; kalau paket baru membawanya lagi, hapus dulu.
2. .env berisi SECRET_KEY & password DB (mode 600). .env.docker-backup = versi lama.
3. seed_dummy.py TIDAK ada di paket ZIP (buatan sendiri). Salinan:
   /home/rifsanserver/KMS-seed_dummy.py
4. Backup dump lama dari era Docker tetap ada di backups/ (termasuk
   kms-db-20261030-022746-FINAL-docker.dump = sumber data yang sekarang dipakai).
