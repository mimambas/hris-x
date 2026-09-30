# HRIS-X Backend — Fondasi Sprint 1 s.d. Go-Live Sprint 10

Fondasi platform HRIS-X sesuai PRD v1.0 (HRIS-X), Sprint S1–S10:
**Tenant, auth, RBP dasar, audit, layanan effective dating** (S1),
modul HR lengkap (S2–S9: org, kontrak, impor, payroll, absensi/cuti/lembur,
rekrutmen, performance 9-box, klaim & pinjaman, dasbor/laporan),
**hardening keamanan & go-live** (S10).
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
`SECRET_KEY` (**wajib diganti di produksi** — start ditolak bila
`ENV=production` dan masih default), `ENV`
(`development`/`staging`/`production`), `ALLOWED_ORIGINS` (koma-dipisah;
default kosong = tanpa CORS), `JWT_EXPIRE_MINUTES` (default 480).

## Yang baru di Sprint 10 (go-live & hardening keamanan)

- **Rate limiting login**: maks 5 kegagalan/menit per (IP + email) →
  429 + `Retry-After`; sukses me-reset counter. In-memory per-instance
  (tanpa dependensi baru); Redis untuk multi-instance = F2.
- **Kebijakan password**: min 12 karakter + huruf besar/kecil/angka/simbol.
  `hash_password()` menolak password lemah (defense in depth); endpoint baru
  `POST /api/v1/users` (buat user, izin `rbac` insert, `extra="forbid"` →
  mass assignment `is_superadmin:true` ditolak 422) dan
  `POST /api/v1/auth/change-password` mengembalikan 422 dengan pesan jelas.
  Seed & test lama aman (`Password123!` lolos).
- **Security headers**: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
  HSTS bila request HTTPS.
- **Startup check**: `ENV=production` + `SECRET_KEY` default → `RuntimeError`
  (fail-closed).
- **CORS**: hanya aktif bila `ALLOWED_ORIGINS` diisi; default tanpa CORS.
- **Audit sweep**: 26 router / 112 endpoint mutasi dipindai — 0 celah
  (dry-run impor sengaja tanpa audit: 0 tulis DB).
- **Pentest mandiri** `scripts/pentest_basic.py`: 12/12 PASS
  (isolasi tenant 404, 401 tanpa/kedaluwarsa token, SQLi tidak 500/bypass,
  mass assignment 422, rate limit 429, RBP 403) → `demo/pentest_report.json`.
- **Migrasi final** `scripts/migrate_final.py`: DB SQLite fresh → seed →
  dry-run → commit `karyawan_500.xlsx` → 500/500 terimpor, NIK duplikat 0
  → `demo/migration_report.json`.
- **Dokumen**: `docs/GO_LIVE_CHECKLIST.md` (15/17 DONE; 2 known limitation
  jujur: RLS live & backup terjadwal), `docs/DEPLOYMENT.md` (Docker generik,
  tanpa klaim provider free-tier), ADR-0013.

> Catatan diskrepansi PRD §24.2: baris S10 tertulis "Payroll cockpit, slip
> gaji, file bank" — itu sudah dibangun di Sprint 4 (lihat ADR-0007).
> Scope Sprint 10 yang berlaku adalah go-live & hardening (ADR-0013).

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

## Yang baru di Sprint 6 (PRD 24.2 S6: rekrutmen, pipeline, e-offer)

- **Requisition**: `draft → submitted → approved/rejected`, approval
  1 level oleh HR (`requisition/correct`). Publish lowongan ditolak 422
  bila requisition belum approved.
- **Lowongan**: `draft → published → closed`. `GET /api/v1/public/jobs?tenant=<slug>`
  TANPA auth — hanya field publik (id, title, description, requirements,
  employment_type, location, published_at).
- **Kandidat & CV**: kandidat eksternal (bukan person); upload CV
  multipart internal ke `backend/uploads/<tenant_id>/` (whitelist
  ekstensi, maks 10 MB), path di `Candidate.cv_file_path`.
