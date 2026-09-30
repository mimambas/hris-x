# ADR-0006: Katalog Lifecycle, Kontrak Berversi, Impor Excel, Dokumen

Tanggal: 2026-09-30 · Sprint 3 · Status: diterima

## Konteks

PRD 4 (CHR-003 s.d. CHR-012): lifecycle karyawan penuh (hire → promosi →
mutasi → terminasi → rehire), identitas Indonesia tervalidasi
(NIK/NPWP/PTKP/BPJS), kontrak kerja PKWT/PKWTT berversi dengan batas
kebijakan tenant, impor massal 500 karyawan via Excel, dan dokumen
karyawan berversi. Semua harus tetap konsisten dengan arsitektur
effective dating (ADR-0001/0004) dan audit wajib (Sprint 1).

## Keputusan

### 1. Katalog lifecycle sebagai data, bukan enum kode

Tabel `lifecycle_events` (kode unik per tenant, nama tampilan, kategori
`lifecycle`/`org`, daftar `event_reasons` sebagai tabel anak) di-seed
saat tenant dibuat (12 event karyawan + 7 event organisasi).
`insert_record`/`correct_record` wajib menerima `event_applies_to`
dan memvalidasi event+alasan ke katalog; pencocokan case-insensitive
tetapi yang disimpan adalah **kode kanonis**. Alasan derivasi: admin
boleh me-rename nama tampilan tanpa merusak logika bisnis — konsekuensi
yang disengaja dari keputusan ini.

### 2. Derivasi status employment (CHR-004)

`derive_employment_status` memetakan event → (status, end_date):
`termination` → terminated + end_date=valid_from; `probation_start` →
probation; `unpaid_leave` → inactive; `data_update` → tak berubah
(aturan keras "data_update tidak boleh mengubah status"). Derivasi
terjadi di service, bukan di API, agar konsisten untuk jalur impor.

### 3. Kontrak = kontrak-info berversi (bukan effective dating)

Tabel `contracts` (identitas: employment + contract_number unik per
tenant) + `contract_info` (versi: periode valid_from..valid_to,
contract_type, nomor). PKWT wajib punya akhir; PKWTT memakai
`valid_to = 9999-12-31` (MAX_DATE yang sama dengan ADR-0001 —
satu konvensi "tanpa akhir" di seluruh codebase). Extend =
versi baru yang contiguous (valid_from = valid_to lama + 1 hari);
extend pertama otomatis menutup PKWT lama dengan event
`contract_end`. Convert PKWT→PKWTT = versi baru bertipe PKWTT
dengan nomor yang sama.

### 4. Kebijakan kontrak per tenant

`tenant_contract_policies`: `max_pkwt_months` (default 60),
`max_extensions` (default 1). Validasi durasi dan batas perpanjangan
di service `contracts.py` terhadap policy aktif tenant — bukan
konstanta kode — sehingga tenant enterprise bisa melonggarkan
tanpa deploy.

### 5. Sidecar kontrak di timeline job

Extend/convert/terminasi kontrak ikut menulis versi `JobInfo` dengan
event katalog (`contract_extension`, `contract_conversion`,
`contract_end`, periode 1 hari). Satu timeline karyawan = utuh
(jabatan + gaji + kontrak), tanpa tabel gabungan baru. Trade-off:
timeline job memuat baris "kontrak" yang tidak mengubah jabatan —
diterima karena timeline adalah narasi peristiwa, bukan snapshot.

### 6. Impor Excel: template + dry-run + commit atomik (CHR-007)

- `build_template()`: header berbahasa Inggris kecil (machine key)
  + sheet "Panduan" berbahasa Indonesia (human layer); NIK/NPWP/dll
  diformat teks agar Excel tak mengubahnya jadi notasi ilmiah.
- `parse_workbook()` + `validate_all()`: validasi **total** sebelum
  tulis — termasuk NIK unik di dalam file, master by NAMA
  (case-insensitive) dan job by kode.
- `commit()`: tulis seluruhnya dalam SATU transaksi; satu baris
  gagal → rollback penuh. Audit `channel="import"` agar jejak
  impor terpisah dari input manual (prinsip audit Sprint 1).
- Dependensi baru: `openpyxl` (gratis, MIT) — satu-satunya
  dependensi baru Sprint 3.

### 7. Dokumen: berkas di disk, metadata di DB

Upload multipart → `backend/uploads/<tenant>/<person>/`; nama berkas
`{doc_type}_v{n}_{uuid}.{ext}`; versi naik per (person, doc_type);
`is_current` menandai versi aktif; unduh memverifikasi file ada di
disk ("cek populasi": DB tanpa berkas = 404 + pesan eksplisit).
Ekstensi di-whitelist; path traversal ditolak. Trade-off sadar:
berkas di disk lokal (bukan object storage) — cukup untuk MVP
self-host; migrasi ke S3/R2 dicatat sebagai pekerjaan lanjutan
tanpa mengubah skema.

### 8. PTKP: sumber kebenaran ganda yang disinkronkan

PTKP hidup di `persons` (identitas pajak karyawan) dan disalin ke
tiap versi `CompInfo` (konteks penggajian saat itu). Perubahan
HANYA lewat `POST /persons/{id}/ptkp-change` yang atomik:
update person + versi comp baru (event `data_update`,
alasan "Perubahan status PTKP"). PATCH person menolak field ptkp
(422) — mencegah perubahan diam-diam tanpa jejak versi.

## Konsekuensi

- `effective_dating.insert_record` kini **wajib** `event_applies_to`
  — breaking change internal (semua pemanggil dimigrasi di Sprint 3).
- Seed tenant baru otomatis mendapat katalog + policy default.
- Tabel baru tercakup policy RLS `001_rls.sql` (semua punya tenant_id).
- Upload dir `backend/uploads/` di-gitignore; file contoh
  `sample_data/karyawan_500.xlsx` di-commit sebagai fixture demo.
