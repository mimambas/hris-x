# ADR-0015: Frontend Web & Arsitektur Staging

Tanggal: 2026-10-01
Status: Diterima

## Konteks

Fondasi backend (Sprint 1–10) selesai: 193 test hijau, RLS Postgres kini
terverifikasi live (menutup known limitation Sprint 10). Fase 2 menambahkan
frontend web untuk pengguna manusia dan environment staging yang bisa diakses
publik untuk demo/UAT — dengan batasan keras: **100% gratis, tanpa kartu
kredit**.

## Keputusan

### 1. Frontend: Next.js 14 (App Router) + TypeScript + Tailwind

- Lokasi: `frontend/` di repo yang sama (monorepo ringan).
- Halaman v1: `/login` (slug tenant + email + password, JWT di
  `localStorage`), `/dashboard` (headcount & tren turnover 12 bulan),
  `/karyawan` (+ detail, tambah, riwayat employment, dokumen),
  `/cuti` (pengajuan ESS + saldo), `/cuti/persetujuan` (antrean approve
  L1/L2), `/slip` (unduh PDF), `/org` (org chart).
- UI 100% Bahasa Indonesia; format tanggal `id-ID` dan rupiah terpusat di
  `lib/format.ts`.
- `lib/api.ts`: wrapper fetch — 401 → hapus token + redirect `/login`;
  403/404 diterjemahkan ke pesan ramah; `apiDownload` untuk PDF/XLSX.
- Penyesuaian kontrak API hasil bacaan backend: `GET /persons` tanpa param
  `search` (pencarian client-side); approve cuti memakai `/approve-l1` dan
  `/approve-l2`; `POST /persons` wajib field `reason` (audit).

### 2. Staging: Vercel (frontend + backend) + Neon Postgres

| Lapisan | Layanan | Detail |
|---|---|---|
| Frontend | Vercel Hobby | Project `hris-x-frontend-staging` |
| Backend | Vercel Hobby (Python serverless) | Project `hris-x-backend-staging`, entrypoint `index.py` |
| Database | Neon free | Project `hris` (existing), database **baru** `hris_x_staging` — DB prototipe tidak disentuh |

- Deploy via **Vercel REST API file-upload** (bukan Git integration):
  `POST /v13/deployments` + upload file yang hilang. Kredensial hanya via
  helper `dynamic_credentials` — tidak pernah mengekstrak raw token.
- `DATABASE_URL` memakai skema `postgresql+psycopg://` (driver psycopg v3,
  pelajaran dari prototipe) dengan role least-privilege `hrisx_sql`
  (NOBYPASSRLS — wajib, karena owner me-bypass RLS).
- `DB_POOL=null` → `NullPool`: koneksi serverless berumur pendek, tidak
  menahan slot pool Neon.
- `ENV=production`, `SECRET_KEY` di-generate acak 48 byte via env var.
- `ALLOWED_ORIGINS` = origin frontend staging (CORS).

### 3. Pelajaran staging Postgres (bug yang tak terlihat di 193 test SQLite)

1. **`SET LOCAL` harus diterapkan sebelum transaksi dimulai.** Pola
   `set_request_tenant_id()` lalu query dalam transaksi yang sama GAGAL
   karena handler `after_begin` tidak jalan lagi → RLS memfilter semua baris
   → login 401. Fix: `db.commit()` setelah set tenant agar query berikutnya
   membuka transaksi baru (berlaku di `auth.py` login dan
   `recruitment.py` public endpoints).
2. **`func.strftime()` hanya ada di SQLite** → 500 di Postgres.
   Diganti `extract("year"/"month", ...)` yang portabel
   (`services/dashboard.py`, `services/claims.py`).
3. **Vercel function tidak punya egress IPv6** → hostname Neon me-resolve ke
   IPv6 dulu → `FUNCTION_INVOCATION_FAILED`. Fix: `hostaddr=<IPv4 pooler>`
   di `DATABASE_URL`. Risiko: bila Neon merotasi IP pooler, env var harus
   di-refresh.
4. **Neon `reset_password` API mengabaikan password custom** — pakai password
   dari respons API dan tunggu operasi `apply_config` selesai (`finished`).

### 4. Batasan staging yang jujur

- Direktori `uploads/` read-only di serverless → upload struk klaim gagal
  tulis disk di staging; produksi butuh object storage (mis. S3/R2).
- Timeout & bandwidth tier Hobby; Neon free tier — cukup untuk demo/UAT,
  bukan beban produksi.
- Token e-offer format lama (tanpa prefix tenant) tidak valid setelah deploy
  ini — dapat diterima di staging.

## Konsekuensi

- E2E staging terverifikasi: login → headcount (`total=4`, membuktikan
  RLS + `SET LOCAL` bekerja di Postgres live) → daftar karyawan (5 person)
  → preflight CORS OK → halaman `/login` frontend render.
- `GO_LIVE_CHECKLIST.md`: baris RLS berubah dari KNOWN LIMITATION menjadi
  DONE (terverifikasi live di Postgres staging).
