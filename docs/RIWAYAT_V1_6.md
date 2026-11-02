ARSIP DOKUMENTASI V1.6 — bukan panduan alur aktif V1.7.

# KMS Management System — V1.6 · Tabel Ringkas, Status & Filter Bulanan

Aplikasi web Django + PostgreSQL untuk pengadaan dan invoicing Supplier → KMS → Koperasi → Dapur → Kantor dapur.
Tampilan menggunakan Django Templates, HTMX, dan Tailwind CSS. Aset CSS dan HTMX sudah tersedia lokal sehingga tidak bergantung pada CDN.

## Menjalankan di Windows / Linux dengan Docker

Pasang Docker Desktop (Windows) atau Docker Engine + Compose (Linux). Ekstrak ZIP ini, lalu buka terminal di folder proyek.

1. Buat konfigurasi dengan secret acak:

   ```bash
   python setup_local.py
   ```

   Jika perintah Python di Linux adalah `python3`, gunakan `python3 setup_local.py`.
   Script tidak menimpa `.env` yang sudah ada.

2. Bangun aplikasi dan PostgreSQL:

   ```bash
   docker compose up -d --build
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py setup_roles
   docker compose exec web python manage.py collectstatic --noinput
   docker compose exec web python manage.py createsuperuser
   ```

3. Buka http://localhost:8000 dan masuk menggunakan akun superuser tadi.

4. Untuk akun admin operasional, buka http://localhost:8000/admin/ → Users → Add.
   Tetapkan grup **Admin Operasional**. Tidak perlu mengaktifkan Staff status atau Superuser status.
   Akun Owner biasa dapat dibuat dengan grup **Owner**.

`docker compose down` menghentikan aplikasi. Data tetap berada di volume Docker.
**Jangan gunakan `docker compose down -v` pada database berisi transaksi**, karena menghapus volume database dan lampiran.

## Mencoba data contoh (opsional)

Hanya jalankan pada database percobaan yang belum memiliki pengadaan dan akun bernama owner / operasional:

```bash
docker compose exec -e KMS_DEMO_PASSWORD=GantiPasswordDemoMinimal12Karakter web python manage.py seed_demo
```

Masuk dengan username `owner` atau `operasional` dan password yang ditentukan di perintah itu.
Jangan gunakan data contoh untuk pencatatan keuangan sungguhan.

## Alur penggunaan

1. **Barang:** daftar kode, nama, kategori, dan satuan. **Supplier & mitra:** daftar supplier, koperasi, dan dapur.
2. **Historis harga supplier:** input barang, supplier, harga per satuan, tanggal berlaku, dan catatan. Setiap perubahan menambah riwayat; tidak menimpa penawaran sebelumnya. Pilih barang untuk melihat penawaran terbaru yang sudah berlaku dari masing-masing supplier, diurutkan dari termurah. Harga masa depan tetap muncul dalam historis tetapi belum masuk daftar pilihan.
3. **Pengadaan & harga:** pilih koperasi, dapur, nama kantor penerima invoice, dan tanggal pengiriman. Isi seluruh baris barang. Klik **Bandingkan penawaran** pada baris terkait, lalu **Gunakan penawaran** untuk memilih supplier. Supplier dan harga belinya terisi dari penawaran. Harga transaksi tetap dapat diinput manual; harga manual yang disimpan juga ditambahkan ke historis.
4. Setelah seluruh barang dan harga beli terisi, klik **Lanjut ke semua harga jual**. Tabel berikutnya memuat seluruh barang untuk diisi tiga harga jual. Empat harga dalam alur ini adalah: beli supplier, KMS → koperasi, koperasi → dapur, serta dapur → kantor dapur. Harga kantor tidak boleh di bawah harga beli dapur. Tidak ada perhitungan porsi, tarif porsi, atau biaya operasional dapur.
5. Owner menekan **Konfirmasi & terbitkan invoice**. Nama barang, satuan, harga, penerbit/penerima, nomor, dan konfigurasi cetak dikunci untuk transaksi ini. Dibuat tiga invoice penjualan dan satu tagihan pembelian untuk setiap supplier yang dipilih.
6. Klik invoice untuk mencetak A4 atau menyimpan PDF melalui dialog cetak browser. Catat pembayaran penuh/sebagian dan unggah bukti bila diperlukan. Pembayaran mengurangi sisa tagihan, tidak mengubah omzet atau profit selisih harga.

### Dua dokumen untuk dapur

| Dokumen | Penerbit → penerima | Harga yang digunakan |
| --- | --- | --- |
| Invoice KMS untuk koperasi | KMS → koperasi | Harga jual KMS |
| Invoice pembelian dapur | Koperasi → dapur | Harga jual koperasi / harga beli dapur |
| Invoice penjualan dapur | Dapur → kantor dapur | Harga yang sudah dinaikkan |