- **Lamaran**: unik per (tenant, lowongan, kandidat) → duplikat 422;
  hanya untuk lowongan published.
- **Pipeline**: `applied → screening → interview → offering → hired`;
  cabang `rejected/withdrawn` dari stage mana pun; `hired` hanya dari
  `offering`. Transisi mundur wajib note. Setiap transisi tercatat di
  audit (`action="move_stage"`) dengan actor + timestamp + note.
- **Wawancara**: `scheduled → completed/cancelled`; satu feedback per
  interviewer (skor 1–5, rekomendasi hire/no_hire/consider).
- **E-offer**: `draft → sent → accepted/declined/expired` + PDF surat
  penawaran (reportlab, tanpa e-sign). Terima via tautan publik
  `POST /api/v1/public/offers/{token}/accept` TANPA auth — kedaluwarsa
  otomatis jadi `expired` (422); accept menciptakan Person + Employment
  + JobInfo (`event="hire"`, reason "Rekrutmen reguler"); lamaran → hired.
- **RBP**: role baru `Recruiter` (grant penuh 6 objek, tanpa assignment di
  seed); hiring manager (`view+correct` requisition & job_application)
  dibatasi di kode hanya untuk unit kerjanya sendiri (ADR-0009).
- **Demo end-to-end**: `../.venv/bin/python scripts/demo_recruitment_flow.py` —
  requisition → approve → publish → Ayu Lestari melamar + CV →
  screening → wawancara + feedback skor 4 → e-offer PDF → accept →
  employment tercipta; jejak audit ke `demo/demo_recruitment_trail.json`.

```bash
# Requisition → approve → publish
curl -s -X POST localhost:8000/api/v1/recruitment/requisitions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"org_unit_id":"<uuid>","job_title":"UI/UX Designer","headcount":2,"reason":"Proyek baru"}'
curl -s -X POST localhost:8000/api/v1/recruitment/requisitions/<uuid>/submit \
  -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/v1/recruitment/requisitions/<uuid>/approve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"note":"Disetujui"}'
curl -s -X POST localhost:8000/api/v1/recruitment/postings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"requisition_id":"<uuid>","title":"UI/UX Designer","employment_type":"tetap","location":"Jakarta"}'
curl -s -X POST localhost:8000/api/v1/recruitment/postings/<uuid>/publish \
  -H "Authorization: Bearer $TOKEN"

# Publik: daftar lowongan (tanpa token)
curl -s "localhost:8000/api/v1/public/jobs?tenant=hashiru"

# Kandidat + CV + lamaran
curl -s -X POST localhost:8000/api/v1/recruitment/candidates \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Ayu Lestari","email":"ayu@example.id","phone":"081234567890","source":"website"}'
curl -s -X POST localhost:8000/api/v1/recruitment/candidates/<uuid>/cv \
  -H "Authorization: Bearer $TOKEN" -F "file=@cv.pdf"
curl -s -X POST localhost:8000/api/v1/recruitment/applications \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"posting_id":"<uuid>","candidate_id":"<uuid>"}'

# Pipeline: screening → interview → offering
curl -s -X POST localhost:8000/api/v1/recruitment/applications/<uuid>/move \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"to_stage":"screening","note":"CV cocok"}'

# Wawancara + feedback
curl -s -X POST localhost:8000/api/v1/recruitment/interviews \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"application_id":"<uuid>","scheduled_at":"2026-10-05T10:00:00+07:00",
       "interviewer_ids":["<user-uuid>"],"mode":"onsite","location":"Jakarta"}'
curl -s -X POST localhost:8000/api/v1/recruitment/interviews/<uuid>/feedback \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"interviewer_id":"<user-uuid>","score":4,"recommendation":"hire","notes":"Bagus"}'

# Offer → kirim → PDF → accept publik
curl -s -X POST localhost:8000/api/v1/recruitment/offers \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"application_id":"<uuid>","salary":9000000,"start_date":"2026-11-01",
       "contract_type":"PKWTT","expires_at":"2026-10-15T17:00:00+07:00",
       "job_id":"<uuid>","org_unit_id":"<uuid>","location_id":"<uuid>","legal_entity_id":"<uuid>"}'
curl -s -X POST localhost:8000/api/v1/recruitment/offers/<uuid>/send \
  -H "Authorization: Bearer $TOKEN"
curl -s -o offer.pdf localhost:8000/api/v1/recruitment/offers/<uuid>/pdf \
  -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/v1/public/offers/<token>/accept \
  -H 'Content-Type: application/json' \
  -d '{"nik":"3174050101900001","full_name":"Ayu Lestari","birth_place":"Bandung",
       "birth_date":"1998-05-20","email":"ayu@example.id","phone":"081234567890",
       "bank_name":"BCA","bank_account_no":"1234567890"}'
```

