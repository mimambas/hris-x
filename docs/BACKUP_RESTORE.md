# Backup & Restore — HRIS-X

Terakhir diverifikasi: 2026-10-01 (staging).

## 1. Lapisan proteksi data

| Lapisan | Mekanisme | Retensi | Catatan |
|---|---|---|---|
| 1 | Neon point-in-time recovery (PITR) | Retensi mengikuti kemampuan akun Neon saat ini — **verifikasi di Neon Console → Branches** (angka pasti tidak diklaim di sini) | Otomatis, tanpa konfigurasi. Untuk insiden &lt; 1×24 jam: **Neon Console → Branches → Restore → point in time**. Jangan andalkan sebagai arsip. |
| 2 | Backup otomatis harian (pg_dump) | 30 hari (artifact GitHub Actions) | `.github/workflows/backup.yml`, jadwal 01:00 WIB. **Belum aktif — secret repo `DATABASE_URL_BACKUP` belum dikonfigurasi** (Settings → Secrets → Actions). |
| 3 | Ekspor manual per tenant | Disimpan sendiri oleh admin | Halaman **Backup** (menu Admin, superadmin saja) → "Unduh Backup" → JSON. Tercatat di audit log. |

## 2. Ekspor manual (level aplikasi)

- Endpoint: `GET /api/v1/admin/backup/export` (superadmin saja, 403 untuk lainnya).
- Format: `hrisx-backup/1` — JSON berisi kunci `tenant` (baris tabel `tenants`
  milik tenant — akar semua FK `tenant_id`; ditambahkan 2026-10-02 setelah CI
  menemukan restore gagal `ForeignKeyViolation` tanpanya) + seluruh 64 tabel
  tenant + `exported_at`.
- `GET /api/v1/admin/backup/info` — ringkasan jumlah baris per tabel & backend storage aktif.
- Opsi `?include_files=true` menyertakan isi berkas dokumen (hex); default `false` (berkas hidup di object storage, bukan DB).

## 3. Uji restore

```bash
# 1. Buat branch Neon BARU dan KOSONG (jangan pakai branch produksi!)
# 2. Arahkan DATABASE_URL ke branch baru, lalu:
cd backend
DATABASE_URL="<redacted>" \
  python scripts/restore_backup.py /path/ke/hrisx-backup-YYYYMMDD-HHMM.json
```

Skrip menolak target yang tidak kosong (kecuali `--force`), memuat ulang
semua baris sesuai urutan dependensi FK, lalu **memverifikasi jumlah baris
per tabel** (`... OK` / `BEDA`). Berkas dokumen ikut dipulihkan bila
`include_files=true` dipakai saat ekspor.

Hasil uji 2026-10-01: restore dump staging ke SQLite kosong → semua tabel
`OK` (`tests/test_backup_storage.py::test_restore_roundtrip_ke_sqlite_kosong`).

## 4. Object storage (berkas dokumen: struk, CV, sertifikat)

Berkas dokumen **tidak** disimpan di database. Abstraksi:
`backend/app/services/storage.py`.

| Backend | Kapan dipakai | Durable di Vercel? |
|---|---|---|
| `local` (default) | Dev, fallback | **Tidak** — filesystem serverless itu ephemeral |
| `cloudinary` | Produksi/staging | Ya |

### Aktivasi Cloudinary (opsi storage produksi)

> Status 2026-10-02: **terverifikasi**. Paket Free $0 "Free forever",
> "No credit card required" (cloudinary.com/pricing, dicek 2026-10-02);
> 25 kredit/bln (1 kredit = 1.000 transformasi ATAU 1GB storage ATAU 1GB
> bandwidth). E2E di staging lolos: upload → unduh byte-identik untuk
> PNG dan PDF; upload memakai `type="authenticated"` (privat).
> Catatan: delivery PDF/ZIP dimatikan default oleh Cloudinary — aktifkan
> sekali di Console → Settings → Security.

1. Daftar gratis di https://cloudinary.com/users/register/free.
2. Dari dashboard, salin **CLOUDINARY_URL** (`cloudinary://API_KEY:API_SECRET@CLOUD_NAME`).
3. Simpan sebagai env var `CLOUDINARY_URL` di Vercel (production + staging), dan set `STORAGE_BACKEND=cloudinary`.

Keamanan: upload memakai `type="authenticated"` — berkas **tidak** dapat
diakses via URL publik; unduhan selalu lewat endpoint backend yang
berautentikasi (`/documents/{id}/download`). Kunci di kolom `file_path`
memakai prefix skema (`local:` / `cloudinary:`) sehingga baris lama tetap
terbaca tanpa migrasi DB.

## 5. Batasan yang diketahui

- PITR Neon berjendela pendek pada tier gratis → arsip mengandalkan lapisan 2 & 3.
- Restore menimpa ke DB kosong; belum ada merge selektif per tabel.
- `include_files=true` memperbesar dump (base64 hex); untuk arsip rutin
  cukup `false` + backup pg_dump harian (lapisan 2) yang mencakup semuanya.

## 7. Menerapkan ulang RLS setelah menambah tabel

Setiap tabel baru ber-`tenant_id` wajib didaftarkan di
`backend/migrations/001_rls.sql`, lalu policy-nya diterapkan ke database:

- Manual (punya akses psql): `psql "$DATABASE_URL" -f backend/migrations/001_rls.sql`
- Via API (tanpa akses DB langsung): `POST /api/v1/admin/backup/apply-rls`
  (superadmin saja; SQL berasal dari file di codebase yang ter-deploy,
  bukan dari input user; idempoten; beraudit).
