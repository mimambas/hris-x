# HRIS-X Backend — Fondasi Sprint 1 + Platform Sprint 2

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

# Org chart per tanggal (S2): struktur yang berlaku 2026-09-30
curl -s "localhost:8000/api/v1/org/chart?as_of=2026-09-30" \
  -H "Authorization: Bearer $TOKEN"

# Pindah unit ke parent baru berlaku 2026-10-15 (restrukturisasi)
curl -s -X POST localhost:8000/api/v1/org/units/<uuid>/versions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"parent_id":"<uuid>","valid_from":"2026-10-15","event":"Reorganisasi","event_reason":"Efisiensi","reason":"demo"}'

# Custom field: definisi lalu isi nilai untuk satu person
curl -s -X POST localhost:8000/api/v1/custom-fields/definitions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"object_name":"person","field_key":"gol_darah","label_id":"Golongan Darah","field_type":"select","options":[{"value":"A","label_id":"A","active":true},{"value":"B","label_id":"B","active":true}],"reason":"demo"}'
curl -s -X POST localhost:8000/api/v1/custom-fields/values \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"definition_id":"<uuid>","record_id":"<person-uuid>","value":"A","reason":"demo"}'
```

Akun seed: `admin@hashiru.id` / `Password123!` (superadmin),
`dewi@hashiru.id` (Manajer, via grup dinamis), `budi@hashiru.id` (Karyawan).

# Kontrak PKWT baru (nomor otomatis, periode + batas 60 bulan)
curl -s -X POST localhost:8000/api/v1/contracts \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","contract_type":"PKWT","start_date":"2026-01-10","end_date":"2026-12-31","event":"hire","event_reason":"Rekrutmen reguler","reason":"demo"}'

# Kontrak yang berakhir <= 30 hari
curl -s "localhost:8000/api/v1/contracts/expiring?within_days=30" \
  -H "Authorization: Bearer $TOKEN"

# Unduh template impor, dry-run, lalu commit
curl -s -o template.xlsx localhost:8000/api/v1/imports/employees/template \
  -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/v1/imports/employees/dry-run \
  -H "Authorization: Bearer $TOKEN" -F "file=@karyawan.xlsx"
curl -s -X POST localhost:8000/api/v1/imports/employees/commit \
  -H "Authorization: Bearer $TOKEN" -F "file=@karyawan.xlsx"

# Ganti PTKP (atomik: person + versi comp baru)
curl -s -X POST localhost:8000/api/v1/persons/<uuid>/ptkp-change \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ptkp":"K/1","effective_date":"2026-10-01","reason":"Menikah"}'

# Upload dokumen KTP (versi 1)
curl -s -X POST localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "doc_type=ktp" -F "person_id=<uuid>" -F "file=@ktp.pdf"
```

## Yang baru di Sprint 3 (PRD 4: CHR-003 s.d. CHR-012)

- **Katalog lifecycle** (CHR-003/004): event & alasan tersimpan sebagai
  data per tenant (`/lifecycle/events`, `/lifecycle/reasons`) — di-seed
  otomatis untuk tenant baru. Event wajib kode katalog (case-insensitive,
  disimpan kanonis); `insert_record` kini wajib `event_applies_to`.
  Terminasi otomatis menutup employment (`status=terminated`,
  `end_date=valid_from`); rehire = employment baru di person yang sama.
  Aturan keras: `data_update` tidak mengubah status.
- **Validasi Indonesia** (CHR-005/006): NIK 16 digit unik, NPWP 16 digit
  (ternormalisasi), PTKP dari daftar resmi (default `TK/0`), email unik
  lowercase, no. BPJS Kes 13 / TK 11 digit, rekening numerik, tanggal
  lahir tak boleh masa depan. PATCH person menolak field `ptkp`.
- **PTKP**: `POST /persons/{id}/ptkp-change` — atomik: update person +
  versi `CompInfo` baru (event `data_update`), nominal gaji disalin.