Invoice ke kantor hanya memuat harga jual dapur, tanpa menampilkan harga beli supplier atau harga beli dapur. Kedua invoice dapur merupakan dua transaksi berbeda, bukan dua tagihan pembelian dapur yang sama.

### Omzet dan profit

Contoh per 1 kg: beli supplier Rp12.000, harga KMS Rp12.500, harga koperasi Rp13.000, dan harga kantor dapur Rp13.500.

| Pihak | Omzet | Profit selisih harga |
| --- | --- | --- |
| KMS | Rp12.500 | Rp500 (harga KMS − beli supplier) |
| Koperasi | Rp13.000 | Rp500 (harga koperasi − harga KMS) |
| Dapur | Rp13.500 | Rp500 (harga kantor − harga beli dapur) |

Seluruh nilai dikalikan jumlah barang dan dijumlah per transaksi. Omzet berasal dari invoice yang sudah terbit, bukan jumlah uang masuk; draf tidak dihitung. Laporan dapat difilter periode terbit, koperasi, dan dapur. Dashboard menampilkan bulan berjalan. Omzet ketiga pihak ditampilkan terpisah dan tidak dijumlahkan sebagai satu omzet gabungan. Profit ini adalah selisih harga, tidak memperhitungkan pajak atau biaya lainnya.

### Nomor dan template invoice

Owner membuka **Nomor & template invoice**, lalu memilih supplier, KMS, koperasi, atau dapur. Dapat diatur awalan, pola nomor, reset urutan per bulan/tahun atau tidak direset, judul, kop tambahan, alamat/kontak, rekening, penanda tangan, catatan kaki, template klasik/ringkas, serta jatuh tempo.

Token nomor: `{prefix}`, `{year}`, `{month}`, `{seq}`. Nomor urut menggunakan minimal 5 digit. Contoh: `KMS/2026/10/00001`. Pola bulanan wajib memuat tahun dan bulan, serta setiap pola wajib memuat nomor urut. Pengaturan berlaku untuk invoice berikutnya; dokumen yang sudah terbit tidak dinomori ulang dan tidak berubah kopnya. Nomor dibuat otomatis dalam transaksi database.

Pengaturan bawaan berlaku per jenis invoice (supplier/KMS/koperasi/dapur). Untuk supplier, koperasi, dan dapur, pilih penerbit tertentu lalu simpan pengaturan khusus. Mitra tanpa pengaturan khusus menggunakan pola bawaan. Nama penerbit/penerima tetap mengikuti mitra pengadaan. Logo kiri/kanan dan tiga penanda tangan dapat diatur pada kop. Posisi tanda tangan adalah kiri atas, kanan atas, dan tengah bawah; tiap posisi mendukung jabatan, nama, dan pangkat/NRP/NIP. Tersedia pratinjau sebelum disimpan. Tata letak tanda tangan dijaga sebagai satu blok saat dicetak.

## Hak akses

| Fitur | Owner / Superuser | Admin Operasional |
| --- | --- | --- |
| Master barang, mitra, historis harga dan pemilihan supplier | Ya | Ya |
| Draf pengadaan dan harga supplier/koperasi/kantor | Ya | Ya |
| Mengisi harga jual KMS → koperasi | Ya | Ya |
| Konfirmasi dan menerbitkan invoice | Ya | Tidak |
| Membatalkan pengadaan, pembayaran atau mutasi tersimpan | Ya | Tidak |
| Menghapus baris barang tersimpan pada draf | Ya | Tidak |
| Melihat harga transaksi dan invoice | Ya | Ya |
| Mencatat pembayaran dan bukti | Ya | Ya |
| Laporan omzet/profit koperasi dan dapur | Ya | Ya |
| Laporan omzet/profit KMS | Ya | Tidak |
| Nomor, template invoice dan jejak aktivitas | Ya | Tidak |
| Melihat saldo, uang masuk/keluar KMS, dan mencatat mutasi manual | Ya | Ya |
| Bukti pembayaran invoice (termasuk supplier) | Ya | Ya |
| Bukti mutasi manual KMS dan ZIP audit tanggal | Ya | Ya |
| Ekspor Excel/PDF pengadaan selesai | Ya | Ya |
| Mengelola akun melalui Django admin | Superuser | Tidak |

Admin melihat harga supplier dan harga KMS pada transaksi sehingga dapat menghitung selisih per transaksi. Kerahasiaan margin per transaksi belum diterapkan; laporan agregat omzet/profit KMS dan pengaturan kop masih khusus Owner. Admin sekarang diizinkan melihat kas dan memasukkan semua harga; input operasional dapur tetap tidak disediakan.

## Pembayaran supplier, kas, dan bukti

