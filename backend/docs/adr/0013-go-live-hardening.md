# ADR-0013: Go-Live & Hardening Keamanan (Sprint 10)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §24.2 baris S10 tertulis "Payroll cockpit, slip gaji, file bank"
— **diskrepansi**: seluruh item itu sudah dibangun di Sprint 4 (struktur gaji,
formula engine, PPh 21, THR, payroll run + lock + retro, slip PDF, file
transfer bank CSV; 100/100 test, ADR-0007). Scope Sprint 10 yang berlaku
adalah dari penugasan sprint ini: **go-live & hardening keamanan**, bukan
membangun ulang payroll cockpit. PRD §17 (NFR) dan §19 (Keamanan & UU PDP)
menjadi acuan target.

## Keputusan

1. **Rate limiting login** (`POST /api/v1/auth/login`): maks 5 kegagalan per
   60 detik per (IP + email) → HTTP 429 + header `Retry-After: 60`.
   Hanya kegagalan yang dihitung; login sukses me-reset counter.
   Implementasi in-memory (`dict` → `deque` timestamp) di
   `app/api/v1/auth.py` — **per-instance**. Cukup untuk F1 (satu instance);
   multi-instance butuh store terpusat (Redis) = scope F2. Tanpa dependensi baru.
2. **Kebijakan password**: min 12 karakter, wajib huruf besar, huruf kecil,
   angka, simbol. Ditegakkan di dua lapis:
   - `app/core/security.py::validate_password_policy()` — daftar pelanggaran.
   - `hash_password()` menolak password lemah (`PasswordPolicyError`) sehingga
     **tidak ada jalur** yang bisa menyimpan password lemah (defense in depth).
   - Endpoint baru `POST /api/v1/users` (rbac, izin `rbac` insert) dan
     `POST /api/v1/auth/change-password` mengembalikan **422** dengan pesan
     jelas per aturan yang dilanggar.
   - Seed & test lama aman: `"Password123!"` (12 char, P besar, huruf kecil,
     123, !) lolos semua aturan.
3. **Security headers** via middleware di `create_app()`: `X-Content-Type-Options:
   nosniff`, `X-Frame-Options: DENY`,
   `Referrer-Policy: strict-origin-when-cross-origin`, dan
   `Strict-Transport-Security` (max-age 1 tahun + includeSubDomains) **hanya**
   bila request HTTPS (cek `request.url.scheme` / header `X-Forwarded-Proto`,
   agar dev HTTP lokal tidak dipaksa HSTS).
4. **Startup check**: `ENV=production` + `SECRET_KEY` masih default
   (`dev-only-secret-key-ganti-di-produksi`) → `create_app()` me-raise
   `RuntimeError` dengan pesan jelas. Fail-closed: aplikasi lebih baik tidak
   jalan daripada jalan dengan kunci JWT yang bisa ditebak publik.
5. **CORS**: sebelumnya tidak ada konfigurasi CORS. Kini `CORSMiddleware`
   hanya dipasang bila env `ALLOWED_ORIGINS` diisi (koma-dipisah);
   default kosong = **tanpa CORS** (same-origin saja). `allow_credentials=True`
   hanya aktif bila origins dikonfigurasi eksplisit.
6. **Audit sweep**: 26 file router dipindai (AST); 112 endpoint mutasi —
   **0 celah**: semua memanggil `write_audit` langsung atau via helper
   (`_audit`, `_audit_transition`, `_transition_requisition`, audit di dalam
   service impor `channel="import"`). `POST /imports/employees/dry-run`
   sengaja tanpa audit: 0 tulis DB (bukan mutasi; konsisten dengan NFR-032
   "100% mutasi tercatat").

## Endpoint baru (aditif; tidak mengubah kontrak lama)

- `POST /api/v1/users` — buat user login (izin `rbac` insert). Skema
  `extra="forbid"`: field tak dikenal (`is_superadmin`, dsb) → 422.
  `is_superadmin` selalu `False`; superadmin hanya via seed/DB langsung.
  Teraudit (`action="create"`, `object_type="user"`).
- `POST /api/v1/auth/change-password` — ganti password sendiri; password lama
  wajib cocok (401 bila salah), password baru ikut kebijakan (422).

## Bug yang tertangkap saat build

1. Pentest (f1): `POST /rbac/roles` → 404. Bukan bug aplikasi: path riil
   adalah `/api/v1/roles` (router rbac tanpa prefix). Skrip pentest diperbaiki.

## Hasil pentest mandiri (scripts/pentest_basic.py)

12/12 PASS — `demo/pentest_report.json`. Metode: TestClient in-process
terhadap `create_app()` (setara server lokal untuk lapisan aplikasi;
TLS/proxy/jaringan di luar cakupan).

## Hasil migrasi final (scripts/migrate_final.py)

DB SQLite fresh → seed → dry-run → commit `karyawan_500.xlsx`:
500/500 baris valid, 500 terimpor, NIK duplikat 0, email kosong 0,
NIK invalid 0 — `demo/migration_report.json`.

## Perubahan perilaku keamanan (kontrak lama tidak berubah)

- Login gagal ke-6 dalam 1 menit per (IP+email) kini 429 (sebelumnya selalu
  401). Klien harus menangani 429 + `Retry-After`.
- Password lemah kini mustahil disimpan (`hash_password` menolak) —
  sebelumnya hanya mengandalkan disiplin pemanggil.
- Header keamanan baru di semua respons; HSTS aktif di HTTPS.
- `ENV=production` tanpa `SECRET_KEY` eksplisit kini gagal start.

## Simplifikasi / known limitations (jujur)

- Rate limit per-instance (dict memori); restart menghapus counter;
  multi-instance butuh Redis (F2).
- RLS Postgres (`migrations/001_rls.sql`) belum terverifikasi live —
  tidak ada Postgres di environment ini; isolasi tenant di SQLite/dev
  tetap di level aplikasi (warisan Sprint 2, bukan regresi Sprint 10).
- Tanpa WAF, tanpa deteksi anomali login, tanpa 2FA/MFA (scope F2/F3).
- `pip audit` tidak tersedia di environment (lihat GO_LIVE_CHECKLIST).