Detail keputusan & simplifikasi jujur: `docs/adr/0009-recruitment.md`.

## Yang baru di Sprint 7 (PRD 24.2 S7: penilaian kinerja, 9-box, pelatihan)

- **Siklus**: `draft → goal_setting → mid_year → year_end → calibration → closed`
  (maju satu langkah; lompat/mundur 422; `closed` = immutable).
- **Goal**: karyawan buat (draft) → submit → atasan/HR approve/reject
  (tak bisa menilai diri sendiri). Total bobot goal APPROVED harus tepat
  100% saat approve maupun self-assessment → 422 bila tidak.
- **Appraisal**: self-assessment (fase goal_setting–year_end) → manager
  score (hanya year_end; ditolak bila self belum submit) → kalibrasi
  (hanya calibration; isi potential 1–5) → `final_score =
  Σ(weight × manager_score)/100`.
- **Matriks 9-box**: `GET /api/v1/performance/cycles/<uuid>/nine-box`
  (422 bila siklus belum calibration/closed). Hanya untuk HR
  (superadmin atau population "all"); karyawan biasa yang mengintip
  data orang lain → 404.
- **Rekomendasi pelatihan**: rule-based deterministik per kotak 9-box
  (BUKAN AI), mis. star → Leadership Development + Mentoring;
  `GET .../training-recommendations?employment_id=<uuid>`.
- **Pelatihan**: katalog kursus (`training_course`) + enrollment
  (`registered → completed/cancelled`), bisa terikat ke siklus kalibrasi.
- **RBP**: object baru `review_cycle`, `goal`, `appraisal`,
  `training_course`, `training_enrollment`; grant penuh ke HR Admin,
  manajer kelola timnya, karyawan self-service milik sendiri.
- **Demo end-to-end**: `../.venv/bin/python scripts/demo_performance_flow.py` —
  siklus "Penilaian Tahunan 2026", 5 karyawan (goal → approve →
  self-assessment → manager score oleh Dewi + HR → kalibrasi),
  matriks 9-box terisi 5 kotak (Bintang: Dewi Lestari; Potensi Tinggi:
  Budi Santoso; dst) → `demo/demo_nine_box.json`; rekomendasi +
  enrollment pelatihan selesai.