- **Kontrak berversi** (CHR-010/011): `/contracts` CRUD + `extend`
  (batas `max_extensions` policy), `convert` PKWT→PKWTT, `expiring`
  (peringatan 30/14/7 hari, terurut), `policy` GET/PUT per tenant
  (default 60 bulan, 1x perpanjangan). Extend/convert/akhir kontrak
  ikut tercatat sebagai sidecar di timeline job.
- **Impor Excel** (CHR-007): `GET /imports/employees/template` (xlsx +
  sheet Panduan), `POST .../dry-run` (laporan per baris, 0 tulis DB),
  `POST .../commit` (atomik: 1 baris gagal → rollback penuh, audit
  `channel=import`). Cocokkan master by nama, job by kode. Data contoh
  500 karyawan: `sample_data/karyawan_500.xlsx` (dibuat via
  `scripts/generate_sample_employees.py`).
- **Dokumen** (CHR-012): `POST /documents` (multipart, whitelist
  ekstensi) — berversi per (person, doc_type), `is_current`,
  `GET /documents/{id}/download` (cek populasi berkas di disk).
  Berkas: `backend/uploads/` (di-gitignore).

## Yang baru di Sprint 2 (PRD 15.1, 9.2)

- **Org bertanggal efektif** (CHR-001): LegalEntity/OrgUnit/Location/
  CostCenter memakai pola identitas + info berversi (ADR-0004).
  `GET /org/chart?as_of=YYYY-MM-DD` → pohon hierarki per tanggal;
  `POST /org/units/{id}/versions` untuk rename/pindah parent/nonaktif;
  `GET .../timeline` untuk riwayat. Siklus parent ditolak; unit
  berpenghuni tidak bisa dinonaktifkan.
- **Custom field** (PLT-001/003, CHR-009): definisi via API tanpa deploy
  (ADR-0005) — tipe text/number/date/select/lookup/attachment, picklist
  berlabel ID/EN, nilai di kolom bertipe. Nonaktif/soft-delete tidak
  menghapus data lama. Izin per field: `custom:<field_key>`.
- **Target population** (PRD 15.5): `RoleAssignment.target_population`
  (`all`/`self`/`team`); `/persons` otomatis terfilter — manajer
  melihat direct report, karyawan melihat dirinya sendiri.
- **Postgres RLS**: `migrations/001_rls.sql` (policy `app.tenant_id` +
  `SET LOCAL`) + `migrations/verify_rls.py`. SQLite tetap untuk
  dev/test. Lihat "Postgres RLS" di bawah.

## Postgres RLS (produksi)

1. Terapkan sekali sebagai pemilik DB:
   `psql "$DATABASE_URL" -f migrations/001_rls.sql`
2. Setiap transaksi aplikasi WAJIB: `SET LOCAL app.tenant_id='<uuid>'`
   (konteks hilang otomatis saat transaksi selesai — aman untuk pool).
3. Role aplikasi hanya diberi GRANT DML (bukan pemilik tabel) agar
   policy dievaluasi.
4. Verifikasi: `DATABASE_URL=... python migrations/verify_rls.py`
   (butuh Postgres asli; SQLite dev/test tidak mendukung RLS —
   isolasi tenant di sana tetap di level aplikasi).

## Yang BELUM dikerjakan (ruang lingkup S3+)

- Rules engine (PLT-020 s.d. PLT-024)
- Workflow engine & approval (PLT-030 s.d. PLT-037)
- SoD, masking data sensitif, proxy login, laporan izin (PLT-042 s.d. PLT-045)
- Rantai hash audit (PLT-051), audit akses baca field sensitif (PLT-052)
- Notifikasi, SSO/OIDC, mobile/ESS
- Modul: absensi, cuti, payroll, rekrutmen, dst. (Sprint 4+)

## Penyederhanaan vs PRD (jujur)

1. `correct_record` belum bisa mengubah tanggal berlaku — harus insert baru.
2. Grup dinamis S1 hanya mendukung field location/org_unit/job/legal_entity
   dengan operator `=`/`in` (tanpa komposisi AND/OR).
3. `detect_retro_impact` belum memeriksa status kunci periode payroll
   (modul payroll baru ada di S8).
4. RBP dievaluasi per-request dari DB (tanpa cache); untuk skala besar
   perlu materialisasi/cache grup.