Buka invoice supplier di **Invoice Supplier** atau dari detail pengadaan. Masukkan nominal, tanggal, referensi transfer, dan bukti pembayaran. Pembayaran penuh/sebagian mengurangi sisa tagihan serta saldo KMS secara otomatis. Nominal tidak boleh melebihi tagihan atau saldo tersedia. Foto JPG/PNG sumber maksimal 5 MB dan PDF maksimal 1 MB dapat diunggah saat pembayaran atau ditambahkan kemudian pada riwayat pembayaran; bukti terkait dengan pembayaran tertentu, bukan hanya pengadaan.

Di **Dana & mutasi KMS**, Owner maupun Admin Operasional dapat melihat saldo, total uang masuk/keluar, riwayat transaksi, dan bukti. Keduanya juga bisa mencatat saldo awal/modal dan uang masuk/keluar lainnya beserta bukti. Gunakan form pembayaran invoice untuk pelunasan tagihan, bukan mutasi manual, agar tidak terjadi pencatatan dua kali. Penerimaan koperasi ke KMS menambah saldo; pembayaran supplier menguranginya. Pembayaran dapur ke koperasi maupun kantor ke dapur tidak memengaruhi kas KMS.

Saldo kas berbeda dari omzet dan profit selisih harga. Penambahan modal serta mutasi kas manual tidak mengubah laporan omzet/profit invoice. Saldo yang ditampilkan merupakan total mutasi yang dicatat, bukan saldo bank yang diperiksa otomatis. Tanggal pembayaran/mutasi tidak boleh berada di masa depan.

Bukti pembayaran invoice dapat diakses oleh Owner dan Admin Operasional. Bukti mutasi manual, saldo, dan laporan kas KMS dapat diakses Owner serta Admin Operasional. File disimpan di volume lampiran privat dan diunduh melalui pemeriksaan login/role.

## Memperbarui dari paket V1 / V1.1 / V1.2 / V1.3 / V1.4 / V1.5

Backup database dan lampiran terlebih dahulu. Pertahankan `.env` milik instalasi dan volume Docker yang sama. Ganti kode aplikasi dengan paket ini, kemudian jalankan:

```bash
docker compose stop web
docker compose build web
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py setup_roles
docker compose run --rm web python manage.py collectstatic --noinput
docker compose up -d web
```

Migrasi mempertahankan transaksi, pembayaran, nomor invoice, dan arsip data operasional lama. Invoice supplier lama kembali tampil dan bisa dibayar. Untuk pengadaan terkonfirmasi dari V1.1 yang belum memiliki invoice supplier, tagihan dipulihkan dari harga beli yang terkunci, dikelompokkan per supplier, dengan nomor `SUP-REC-...`. Cocokkan tagihan hasil pemulihan dengan dokumen supplier sebelum membayar. Ini tidak otomatis mencatat pembayaran baru.

Pembayaran KMS/supplier lama yang belum memiliki mutasi kas dimasukkan ke ledger; pembayaran yang sudah memiliki mutasi tidak dimasukkan kedua kali. Tanggal mutasi mengikuti tanggal pembayaran. Bukti pengadaan lama tidak ditebak sebagai bukti pembayaran tertentu dan tetap tersedia pada pengadaan; unggah ulang pada pembayaran bila perlu. Setelah migrasi, periksa saldo dan catat saldo awal/modal yang memang belum pernah dicatat. Tidak ada penambahan modal buatan untuk menutup selisih saldo.

Harga beli supplier dari transaksi lama tetap diimpor menjadi historis harga. Harga rekomendasi lama tidak otomatis dianggap harga jual kantor dapur.

Pengadaan lama yang sudah dikonfirmasi tidak otomatis mendapat invoice kantor dapur karena harga yang benar belum diketahui. Laporannya menampilkan **Belum ada invoice kantor** dan tidak mengada-adakan omzet/profit dapur. Draf lama harus dilengkapi harga kantor sebelum konfirmasi. Gunakan pengadaan baru untuk mencoba alur lengkap.

Harga pada transaksi dikonfirmasi tetap dikunci. V1.5 menambah pembatalan pengadaan/pembayaran/mutasi khusus Owner/Superadmin dengan alasan dan audit. Koreksi dokumen terbit dilakukan dengan pembatalan lalu pencatatan pengganti. Retur barang, nota kredit parsial, stok gudang, dan pajak belum termasuk.

## Pengujian

Untuk tes transaksi dan penguncian bersamaan menggunakan PostgreSQL yang berjalan:

```bash
docker compose exec web python manage.py test
```

