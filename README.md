# KMS Management System V1.7

Aplikasi pengadaan dan invoicing dengan alur **Supplier → KMS → Koperasi → Dapur**. Pengadaan baru berhenti di dapur. Tidak ada input harga, penerbitan invoice, atau perhitungan profit baru untuk Dapur → Kantor.

Stack: Django 5.2, PostgreSQL, Django Templates, HTMX, Tailwind CSS, Gunicorn dan WhiteNoise. CSS hasil build sudah disertakan; Node.js hanya diperlukan jika mengubah CSS.

## Perubahan V1.7

- Input pengadaan tetap dua tabel: seluruh barang/supplier/harga beli, lalu harga KMS → koperasi dan koperasi → dapur.
- Setelah Owner/Superadmin mengonfirmasi, terbit **satu tagihan untuk setiap supplier**, satu invoice KMS → koperasi, dan satu invoice koperasi → dapur. Dapur hanya mendapat satu invoice dari koperasi.
- Laporan utama menghitung omzet/profit KMS dan koperasi. Tidak menganggap penerimaan barang dapur sebagai omzet dapur. Omzet/profit KMS tetap khusus Owner/Superadmin.
- Ekspor pengadaan baru berhenti pada harga beli dapur dan total tagihan ke dapur. Kolom harga kantor, rekomendasi kantor dan profit dapur dihapus dari format baru.
- Invoice kantor lama tersedia lewat **Invoice Penjualan → Arsip invoice kantor lama**. Nomor, kop, harga, pembayaran, bukti, sisa tagihan dan akses cetaknya tetap dipertahankan. Arsip masih dapat dilunasi atau dibatalkan oleh role yang berwenang.
- Ekspor pengadaan lama mempertahankan format lama 13 kolom. Format baru memakai 11 kolom. Pengadaan baru tidak dapat menerbitkan invoice kantor, termasuk melalui fungsi penerbitan di server.
- Hak admin operasional, kas, bukti, pembatalan, filter bulan, warna status dan tabel ringkas dari V1.6 tetap digunakan.

## Persiapan Docker untuk instalasi baru

Pasang Docker Engine/Desktop dan Compose. Ekstrak paket, masuk ke folder yang memuat `manage.py` dan `compose.yaml`, kemudian:

```bash
python setup_local.py
docker compose up -d --build db
docker compose build web
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py setup_roles
docker compose run --rm web python manage.py collectstatic --noinput
docker compose run --rm web python manage.py createsuperuser
docker compose up -d web
```

Buka `http://127.0.0.1:8000`. Konfigurasi yang dibuat `setup_local.py` ditujukan untuk komputer lokal dan tidak menimpa `.env` yang sudah ada. Username/password Superadmin dibuat melalui `createsuperuser`, bukan akun bawaan.

Untuk server produksi: gunakan `DEBUG=0`, secret milik server, domain pada `ALLOWED_HOSTS`, origin HTTPS pada `CSRF_TRUSTED_ORIGINS`, HTTPS reverse proxy, dan header `X-Forwarded-Proto` yang ditetapkan oleh proxy terpercaya. Jangan memakai `runserver` sebagai server produksi.

## Memperbarui instalasi lama dengan Docker

Backup database dan lampiran terlebih dahulu. Pertahankan `.env`, nama project Compose dan volume data yang sama. Jangan menghapus volume database/lampiran. Hentikan web, salin kode baru, lalu jalankan:

```bash
docker compose stop web
docker compose build web
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py setup_roles
docker compose run --rm web python manage.py collectstatic --noinput
docker compose up -d web
```

**Migrasi 0011 wajib dijalankan sebelum membuka V1.7.** Migrasi menambah penanda alur pengadaan: transaksi lama yang sudah keluar dari status Draf ditandai sebagai arsip alur lama; draf lama menggunakan alur baru saat dilanjutkan. Tidak ada tabel, harga, nomor, invoice, pembayaran, saldo, kop, atau berkas bukti lama yang dihapus. Harga kantor yang sudah tersimpan pada draf lama tetap ada di database, tetapi tidak diminta/dipakai untuk penerbitan dokumen baru.

Paket ini juga memuat seluruh migrasi V1 sampai V1.6. Migrasi lama untuk pemulihan tagihan supplier dan kas hanya berlaku jika instalasi belum menjalankannya. Cocokkan hasil pemulihan terhadap dokumen asli sebagaimana dijelaskan pada arsip dokumentasi V1.6.

## Menjalankan tanpa Docker