```bash
# Siklus → goal_setting
curl -s -X POST localhost:8000/api/v1/performance/cycles \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Penilaian Tahunan 2026","year":2026,
       "start_date":"2026-01-01","end_date":"2026-12-31"}'
curl -s -X POST localhost:8000/api/v1/performance/cycles/<uuid>/transition \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"to_status":"goal_setting"}'

# Goal (karyawan) → submit → approve (atasan/HR)
curl -s -X POST localhost:8000/api/v1/performance/cycles/<uuid>/goals \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","title":"Selesaikan 12 fitur","weight":100,
       "target_text":"Tepat waktu"}'
curl -s -X POST localhost:8000/api/v1/performance/goals/<uuid>/submit \
  -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/v1/performance/goals/<uuid>/approve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"note":"Disetujui"}'

# Appraisal: self-assessment → manager score → kalibrasi
curl -s -X POST localhost:8000/api/v1/performance/appraisals \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","cycle_id":"<uuid>"}'
curl -s -X POST localhost:8000/api/v1/performance/appraisals/<uuid>/self-assessment \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"scores":[{"goal_id":"<uuid>","score":4,"comment":"Mandiri"}]}'
curl -s -X POST localhost:8000/api/v1/performance/appraisals/<uuid>/manager-score \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"scores":[{"goal_id":"<uuid>","score":5}]}'
curl -s -X POST localhost:8000/api/v1/performance/appraisals/<uuid>/calibrate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"potential_score":5}'

# Matriks 9-box (HR) + rekomendasi pelatihan
curl -s localhost:8000/api/v1/performance/cycles/<uuid>/nine-box \
  -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/performance/cycles/<uuid>/training-recommendations?employment_id=<uuid>" \
  -H "Authorization: Bearer $TOKEN"

# Kursus + enrollment
curl -s -X POST localhost:8000/api/v1/performance/courses \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"code":"LD-01","name":"Leadership Development","provider":"Hashiru Academy",
       "duration_hours":16,"cost":2500000}'
curl -s -X POST localhost:8000/api/v1/performance/enrollments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","course_id":"<uuid>"}'
curl -s -X POST localhost:8000/api/v1/performance/enrollments/<uuid>/complete \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'
```

Detail keputusan & simplifikasi jujur: `docs/adr/0010-performance-training.md`.

## Yang baru di Sprint 8 (PRD 24.2 S8: klaim & pinjaman karyawan)

- **Klaim**: jenis klaim berplafon (`/claims/types`, di-seed: kesehatan,
  kacamata, melahirkan, transport, pulsa); alur `draft → submitted →
  approved_l1 (atasan) → approved (HR/Finance) → paid`. Plafon per
  pengajuan & per tahun ditegakkan 422; struk wajib bila
  `requires_receipt`; self-approval ditolak.
- **Reimbursement non-pajak**: klaim `approved` via payroll otomatis masuk
  run sebagai earning NON-PAJAK (`breakdown["reimbursement"]`, kolom
  `PayrollLine.reimbursement_amount`); PPh 21 & basis pensiun memakai
  `taxable_gross = bruto − reimbursement`. Terlihat di slip PDF.
- **Pinjaman**: kebijakan tenant (`/loans/policy`: maks 3× gaji, tenor
  maks 24 bln, bunga flat default 0%); 1 pinjaman aktif per karyawan;
  alur `draft → submitted → active → completed`. Cicilan dibuat lazy per
  periode (idempoten) dan dipotong sebagai deduction `cicilan_pinjaman`;
  `lock_run` menandai angsuran paid + mengurangi sisa. **Payoff**:
  pelunasan dipercepat menjadi potongan penuh di periode terbuka
  berikutnya.
- **RBP**: object baru `claim`, `claim_type`, `loan`, `loan_policy`;
  HR Admin penuh; manajer L1 klaim timnya; karyawan ESS milik sendiri.
- **Demo end-to-end**: `../.venv/bin/python
  scripts/demo_claim_loan_trail.py` — Budi Santoso ajukan klaim kesehatan
  Rp1,5jt → Dewi Lestari approve L1 → admin approve final → masuk payroll
  run 2026-09 (reimbursement tercatat, non-pajak) + pinjaman Rp12jt/12bln
  (cicilan Rp1jt dipotong) → run dikunci → `demo/demo_claim_loan_trail.json`.

```bash
# Pengajuan klaim (karyawan)
curl -s -X POST localhost:8000/api/v1/claims \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","claim_type_id":"<uuid>","amount":1500000,
       "claim_date":"2026-09-15","receipt_document_id":"<uuid>"}'
curl -s -X POST localhost:8000/api/v1/claims/<uuid>/submit \
  -H "Authorization: Bearer $TOKEN"

# Approve L1 (atasan) -> approve final (HR)
curl -s -X POST localhost:8000/api/v1/claims/<uuid>/approve-l1 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"Struk valid"}'
curl -s -X POST localhost:8000/api/v1/claims/<uuid>/approve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"Disetujui HR"}'

# Pinjaman -> submit -> approve (HR)
curl -s -X POST localhost:8000/api/v1/loans \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"employment_id":"<uuid>","amount":12000000,"tenor_months":12}'
curl -s -X POST localhost:8000/api/v1/loans/<uuid>/submit \
  -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/v1/loans/<uuid>/approve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"reason":"Sesuai kebijakan 3x gaji"}'

# Pelunasan dipercepat -> angsuran payoff di periode terbuka berikutnya
curl -s -X POST localhost:8000/api/v1/loans/<uuid>/payoff \
  -H "Authorization: Bearer $TOKEN"

# Sisa plafon klaim tahunan per karyawan
curl -s "localhost:8000/api/v1/claims/summary/yearly?employment_id=<uuid>&year=2026" \
  -H "Authorization: Bearer $TOKEN"
```