User database harus bisa membuat database tes. User bawaan image PostgreSQL dalam Compose memiliki kemampuan tersebut.
Alternatif tes portabel (tidak memverifikasi konkurensi PostgreSQL):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py test --settings=config.test_settings
```

## Server produksi dan pencadangan

Konfigurasi bawaan khusus komputer lokal, DEBUG=1 dan port terikat ke 127.0.0.1. Untuk server, gunakan domain + HTTPS reverse proxy, DEBUG=0, ALLOWED_HOSTS dan CSRF_TRUSTED_ORIGINS sesuai domain, serta secret milik server. Jangan memublikasikan `.env`.

Backup database dan volume lampiran secara rutin. Contoh backup database (terminal Linux):

```bash
docker compose exec -T db pg_dump -U kms -d kms -Fc > kms-backup.dump
```

Sesuaikan nama user/database jika diubah. Backup volume `evidence` juga diperlukan karena database hanya menyimpan referensi berkas. Uji pemulihan pada lingkungan terpisah.

## Fitur tampilan dan laporan V1.3

- **Invoice Supplier** khusus tagihan pembelian, pembayaran, sisa utang, dan bukti. **Invoice Penjualan** khusus dokumen KMS, koperasi, serta kantor dapur. Kedua kelompok terpisah juga pada detail pengadaan.
- Pencarian barang berdasarkan nama/kode menampilkan kode, nama, dan satuan. Pencarian supplier, koperasi, dan dapur memuat maksimal 20 hasil per pencarian dari server; formulir tidak memuat seluruh master ke dropdown. Gunakan tombol panah dan Enter untuk memilih dengan keyboard.
- Input pengadaan kini dilakukan sekaligus: seluruh barang, jumlah, supplier, dan harga beli pada satu tabel, lalu seluruh harga jual pada tabel berikutnya. Pilihan supplier terisi dari perbandingan penawaran atau pencarian manual.
- **Omzet & profit → Export Excel** mengikuti periode/koperasi/dapur. Workbook berisi ringkasan, detail omzet, pembayaran untuk invoice yang dilaporkan, serta tautan bukti. Tanggal pembayaran pada sheet pendukung dapat berbeda dari periode terbit invoice.
- **Dana & mutasi KMS → Export Excel** menghasilkan ringkasan kas, riwayat mutasi bertanda, dan tautan bukti. Export kas tersedia untuk Owner dan Admin Operasional.
- **Pembayaran & bukti** menampilkan data pembayaran dan tombol mata untuk melihat bukti. Filter tanggal pembayaran, supplier, jenis invoice, koperasi, atau dapur lalu export Excel. Satu pembayaran tetap satu baris meskipun memiliki beberapa bukti; tautan bukti berada di sheet tersendiri. Tautan memerlukan login dan hak akses. Gambar tidak ditanam dalam workbook agar export ringan.
- Laporan/Excel untuk Admin Operasional tidak menyertakan omzet/profit atau agregat pembayaran masuk KMS. Akses invoice individual tetap mengikuti aturan sebelumnya.
- Klik **Lihat bukti** (ikon mata) untuk pratinjau foto/PDF tanpa mengunduh. Foto tidak dimuat pada daftar transaksi. Browser yang tidak mendukung dialog dapat membuka bukti pada tab baru.
- Foto baru dioptimasi di server, sisi terpanjang maksimal 1.600 piksel dan ukuran tersimpan maksimal 300 KB, serta thumbnail maksimal 320 piksel. Foto asli unggahan tidak disimpan setelah optimasi. Jika foto terlalu kompleks untuk batas ini, unggahan ditolak dan pengguna diminta memotong bagian yang tidak diperlukan. PDF tidak dikompres otomatis dan dibatasi 1 MB.
- Logo JPG/PNG sumber maksimal 2 MB dioptimasi menjadi PNG, sisi maksimal 600 piksel, tersimpan maksimal 200 KB. Logo bisa dihapus/diganti untuk dokumen berikutnya; logo lama tetap disimpan jika dipakai invoice terbit. SVG tidak diterima.
- File bukti lama tidak diubah/dihapus otomatis; batas kompresi diterapkan pada unggahan baru. Bukti lama tanpa thumbnail tetap bisa dipratinjau dari file yang ada.
- Judul/keterangan dokumen kantor dapur tidak menggunakan tulisan “harga dinaikkan”. Perhitungan profit tetap menggunakan selisih harga transaksi.

### Mengubah kop dan tiga tanda tangan

1. Masuk sebagai Owner dan buka **Kop & template invoice**.
2. Pilih jenis invoice. Untuk koperasi/dapur/supplier tertentu, cari nama penerbit pada **Atur untuk penerbit**, lalu tekan **Buka pengaturan**. Pilih **Pola bawaan** untuk mengubah template umum.
3. Atur nomor dan jatuh tempo, lalu nama organisasi, alamat, serta logo kiri/kanan. Tersedia centang untuk menghapus logo dari dokumen berikutnya.
4. Isi tiga blok penanda tangan: jabatan dan nama wajib diisi bila posisi tersebut digunakan; identitas pangkat/NRP/NIP opsional. Contoh jabatan pada placeholder hanya panduan dan tidak otomatis memakai identitas organisasi tertentu.
5. Atur rekening, catatan, dan template klasik/ringkas. Lihat pratinjau kop/tanda tangan di sebelah formulir, lalu simpan.
6. Terbitkan invoice baru dari pengadaan. Invoice lama tidak berubah logo/kop/nama penanda tangannya. Format satu penanda tangan lama tetap tersedia pada bagian lipat untuk kompatibilitas.

## Input sekaligus V1.4

1. **Pengadaan & harga → Buat pengadaan**: pilih koperasi, dapur, kantor penerima dan tanggal, lalu simpan.
2. Aplikasi langsung membuka **Semua barang & harga supplier**. Tambahkan baris sesuai kebutuhan dan cari nama/kode barang. Isi jumlah, pilih supplier, dan isi harga beli per satuan. Gunakan **Bandingkan penawaran** pada baris untuk melihat seluruh penawaran terbaru barang itu dan memilih supplier/harga sekaligus. Mendukung maksimal 200 baris per pengadaan.
3. Tekan **Simpan draf** bila belum ingin mengisi harga jual, atau **Lanjut ke semua harga jual** jika daftar barang sudah lengkap. Kedua tombol menyimpan seluruh baris yang valid ke database; invoice belum dibuat.
4. Pada **Semua harga jual**, isi harga KMS → koperasi, koperasi → dapur, dan dapur → kantor untuk seluruh barang pada satu tabel. Harga beli serta jumlah tetap terlihat sebagai referensi. Admin Operasional dapat mengisi harga KMS; Owner memeriksa sebelum konfirmasi.
5. **Simpan & kembali ke barang** menyimpan harga yang sudah diisi sebagai draf (harga yang belum diisi boleh kosong/0), lalu membuka kembali daftar pembelian. Isian jumlah/supplier tetap tersimpan. Untuk melanjutkan pemeriksaan, seluruh harga yang menjadi kewenangan pengguna harus lengkap dan harga kantor minimal sama dengan harga beli dapur.
6. **Simpan & periksa pengadaan** membuka ringkasan, tanpa menerbitkan invoice. Owner memeriksa lalu mengonfirmasi sebagaimana alur sebelumnya. Mekanisme invoice per supplier, tiga invoice penjualan, pembayaran, bukti dan kas tidak berubah.
7. Dari ringkasan draf, gunakan **Input semua barang** dan **Isi semua harga jual** untuk memperbaiki seluruh daftar. Link edit per barang dari versi lama masih didukung untuk kompatibilitas.

Isian tersimpan ketika tombol simpan/lanjut/kembali ditekan; bukan setiap ketukan keyboard. Jika dua tab atau akun mengubah pengadaan bersamaan, versi yang tertinggal ditolak agar perubahan pihak lain tidak tertimpa. Muat ulang halaman dan periksa ulang sebelum menyimpan. Mengganti jenis barang pada baris lama mengosongkan harga jual baris tersebut agar harga produk lama tidak terpakai pada produk baru. Mengubah jumlah/supplier untuk barang yang sama mempertahankan harga jual per satuannya.

## Katalog Supplier & Harga

- Pilih **Berdasarkan barang**, cari misalnya Ayam potong, lalu tekan **Tampilkan katalog**. Daftar menampilkan semua supplier terdaftar untuk barang itu, harga terbaru yang sudah berlaku, satuan, dan tanggal harga.
- Pilih **Berdasarkan supplier**, cari Supplier A, lalu tampilkan katalog. Daftar menampilkan seluruh barang yang ditawarkan supplier itu dan harga terakhirnya. Filter barang dan supplier bisa dipakai bersama untuk satu pasangan tertentu.
- Tekan **Lihat histori** untuk seluruh perubahan harga pasangan barang–supplier, termasuk penawaran yang baru berlaku di masa depan. Harga dengan satuan lama tetap ditampilkan sesuai satuannya; perbandingan harga terbaru hanya memakai satuan master saat ini.
- **Daftarkan barang supplier** mencatat produk yang ditawarkan meskipun belum pernah dibeli dan belum memiliki harga. Baris tanpa harga tampil sebagai **Belum ada harga**; tambahkan penawaran melalui **Historis harga**.
- Pasangan barang–supplier dari penawaran dan transaksi lama diimpor saat migrasi. Penawaran baru dan pembelian baru otomatis menambah pasangan tersebut. Migrasi ini tidak mengubah invoice, pembayaran, harga transaksi, atau saldo.

## Cetak invoice padat V1.4

Kop dan logo diperkecil, nomor/tanggal disusun sejajar, pihak penerbit/penerima dipadatkan, jarak antarbaris barang dikurangi, dan blok total/rekening/tiga tanda tangan dipadatkan. Tinggi minimum workspace tidak dibawa ke halaman cetak, sehingga tidak menghasilkan lembar kosong tambahan. Aturan cetak dipisahkan dalam aset khusus.

Gunakan **A4, portrait, skala 100%**, lalu matikan header/footer tambahan browser (tanggal/URL). File CSS menentukan margin halaman 10 mm. Baris barang tetap terbaca; nama panjang tidak dipotong hanya untuk mengejar jumlah halaman. Jumlah baris yang muat bergantung panjang nama, kop, rekening, dan identitas penanda tangan.

Uji render dengan WeasyPrint 70 menggunakan kop 3 baris, dua logo, rekening, dan tiga penanda tangan: contoh 1, 15, dan 20 baris masing-masing satu halaman A4; 40 baris menjadi dua halaman. Total dan blok tanda tangan hanya tampil pada halaman terakhir. Ini uji render PDF independen, bukan jaminan seluruh konfigurasi browser/printer identik. Pengadaan dengan barang lebih banyak tetap dapat dicetak beberapa halaman tanpa membatasi jumlah barang ke satu halaman.

## Status validasi paket

V1.6: 98 tes portabel lulus, dua tes konkurensi PostgreSQL belum dijalankan. Pemeriksaan browser Chromium mencakup tabel, filter bulan/status, aksi, pratinjau bukti dan layar desktop/ponsel. Detail ada pada bagian V1.6 di akhir dokumen. Paket belum diterapkan ke server pengguna.

## Koreksi transaksi dan hak akses V1.5

- Admin Operasional bisa mengisi harga KMS → koperasi, koperasi → dapur dan dapur → kantor, mencatat pembayaran, melihat kas serta membuat uang masuk/keluar manual dan bukti. Konfirmasi dokumen tetap oleh Owner/Superadmin.
- Owner/Superadmin dapat mengubah tujuan/tanggal/catatan pada **Ubah tujuan / tanggal** selama pengadaan masih draf. Barang dan harga draf diedit melalui dua tabel seperti sebelumnya. Hanya Owner/Superadmin yang dapat menghapus baris tersimpan; admin boleh membuang baris baru yang belum disimpan.
- Untuk salah catat pembayaran: buka invoice → **Batalkan pembayaran** → isi alasan minimal 5 karakter → konfirmasi. Pembayaran dan mutasi terkait ditandai batal bersama. Sisa invoice dan kas dihitung ulang; bukti dan data lama tetap tersimpan. Catat pembayaran baru bila diperlukan. Pembatalan bukan transfer pengembalian dana bank.
- Untuk mutasi manual: **Dana & mutasi KMS → Batalkan mutasi**. Mutasi otomatis dari pembayaran harus dibatalkan lewat pembayaran agar sisa tagihan tetap sesuai.
- Untuk membatalkan pengadaan: selesaikan pembatalan setiap pembayaran aktifnya, lalu **Batalkan pengadaan** pada ringkasan. Semua invoice terkait menjadi tidak berlaku dan pengadaan tidak dihitung pada omzet/profit. Pengadaan yang dibatalkan tidak dapat dibayar atau dilanjutkan statusnya. Buat pengadaan baru untuk koreksi transaksi yang sudah terbit.
- Pembatalan uang masuk ditolak jika penghapusannya dari saldo aktif menyebabkan saldo negatif. Selesaikan dana yang memang sudah dipakai terlebih dahulu. Pembatalan berulang tidak menggandakan perubahan saldo.
- Transaksi keuangan tidak dihapus secara fisik. Data pembayaran/mutasi yang batal masih ada pada riwayat bertanda **Dibatalkan**, tetapi tidak masuk total aktif. Export kas menyertakan status per baris. Laporan pembayaran aktif mengecualikan pembayaran batal.
- Jejak pembatalan mencatat pelaku, alasan, waktu dan ID transaksi. Pembatasan hak akses juga berlaku di server, termasuk permintaan langsung ke URL dan manipulasi form.

## Bukti dan unduhan audit V1.5

1. Pada riwayat kas/pembayaran, tekan ikon mata **Lihat bukti** untuk membuka foto/PDF. Daftar tidak memuat thumbnail atau foto secara otomatis.
2. Nama unduhan mengikuti tanggal transaksi, jenis/nomor transaksi dan ID bukti. Contoh: `2026-10-28-pgd-00001-supplier-sup-2026-10-00001-bayar-12-bukti-7.jpg`. Foto baru tetap dikompres maksimal 300 KB, PDF maksimal 1 MB. Bukti lama memperoleh nama unduhan yang sesuai tanpa memindahkan atau mengganti bytes berkas lama.
3. **Dana & mutasi KMS → Unduh bukti per tanggal (ZIP)** atau tombol sejenis di laporan pembayaran. Isi tanggal awal/akhir (inklusif). ZIP berisi bukti dalam folder per tanggal dan `daftar-bukti.csv` untuk mencocokkan berkas dengan transaksi/statusnya.
4. Tanggal bukti pembayaran mengikuti tanggal bayar; bukti mutasi manual mengikuti tanggal mutasi; lampiran pengadaan mengikuti tanggal pengiriman. Tanggal unggah tidak dipakai sebagai pengganti tanggal transaksi.
5. Arsip memuat semua jenis pembayaran dan mutasi KMS, termasuk bukti transaksi batal bertanda `batal`, serta lampiran pengadaan pada rentang tanggal itu. Bukti yang belum pernah diunggah tidak dibuat otomatis. Jika berkas hilang dari volume, unduhan arsip ditolak agar hasil audit tidak diam-diam menghilangkan bukti.
6. Filter tanggal pada riwayat kas mengatur daftar dan total masuk/keluar periode; saldo KMS tetap saldo aktif semua tanggal. Filter riwayat kas tidak membatasi transaksi baru yang dicatat melalui form.

## Ekspor pengadaan Excel/PDF V1.5

1. Sebelum konfirmasi pengadaan, Owner membuka **Kop & template dokumen → Laporan pengadaan**. Atur judul (default **PENAWARAN HARGA**), nama organisasi, alamat/kontak, dua logo, rekening/catatan dan tiga penanda tangan opsional. Nomor laporan memakai nomor pengadaan PGD, bukan urutan nomor invoice.
2. Konfirmasi pengadaan menyimpan kop sebagai snapshot. Perubahan pengaturan berikutnya tidak mengubah dokumen transaksi yang sudah terbit. Pengadaan lama mendapat snapshot dari kop invoice KMS yang sudah ada dengan judul Penawaran Harga; tidak mengubah harga, invoice, pembayaran atau saldo lama.
3. Lanjutkan status **Dikonfirmasi → Dalam pengiriman → Diterima dapur**. Status Diterima dapur berarti selesai untuk keperluan ekspor, walaupun invoice masih dapat dicicil. Tombol **Export pengadaan Excel / PDF** muncul pada detail pengadaan. Draf, pengadaan belum diterima dan pengadaan batal tidak dapat diekspor sebagai laporan selesai.
4. Kedua format memakai kolom sesuai contoh: No, Tanggal, Keterangan, QTY, Satuan, HPP KMS, Margin KMS, HPP KOP, Margin KOP, HPP Dapur, Rekomendasi Dapur, Profit Dapur, Total Profit. Harga dan margin adalah rupiah per satuan; total profit dikalikan jumlah barang.
5. Definisi: **HPP KMS = harga beli supplier**, **Margin KMS = harga KMS ke koperasi − harga beli supplier**, **HPP KOP = harga KMS ke koperasi**, **Margin KOP = harga koperasi ke dapur − harga KMS**, **HPP Dapur = harga koperasi ke dapur**, **Rekomendasi Dapur = harga dapur ke kantor**, **Profit Dapur = harga kantor − HPP Dapur**, **Total Profit = jumlah × profit dapur**. Tidak menambahkan input harga baru.
6. Excel berisi angka/tanggal bertipe asli, total profit, kop/logo, tiga tanda tangan, pengulangan kepala tabel dan pengaturan cetak A4 landscape. Nilai harga ekspor adalah snapshot transaksi, bukan rumus dinamis untuk mengubah invoice dari Excel. PDF diunduh langsung dari server, tidak memerlukan dialog cetak browser. Tabel yang panjang dilanjutkan ke halaman berikutnya dengan kepala tabel berulang, tanda tangan di akhir.

Validasi V1.5: 82 tes portabel lulus (84 total, 2 tes PostgreSQL konkurensi dilewati), termasuk hak akses baru, pembatalan/idempotensi/saldo, pemblokiran pembayaran batal, ZIP audit dan pemetaan tanggal, filter kas, nama bukti, ekspor selesai, snapshot kop serta perhitungan margin/profit. PDF contoh 33 baris dan 100 nama panjang berhasil dirender; contoh 33 baris diperiksa visual. Workbook contoh juga dibuka/dicetak lewat LibreOffice dan diperiksa visual. Browser interaktif dan konkurensi PostgreSQL belum diverifikasi dalam lingkungan ini. Belum diterapkan ke server pengguna.


## Tabel dan filter bulanan V1.6

- Daftar pengadaan, invoice supplier/penjualan, kas, pembayaran, omzet/profit dan jejak aktivitas memakai bulan berjalan dari waktu server **Asia/Jakarta**. Bawaan dihitung ulang setiap membuka halaman tanpa pilihan bulan, sehingga berganti bulan/tahun otomatis mengikuti kalender.
- Pilih bulan lain pada kolom **Bulan**. Pilihan langsung diterapkan dan centang **Semua bulan** dinonaktifkan. Pilihan eksplisit tetap mengikuti bulan itu saat membuka halaman berikutnya atau mengekspor. Tekan **Reset** untuk kembali ke bulan berjalan, atau centang **Semua bulan** lalu Terapkan untuk seluruh periode.
- Dasar tanggal: pengadaan memakai tanggal pengiriman; invoice memakai tanggal terbit; kas memakai tanggal mutasi; laporan pembayaran memakai tanggal pembayaran; omzet/profit memakai tanggal konfirmasi pengadaan; audit memakai waktu aktivitas. Saldo KMS tetap semua tanggal, sedangkan total masuk/keluar mengikuti filter aktif dan mengecualikan pembatalan.
- **Status** membatasi daftar, **Urutkan → Status** mengelompokkan status. Pengadaan diurutkan Draf → Dikonfirmasi → Dalam pengiriman → Diterima dapur → Dibatalkan. Invoice diurutkan Belum dibayar → Dibayar sebagian → Lunas → Dibatalkan. Transaksi kas/pembayaran menampilkan transaksi aktif dahulu, kemudian pembatalan. Tersedia urutan Terbaru/Terlama. Laporan pembayaran bawaan tetap hanya transaksi Aktif; pilih Dibatalkan atau Semua status untuk audit.
- **Filter lainnya** membuka rentang tanggal, mitra dan jenis invoice pada halaman yang mendukungnya. Rentang tanggal eksplisit dari tautan lama tetap bekerja lintas bulan jika tidak menyertakan parameter bulan. Jika bulan dan rentang tanggal sama-sama dipilih, keduanya diterapkan sebagai irisan. Pilihan tanggal tidak diubah menjadi pencatatan transaksi.
- Filter bulanan tidak menyembunyikan master barang/mitra, katalog supplier atau histori penawaran harga. Data referensi dan perbandingan harga tetap tersedia lintas periode. Master barang/mitra kini dapat difilter Aktif/Nonaktif dan diurutkan berdasarkan status.
- Tabel layar memakai baris pendek, nominal tanpa desimal nol yang berulang (Rp100.000), serta desimal yang tetap terlihat bila bernilai (Rp100.000,50). Teks panjang dipadatkan dengan ellipsis dan nama lengkap tersedia lewat tooltip atau detail transaksi. Pada layar ponsel, tabel dapat digeser mendatar di dalam panel; halaman tidak ikut melebar.
- Ikon mata membuka bukti. Menu **tiga titik pada kolom Aksi** membuka rincian baris, tambah bukti dan pembatalan. Pembatalan ditempatkan terpisah pada bagian bawah dialog, tetap khusus Owner/Superadmin dan tetap meminta alasan pada halaman konfirmasi. Pada detail pengadaan gunakan **Kelola pengadaan**; pada riwayat pembayaran invoice gunakan tiga titik baris pembayaran.
- Warna status: draf abu-abu, dikonfirmasi biru, dikirim kuning, diterima/lunas hijau, cicilan ungu, belum dibayar jingga, dibatalkan merah. Status tetap ditulis dengan teks agar tidak bergantung warna saja. Jenis uang masuk/keluar juga dibedakan.
- Form filter keuangan memakai komponen yang sama dengan pengadaan/invoice, tombol Terapkan dan Reset sejajar, filter lanjutan bisa dilipat. Form pencatatan kas dipisahkan dan bisa dibuka melalui **Catat uang masuk / keluar lainnya**.
- Tidak ada perubahan skema database pada V1.6. Pembaruan tetap membutuhkan build ulang image dan collectstatic. Jalankan langkah pembaruan di atas; migrate aman dijalankan untuk memastikan versi lama juga lengkap. Pertahankan `.env` dan volume database/lampiran.

Validasi V1.6: **98 tes lulus dari 100 tes**, dua tes konkurensi PostgreSQL dilewati. Tes tambahan mencakup bulan berjalan dan pergantian tahun, batas tanggal bulanan, pilihan semua bulan, penolakan filter tidak valid, kombinasi status/jenis/sortir, laporan dan Excel sesuai periode, pagination mempertahankan filter, master lintas periode, hak akses aksi dan pecahan rupiah tetap terlihat. Chromium memeriksa halaman kas, pengadaan, kedua daftar invoice, pembayaran, omzet dan master; dialog aksi, filter lanjutan, perpindahan bulan otomatis, serta tampilan 1440/1024/390 piksel. Tidak ada kesalahan JavaScript pada pemeriksaan tersebut. Ini pemeriksaan dengan data contoh, belum penerapan ke server pengguna.
