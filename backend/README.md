# HRIS-X Backend — Fondasi Sprint 1

Fondasi platform HRIS-X sesuai PRD v1.0 (HRIS-X), Sprint S1:
**Tenant, auth, RBP dasar, audit, layanan effective dating.**
Hasil demo S1: *login multi-tenant; setiap perubahan tercatat dengan riwayat.*

> Codebase ini BARU dan terpisah dari prototipe live di `~/workspace/hris/`.
> Jangan mencampur keduanya.

## Arsitektur singkat

- **FastAPI** (keputusan PRD 18.2, opsi A) · **modular monolith** · **PostgreSQL**
  (SQLite untuk test/lokal; SQLAlchemy membuat SQL tetap portabel).
- Multi-tenant: `tenant_id` di semua tabel bisnis; penegakan di lapisan
  aplikasi (Postgres RLS = hardening produksi, lihat ADR-0003).
- Primary key **UUIDv7** (terurut waktu), uang sebagai **integer rupiah**.
- Keputusan besar didokumentasikan di `docs/adr/`:
  - `0001-effective-dating.md` — satu layanan generik untuk semua blok bertanggal efektif
  - `0002-rbp-model.md` — RBP tiga sumbu (role × group dinamis → target population)
  - `0003-tenant-strategy.md` — strategi isolasi tenant

## Struktur

```
backend/
  app/
    api/v1/        # endpoint: auth, persons, job-info, comp-info,
                   #           audit-logs, rbac, org, tenants
    core/          # config, db, ids (uuid7), security (bcrypt+JWT), deps
    models/        # SQLAlchemy 2.0 (semua tabel bisnis punya tenant_id)
    schemas/       # Pydantic v2
    services/      # effective_dating, audit, rbp
    main.py        # create_app() — dipakai server & test
  tests/           # pytest (SQLite in-memory per test)
  docs/adr/        # architecture decision records
  seed.py          # data demo tenant "hashiru"
```

## Cara jalan

```bash
cd backend
../.venv/bin/pip install -r requirements.txt   # atau pakai .venv yang ada

# 1. Seed data demo (SQLite ./hrisx.db; atau set DATABASE_URL postgres)
../.venv/bin/python seed.py

# 2. Jalankan server
DATABASE_URL="sqlite:///./hrisx.db" ../.venv/bin/uvicorn app.main:app --reload --port 8000
# Docs: http://localhost:8000/docs

# 3. Jalankan test
../.venv/bin/python -m pytest tests/ -q
```

Variabel env: `DATABASE_URL` (default `sqlite:///./hrisx.db`),
`SECRET_KEY` (**wajib diganti di produksi**), `JWT_EXPIRE_MINUTES` (default 480).

## Contoh pakai

```bash
# Login (multi-tenant)
curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"tenant_slug":"hashiru","email":"admin@hashiru.id","password":"Password123!"}'
# -> {"access_token":"...","token_type":"bearer","tenant_id":"...","user_id":"...","roles":[...]}

TOKEN=...  # isi dari access_token

# Data jabatan yang berlaku HARI INI (record masa depan tidak ikut)
curl -s "localhost:8000/api/v1/job-info?employment_id=<uuid>&as_of=2026-09-30" \
  -H "Authorization: Bearer $TOKEN"

# Riwayat lengkap (butuh izin view_history)
curl -s "localhost:8000/api/v1/job-info/timeline?employment_id=<uuid>" \
  -H "Authorization: Bearer $TOKEN"

# Audit per karyawan
curl -s "localhost:8000/api/v1/audit-logs?employment_id=<uuid>" \
  -H "Authorization: Bearer $TOKEN"
```

Akun seed: `admin@hashiru.id` / `Password123!` (superadmin),
`dewi@hashiru.id` (Manajer, via grup dinamis), `budi@hashiru.id` (Karyawan).

## Yang BELUM dikerjakan (ruang lingkup S2+)

- Struktur organisasi bertanggal efektif penuh (S1: master data baca saja)
- Rules engine (PLT-020 s.d. PLT-024)
- Workflow engine & approval (PLT-030 s.d. PLT-037)
- Target population per-user / scoping karyawan-ke-data-sendiri
- SoD, masking data sensitif, proxy login, laporan izin (PLT-042 s.d. PLT-045)
- Rantai hash audit (PLT-051), audit akses baca field sensitif (PLT-052)
- Postgres RLS, notifikasi, SSO/OIDC, import Excel, mobile/ESS
- Modul: absensi, cuti, payroll, rekrutmen, dst. (Sprint S2+)

## Penyederhanaan vs PRD (jujur)

1. `correct_record` belum bisa mengubah tanggal berlaku — harus insert baru.
2. Grup dinamis S1 hanya mendukung field location/org_unit/job/legal_entity
   dengan operator `=`/`in` (tanpa komposisi AND/OR).
3. `detect_retro_impact` belum memeriksa status kunci periode payroll
   (modul payroll baru ada di S8).
4. RBP dievaluasi per-request dari DB (tanpa cache); untuk skala besar
   perlu materialisasi/cache grup.
