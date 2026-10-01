# Checklist Go-Live HRIS-X (Sprint 10)

Tanggal: 2026-09-30 (diperbarui 2026-10-01: item 13 RLS → DONE, terverifikasi live di Postgres staging). Status: **16/17 DONE (94%)** —
1 item KNOWN LIMITATION yang jujur, bukan DONE palsu.

## 1. Environment variables

| # | Item | Status | Catatan |
|---|------|--------|---------|
| 1 | `DATABASE_URL` | DONE | Postgres di produksi; `sqlite:///./hrisx.db` hanya dev/test |
| 2 | `SECRET_KEY` | DONE | Startup check: `ENV=production` + default → `RuntimeError` (fail-closed) |
| 3 | `ENV` | DONE | `development`/`staging`/`production`; dibaca `get_env()` |
| 4 | `ALLOWED_ORIGINS` | DONE | Koma-dipisah; default kosong = **tanpa CORS** |
| 5 | `JWT_EXPIRE_MINUTES` | DONE | Default 480 (8 jam); kontrak lama tidak berubah |

## 2. Keamanan

| # | Item | Status | Catatan |
|---|------|--------|---------|
| 6 | Rate limiting login | DONE | 5 gagal/menit per (IP+email) → 429 + `Retry-After`; sukses me-reset; per-instance (Redis = F2) |
| 7 | Password policy | DONE | Min 12 char + besar/kecil/angka/simbol; 422 di `POST /users` & `/auth/change-password`; `hash_password` menolak password lemah |
| 8 | Security headers | DONE | nosniff, DENY, strict-origin-when-cross-origin; HSTS hanya bila HTTPS |
| 9 | CORS | DONE | Hanya aktif bila `ALLOWED_ORIGINS` diisi |
| 10 | Audit coverage | DONE | Sweep AST 26 router / 112 endpoint mutasi: **0 celah** (ADR-0013) |
| 11 | Dependency scan | DONE | `pip-audit -r requirements.txt`: **No known vulnerabilities found** (2026-09-30) |
| 12 | Pentest mandiri | DONE | `scripts/pentest_basic.py`: **12/12 PASS** → `demo/pentest_report.json` |

## 3. Data & operasi

| # | Item | Status | Catatan |
|---|------|--------|---------|
| 13 | RLS migration applied (Postgres) | **DONE** | `migrations/001_rls.sql` dijalankan + `verify_rls.py` LULUS di Postgres staging (Neon, DB `hris_x_staging`) pada 2026-10-01: isolasi tenant terverifikasi, tabel `tenants` dikecualikan dari RLS (bootstrap login), role aplikasi `hrisx_sql` NOBYPASSRLS. E2E staging: login 200, headcount terbaca (RLS + `SET LOCAL` bekerja live). |
| 14 | Backup DB | **KNOWN LIMITATION** | Prosedur backup/restore Postgres didokumentasikan di `docs/DEPLOYMENT.md`, tapi **jadwal backup harian + uji restore belum dijalankan** (butuh infra produksi). Target PRD NFR-014. |

## 4. Kualitas & dokumentasi

| # | Item | Status | Catatan |
|---|------|--------|---------|
| 15 | Test suite hijau | DONE | 176 test lama + test Sprint 10 (lihat bawah) |
| 16 | Demo artifacts | DONE | `demo/pentest_report.json`, `demo/migration_report.json` (+ artifact Sprint 1–9) |
| 17 | Dokumentasi API | DONE | OpenAPI otomatis di `/docs`; `README.md` mencakup Sprint 1–10; `docs/DEPLOYMENT.md` baru |

## Test Sprint 10

`tests/test_sprint10.py` — rate limit (5 gagal → 429, sukses me-reset),
password policy (5 aturan → 422 tiap aturan + lolos untuk `Password123!`),
isolasi tenant (person tenant lain → 404), JWT kedaluwarsa → 401,
security headers di respons, startup check (`ENV=production` + default
secret → `RuntimeError`).

## Sebelum benar-benar go-live produksi

1. Sediakan Postgres; jalankan `psql "$DATABASE_URL" -f migrations/001_rls.sql`
   lalu `python migrations/verify_rls.py`.
2. Set `SECRET_KEY` acak ≥32 char, `ENV=production`, `ALLOWED_ORIGINS`
   ke domain frontend resmi.
3. Aktifkan backup harian terenkripsi + uji restore bulanan (NFR-014).
4. Untuk multi-instance: pindahkan rate limit ke Redis (F2).
5. Putuskan terminasi TLS di reverse proxy; pastikan `X-Forwarded-Proto`
   diteruskan agar HSTS aktif.
