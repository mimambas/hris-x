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

## Yang baru di Sprint 4 (Payroll: struktur gaji, formula, PPh 21, THR)

- **Komponen gaji** berversi effective-dated (`earning`/`deduction`), kode unik
  per tenant, perubahan tercatat sebagai event lifecycle `salary_structure`.
- **Formula engine aman**: evaluator AST whitelist tanpa `eval()`; referensi
  antar-komponen + variabel bawaan (`hari_kerja`, `gaji`, `jam_lembur`,
  `upah_per_jam`); siklus & nama tak dikenal ditolak 422 saat simpan.
- **PPh 21**: progresif-tahunan/12 + penyesuaian Desember (BUKAN tarif TER —
  lihat ADR-0007); metode `gross` / `gross_up` / `net` per policy tenant.
- **THR** proporsional masa kerja (Permenaker 6/2016), basis `gaji_pokok`
  atau `total_fixed`.
- **Payroll run** `YYYY-MM`: hitung → lock (validasi blocking: rekening bank,
  take-home negatif) → retro otomatis di run berikut bila ada koreksi mundur.
  Periode harus dikunci berurutan.
- **Slip gaji PDF** per karyawan + **file transfer bank CSV**; semua angka
  dapat direkonsiliasi (`take_home = gross + THR + retro − potongan − PPh21`).

```bash
# Buat komponen formula (potongan JHT 2% dari gaji)
curl -s -X POST localhost:8000/api/v1/payroll/components \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Potongan JHT","kind":"deduction","calc_type":"formula",
       "amount_or_formula":"0.02 * gaji","valid_from":"2024-01-01",
       "event":"salary_structure","event_reason":"Komponen baru","reason":"demo"}'

# Tugaskan komponen ke karyawan
curl -s -X POST localhost:8000/api/v1/payroll/assignments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","component_id":"<uuid>","valid_from":"2024-01-01",
       "event":"salary_structure","event_reason":"Komponen baru","reason":"demo"}'

# Buat & kunci run Agustus 2026 (dengan THR bila ada hari raya)
curl -s -X POST localhost:8000/api/v1/payroll/runs \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"period":"2026-08","include_thr":false}'
curl -s -X POST localhost:8000/api/v1/payroll/runs/<uuid>/lock \
  -H "Authorization: Bearer $TOKEN"

# Slip PDF + file transfer
curl -s -o slip.pdf "localhost:8000/api/v1/payroll/runs/<uuid>/payslip/<employment-uuid>.pdf" \
  -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/payroll/runs/<uuid>/transfer-file?bank=bca" \
  -H "Authorization: Bearer $TOKEN"
```

Detail keputusan & simplifikasi jujur: `docs/adr/0007-payroll-engine.md`.

## Yang baru di Sprint 5 (PRD 24.2 S5: absensi, cuti multi-level, lembur)

- **Shift**: katalog per tenant (`Pagi 08:00–17:00`, `Siang 13:00–22:00`,
  `Malam 22:00–07:00` overnight) + penugasan bertanggal efektif per
  employment (cek tumpang-tindih). `/shifts`, `/shift-assignments`.
- **Absensi**: `POST /attendance/check-in|check-out` (deteksi telat vs
  shift+grace, pulang-cepat), koreksi **wajib alasan** → versi baru
  (TIM-021, versi lama tersimpan, jam koreksi dihitung ulang),
  `GET /attendance/summary?period=YYYY-MM` (hadir/telat/mangkir/cuti/libur).
  Kolom `source` disiapkan untuk `mobile|web|manual|machine`.
- **Cuti multi-level**: `draft → submitted → approved_l1 → approved`
  (+`rejected`/`cancelled`). L1 = atasan langsung (org chart hari ini),
  L2 = HR; larangan menyetujui pengajuan sendiri. Saldo
  (`entitled/used/remaining`) dipotong saat approval final, kembali bila
  dibatalkan sebelum mulai. Akrual pro-rata (`kuota × sisa_bulan/12`),
  hari cuti = Senin–Jumat minus libur. Cuti bersama massal:
  `POST /holidays/{id}/apply-mass-leave` (idempoten, potong 1 hari semua
  karyawan aktif).
- **Lembur**: pengajuan pra-persetujuan maks 4 jam/hari; upah =
  1,5× jam pertama + 2× sisanya, upah/jam = `gaji_pokok/173` (PP 35/2021),
  dikunci saat approval final. Tabel `OvertimeRate` bertanggal efektif.
- **Integrasi payroll (ATT-010)**: variabel `hari_hadir`, `hari_mangkir`,
  `jam_lembur`, `upah_lembur`, `potongan_mangkir_aktif` mengalir ke formula
  gaji — seed: `uang_makan = hari_hadir × 50.000`,
  `lembur = jam_lembur × upah_per_jam + upah_lembur`,
  `potongan_mangkir = hari_mangkir × (gaji/25) × potongan_mangkir_aktif`.
  Lembur approved otomatis masuk payroll run; variabel integrasi terlihat
  di `inputs_snapshot` tiap baris slip (rekonsiliasi). Tanpa record absensi
  → fallback `hari_hadir = hari_kerja` (run lama tetap reproduksibel).
- **ESS/RBP**: karyawan self-service (`view+insert` absensi/cuti/lembur),
  manajer `view+correct` (persetujuan tim).
- **Demo end-to-end**: `../.venv/bin/python scripts/demo_leave_flow.py` —
  Budi mengajukan cuti via `?source=mobile` → Dewi (atasan) approve L1 →
  admin approve L2 → saldo 12→9; jejak audit ke `demo/demo_leave_trail.json`.

```bash
# Check-in (telat terdeteksi otomatis vs shift+grace)
curl -s -X POST localhost:8000/api/v1/attendance/check-in \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","at":"2026-11-02T08:20:00","channel":"mobile"}'

# Ajukan cuti via "HP", lalu alur approval 2 level
curl -s -X POST 'localhost:8000/api/v1/leave/requests?source=mobile' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","leave_type_id":"<uuid>",
       "start_date":"2026-11-09","end_date":"2026-11-11","reason":"Liburan"}'
curl -s -X POST localhost:8000/api/v1/leave/requests/<uuid>/submit \
  -H "Authorization: Bearer $TOKEN"
# (login sebagai atasan) .../approve-l1   (login sebagai HR) .../approve-l2

# Lembur 3 jam → upah = 1,5x1 + 2x2 jam × gaji/173
curl -s -X POST localhost:8000/api/v1/overtime/requests \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","date":"2026-11-02",
       "start_time":"18:00","end_time":"21:00","reason":"Deployment"}'
```

Detail keputusan & simplifikasi jujur: `docs/adr/0008-attendance-leave-overtime.md`.

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
- Notifikasi, SSO/OIDC, aplikasi mobile/ESS native
  (API siap `source=mobile`; tanpa GPS/geofence/face-match/offline)
- Modul: rekrutmen, dst. (Sprint 6+; absensi/cuti/lembur selesai di Sprint 5,
  payroll di Sprint 4)

## Penyederhanaan vs PRD (jujur)

1. `correct_record` belum bisa mengubah tanggal berlaku — harus insert baru.
2. Grup dinamis S1 hanya mendukung field location/org_unit/job/legal_entity
   dengan operator `=`/`in` (tanpa komposisi AND/OR).
3. `detect_retro_impact` di effective-dating belum memeriksa status kunci
   periode payroll (deteksi retro bawaan modul payroll Sprint 4 sudah
   memakai run terkunci).
4. RBP dievaluasi per-request dari DB (tanpa cache); untuk skala besar
   perlu materialisasi/cache grup.