Detail keputusan & simplifikasi jujur: `docs/adr/0011-claim-loan.md`.

## Yang baru di Sprint 9 (PRD 24.2 S9: dasbor & laporan standar)

- **Dasbor real-time** (tanpa cache, semua dari data live per tanggal):
  `GET /api/v1/dashboard/headcount?as_of=` (total + breakdown unit /
  jenis kontrak PKWT-PKWTT / jenis kelamin / status, karyawan baru &
  keluar bulan ini), `turnover?period=` (definisi ANL-004 baku:
  terminasi ÷ rata-rata headcount × 100% + breakdown unit + tren 12
  bulan), `attendance?period=`, `leave?year=`, `payroll?period=` (izin
  `payroll` view), `demographics?as_of=` (usia, masa kerja, gender).
- **Headcount historis yang benar**: karyawan yang terminasi *setelah*
  tanggal as_of tetap dihitung aktif per tanggal tersebut.
- **RBP**: objek izin baru `dashboard` (view); Direktur/HR semua data,
  manajer terfilter otomatis ke timnya (target population), karyawan
  biasa 403.
- **Laporan XLSX**: `GET /reports/employees.xlsx` dan
  `GET /reports/payroll-summary.xlsx?period=` — menghormati target
  population, tercatat di audit (aksi `export`).
- **Kolom baru `Person.gender`** ("L"/"P", nullable, dinormalisasi,
  nilai lain 422) — aditif di create/update/out + offer accept.
- **Demo end-to-end**: `../.venv/bin/python scripts/demo_dashboard.py`
  — karyawan baru (PKWT) → terminasi bulan berjalan → headcount &
  turnover real-time → `demo/demo_dashboard.json` (headcount 5,
  turnover Sep 2026: 20,0%, top unit Tim Backend).

```bash
curl -s "localhost:8000/api/v1/dashboard/headcount?as_of=2026-09-30" \
  -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/dashboard/turnover?period=2026-09" \
  -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/v1/reports/employees.xlsx" \
  -H "Authorization: Bearer $TOKEN" -o karyawan.xlsx
```

Detail keputusan & simplifikasi jujur: `docs/adr/0012-dashboard-reports.md`.

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
- Modul: rekrutmen selesai di Sprint 6 (tanpa AI CV parsing, talent pool,
  integrasi job portal, e-sign — lihat ADR-0009)

## Penyederhanaan vs PRD (jujur)

1. `correct_record` belum bisa mengubah tanggal berlaku — harus insert baru.
2. Grup dinamis S1 hanya mendukung field location/org_unit/job/legal_entity
   dengan operator `=`/`in` (tanpa komposisi AND/OR).
3. `detect_retro_impact` di effective-dating belum memeriksa status kunci
   periode payroll (deteksi retro bawaan modul payroll Sprint 4 sudah
   memakai run terkunci).
4. RBP dievaluasi per-request dari DB (tanpa cache); untuk skala besar
   perlu materialisasi/cache grup.
5. Dasbor Sprint 9: tanpa cache & tanpa tabel agregat (dihitung live —
   mahal di skala ribuan karyawan); laporan hanya XLSX on-demand (tanpa
   CSV/PDF terjadwal); metrik absensi dari record tercatat saja; gender
   hanya L/P/tidak-diisi (lihat ADR-0012).
