# ADR-0001: Layanan Effective Dating Generik

Tanggal: 2026-09-30 · Sprint 1 · Status: diterima

## Konteks

PRD 15.2 mewajibkan semua data yang berubah dari waktu ke waktu (jabatan,
kompensasi, alamat, struktur organisasi, aturan) disimpan sebagai rangkaian
record bertanggal efektif, bukan ditimpa. PLT-010 menuntut **satu library**
untuk semua modul — tidak ada implementasi ganda.

## Keputusan

`app/services/effective_dating.py` adalah satu-satunya tempat logika
tanggal-efektif berada. Model (JobInfo, CompInfo, ...) hanya mendeklarasikan
kolom; semua operasi lewat fungsi generik yang menerima `model` +
`identity_field`:

- `insert_record` — record baru menutup record yang tercakup pada
  (valid_from − 1 hari); valid_to default 9999-12-31; >1 perubahan di hari
  yang sama memakai `seq_no` (record seq_no terbesar yang berlaku).
- `correct_record` — membetulkan record salah **tanpa** menambah riwayat;
  kunci riwayat (valid_from/valid_to/seq_no/identitas) tidak boleh diubah
  lewat jalur ini (aksi & izin berbeda, sesuai PRD).
- `as_of` — record yang berlaku pada tanggal X; record masa depan tidak
  memengaruhi tampilan hari ini. Deterministik (PLT-012).
- `timeline` — riwayat kronologis lengkap (PLT-011).
- `detect_retro_impact` — daftar periode payroll bulanan ("YYYY-MM") yang
  terdampak perubahan bertanggal mundur (PLT-013); stub siap dipakai
  modul payroll Sprint 8 (belum memeriksa status kunci periode).

## Alternatif yang dipertimbangkan

1. **Range type Postgres (tstzrange) + exclusion constraint** — lebih kuat
   di level DB, tetapi tidak portabel ke SQLite (dipakai untuk test) dan
   mengikat ke Postgres sejak hari pertama.
2. **Logika per-modul** — ditolak eksplisit oleh PLT-010.
3. **Slowly Changing Dimension tipe 2 ala data warehouse** — setara secara
   konsep; dipilih varian SAP (valid_from/valid_to/seq_no + event reason)
   karena PRD 3.2 mewajibkan padanan Employee Central (event & event reason
   wajib di setiap perubahan, CHR-004).

## Konsekuensi

- Semua query "data saat ini" harus lewat `as_of`, tidak boleh
  `order_by(valid_from.desc()).first()` secara ad-hoc.
- Insert yang menutup record lama terjadi dalam satu transaksi dengan
  penulisan audit.
- Keterbatasan S1: `correct_record` belum mendukung perubahan tanggal
  berlaku (harus lewat insert baru + correct), dan belum ada validasi
  overlap lintas-tenant di level constraint DB (ditangani di service).