Gunakan Python 3.12, PostgreSQL, virtual environment, Gunicorn dan Nginx. Salin `.env.example` menjadi `.env`, isi secret/domain/password database dan sesuaikan host PostgreSQL, lalu dari folder aplikasi:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_roles
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py check --deploy
```

Jalankan Gunicorn melalui service systemd dengan pengguna aplikasi, bukan root. Contoh target aplikasi adalah `config.wsgi:application`; bind hanya ke loopback, misalnya `127.0.0.1:8010`, lalu arahkan Nginx ke port itu dan pasang HTTPS. WhiteNoise melayani aset statis yang sudah dikumpulkan. Jangan memberi akses Nginx publik ke `private_uploads`; bukti disajikan lewat endpoint Django dengan pemeriksaan login.

Untuk instalasi non-Docker yang sebelumnya memakai service `/srv/kms/venv` dan folder `/srv/kms/app`, lakukan backup lalu hentikan service, salin kode baru tanpa menghapus `.env` dan `private_uploads`, kemudian:

```bash
sudo systemctl stop kms
cd /srv/kms/app
sudo -u kms /srv/kms/venv/bin/pip install -r requirements.txt
sudo -u kms /srv/kms/venv/bin/python manage.py migrate
sudo -u kms /srv/kms/venv/bin/python manage.py setup_roles
sudo -u kms /srv/kms/venv/bin/python manage.py collectstatic --noinput
sudo systemctl start kms
sudo systemctl status kms --no-pager
```

Sesuaikan path dan nama service bila berbeda. Pindah dari Docker ke instalasi native memerlukan pemindahan database serta isi volume bukti, bukan hanya menyalin kode.

## Pekerjaan operasional

1. Siapkan barang, satuan, supplier, koperasi dan dapur yang aktif. Gunakan pencarian agar tidak membuat master ganda.
2. Bandingkan harga lewat Katalog Supplier & Harga. Tersedia tampilan berdasarkan barang atau supplier, harga terakhir dan histori. Tambahkan penawaran baru tanpa menimpa histori lama.
3. Buat pengadaan: koperasi, dapur tujuan, tanggal pengiriman dan catatan. Nama kantor penerima tidak diminta lagi.
4. Isi seluruh barang, jumlah, supplier dan harga beli per satuan. Pilih penawaran atau harga manual yang benar, lalu simpan draf atau lanjut. Maksimal 200 baris.
5. Isi harga KMS → koperasi dan koperasi → dapur untuk seluruh barang. Semua harga jual harus positif saat pemeriksaan akhir. Admin Operasional boleh mengisi kedua harga. Simpan/kembali menyimpan draf; tidak menerbitkan invoice.
6. Owner memeriksa lalu mengonfirmasi. Harga, nama, satuan, nomor dan kop dokumen dibekukan. Konfirmasi tidak dapat dilakukan admin operasional.
7. Tandai dikirim dan diterima sesuai kejadian. Setelah **Diterima dapur**, tombol ekspor pengadaan Excel/PDF tersedia. Penerimaan barang tidak berarti tagihan lunas.
8. Catat pembayaran dan bukti melalui invoice yang sesuai. Gunakan mutasi manual hanya untuk transaksi di luar pembayaran invoice.

Panduan rinci Admin Operasional V1.7 disertakan pada folder `docs`.

## Pembayaran kas dan pembatalan

- Pembayaran supplier mengurangi kas KMS. Pembayaran koperasi pada invoice KMS menambah kas KMS. Pembayaran dapur pada invoice koperasi tidak mengubah kas KMS. Pembayaran arsip kantor lama juga tidak mengubah kas KMS.
- Kas KMS dapat dilihat dan dicatat oleh Owner/Superadmin dan Admin Operasional. Nominal pembayaran tidak boleh melebihi sisa tagihan; uang keluar tidak boleh melebihi saldo. Tanggal pembayaran/mutasi tidak boleh di masa depan.
- Aplikasi mencatat uang yang telah berpindah; tidak melakukan transfer bank. Jangan mencatat ulang pembayaran invoice sebagai mutasi manual.
- Hanya Owner/Superadmin yang boleh menghapus baris draf tersimpan atau membatalkan pembayaran, mutasi dan pengadaan. Pembatalan dilakukan lewat menu tiga titik atau Kelola pengadaan, diikuti alasan. Data dan bukti tetap tersimpan.
- Pembatalan pembayaran membatalkan mutasi terkait dan memperbarui sisa tagihan secara atomik. Pengadaan yang masih memiliki pembayaran aktif harus diselesaikan pembatalan pembayarannya terlebih dahulu. Pembatalan pemasukan ditolak jika membuat saldo negatif.
- Invoice kantor lama tidak dipindahkan ke invoice koperasi dan tidak diubah totalnya. Gunakan nomor arsip lama untuk pelunasan atau penelusuran agar tidak menggandakan transaksi.

## Bukti laporan dan filter

- Foto JPG/PNG sumber maksimal 5 MB dioptimasi hingga maksimal 300 KB. PDF maksimal 1 MB dan tidak dikompres otomatis. Foto asli unggahan baru tidak disimpan setelah optimasi.
- Daftar menampilkan data dan ikon mata, tanpa thumbnail. Nama unduhan mengikuti tanggal dan transaksi. Bukti tetap privat dan memerlukan login.
- Unduh bukti per tanggal menghasilkan ZIP dan `daftar-bukti.csv`. Tanggal pembayaran mengikuti tanggal bayar, mutasi manual mengikuti tanggal mutasi, dan lampiran pengadaan mengikuti tanggal pengiriman. Arsip juga memuat bukti transaksi batal; berkas yang hilang menyebabkan arsip ditolak agar audit tidak diam-diam kehilangan bukti.
- Daftar transaksi memakai bulan berjalan Asia/Jakarta. Mengganti bulan langsung menerapkan filter. Reset kembali ke bulan berjalan; Semua bulan membuka lintas periode. Pagination dan Excel mempertahankan filter. Arsip invoice kantor juga dapat dicari dengan pilihan Semua bulan.
- Dasar periode: pengadaan memakai tanggal pengiriman, invoice memakai tanggal terbit, kas memakai tanggal mutasi, pembayaran memakai tanggal bayar dan omzet memakai tanggal konfirmasi. Saldo KMS tetap seluruh tanggal aktif; total masuk/keluar mengikuti filter.
- Profit KMS adalah selisih harga KMS dan beli supplier dikali jumlah. Profit koperasi adalah selisih harga koperasi dan harga KMS dikali jumlah. Laporan menggunakan nilai invoice terbit dan tidak menyamakan omzet dengan kas yang diterima.

## Kop dan ekspor pengadaan

Owner membuka Kop & template dokumen, lalu memilih supplier, KMS, koperasi atau laporan pengadaan. Atur judul, nama organisasi, alamat/kontak, dua logo, tiga penanda tangan, rekening dan catatan. Invoice mendukung format nomor dan reset urutan. Laporan pengadaan memakai nomor PGD. Perubahan berlaku pada dokumen yang diterbitkan berikutnya; snapshot lama tidak ditimpa.

Ekspor baru menggunakan 11 kolom: No, Tanggal, Keterangan, QTY, Satuan, HPP KMS, Margin KMS, HPP KOP, Margin KOP, Harga Beli Dapur, Total ke Dapur. HPP KMS adalah harga supplier, HPP KOP adalah harga KMS ke koperasi, harga beli dapur adalah harga koperasi ke dapur. Total ke dapur adalah jumlah dikali harga beli dapur, dibulatkan dua desimal. Ekspor arsip pengadaan lama memakai format sebelumnya, termasuk harga dan profit dapur lama, supaya riwayat tidak ditulis ulang.

## Backup dan pengujian

Backup database PostgreSQL dan folder `private_uploads` atau volume bukti secara rutin, lalu uji pemulihannya. Salinan kode tidak memuat database atau foto bukti. Contoh backup Docker (sesuaikan user/database):

```bash
docker compose exec -T db pg_dump -U kms -d kms -Fc > kms-backup.dump
```

Jalankan tes dengan PostgreSQL untuk pemeriksaan konkurensi:

```bash
python manage.py test
```

Tes portabel terisolasi:

```bash
python manage.py test --settings=config.test_settings
```

Validasi V1.7: 108 tes portabel lulus dari 110 tes; dua tes konkurensi PostgreSQL belum dijalankan. Cakupan termasuk migrasi tanpa perubahan data keuangan lama, penerbitan hanya sampai dapur, harga kantor yang diabaikan, dua harga jual, arsip invoice dan pelunasannya, ekspor baru/lama serta batas akses. Hasil Excel/PDF dan panduan diperiksa lewat render. Pemeriksaan browser mencakup input harga, konfirmasi, navigasi arsip dan laporan. Paket belum diterapkan ke server pengguna.

Dokumentasi V1.6 disimpan di `docs/RIWAYAT_V1_6.md` sebagai riwayat versi; alur aktif mengikuti README V1.7 ini.
