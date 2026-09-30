# ADR-0009: Rekrutmen — Requisition, Lowongan, Pipeline, E-Offer (Sprint 6)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §24.2 baris S6. Sprint ini menutup loop "butuh orang → orang
mulai kerja": kebutuhan disetujui dulu (requisition), lowongan dipublish,
kandidat mengalir lewat pipeline berjejak audit, e-offer diterima via
tautan publik, dan accept otomatis menciptakan Person + Employment +
JobInfo (event `hire`).

## Keputusan

1. **Requisition**: `draft → submitted → approved/rejected`. Approval
   1 level oleh pemegang izin `requisition/correct` (HR/recruiter).
   Publish lowongan DITOLAK (422) bila requisition belum `approved` —
   aturan keras di endpoint publish.
2. **Lowongan**: `draft → published → closed` + `published_at/closed_at`.
   Endpoint publik `GET /api/v1/public/jobs?tenant=<slug>` TANPA auth,
   hanya field publik (tanpa id relasi internal). Tenant dari query param
   wajib (404 bila slug tak dikenal/tidak aktif).
3. **Kandidat ≠ Person**. Kandidat adalah orang luar; CV diunggah via
   endpoint multipart internal ke `backend/uploads/<tenant_id>/`
   (whitelist ekstensi, maks 10 MB, pola `documents.py`) dan path-nya
   disimpan di `Candidate.cv_file_path`. Modul `documents` TIDAK dipakai.
4. **Lamaran** unik per (tenant, posting, kandidat) → duplikat = 422.
   Lamaran hanya untuk lowongan `published`.
5. **Pipeline**: `applied → screening → interview → offering → hired`;
   cabang `rejected/withdrawn` dari stage mana pun (non-final); `hired`
   hanya dari `offering`. Transisi mundur diizinkan dengan note WAJIB;
   lompat maju & transisi dari stage final ditolak 422. Setiap transisi
   tercatat di audit dengan `action="move_stage"` (actor + timestamp +
   note) — audit log adalah trail stage, tanpa tabel history terpisah.
6. **Wawancara**: `scheduled → completed/cancelled`; interviewer =
   daftar user id (divalidasi aktif & se-tenant). Satu feedback per
   interviewer (skor 1–5, rekomendasi hire/no_hire/consider).
7. **E-offer**: `draft → sent → accepted/declined/expired`; pengiriman
   menerbitkan `offer_token` acak (token_urlsafe 32). PDF surat penawaran
   via reportlab (pola `payslip.py`), tanpa tanda tangan digital.
8. **Accept publik** `POST /api/v1/public/offers/{token}/accept` TANPA
   auth: cek kedaluwarsa (lewat → status `expired` + 422), validasi NIK
   16 digit & unik per tenant (409 bila duplikat), lalu atomik membuat
   Person + Employment + JobInfo (`event="hire"`,
   `event_reason="Rekrutmen reguler"`, `created_by` = akun superadmin
   tenant sebagai pencatat sistem; audit `channel="public"`,
   `actor_user_id=NULL`). Lamaran → `hired`.
9. **RBP**: object baru `requisition`, `job_posting`, `candidate`,
   `job_application`, `interview`, `offer`. Role `Recruiter` (grant penuh
   6 objek; tanpa assignment di seed, seperti HR Admin). Hiring manager
   (`view+correct` atas `requisition` & `job_application`) dibatasi di
   KODE: hanya boleh mengelola yang `org_unit_id`-nya = unit kerja
   employment-nya sendiri (dibaca dari `JobInfo` aktif via `ed.as_of`).
   Heuristik pembeda: manager = punya `view+correct` tapi TIDAK punya
   `insert` atas `requisition`; superadmin & pemegang `insert` = HR-like
   (tanpa batas unit).
10. **RLS**: 7 tabel baru ditambahkan ke `migrations/001_rls.sql`.

## Konsekuensi / simplifikasi jujur

- Tanpa AI CV parsing/skrining otomatis, tanpa talent pool & retensi
  kandidat (kandidat yang ditolak tidak dipertahankan/dihubungi ulang).
- Tanpa integrasi job portal (posting manual; endpoint publik hanya baca).
- Tanpa e-sign: PDF offer adalah surat elektronik tanpa tanda tangan.
- Tanpa multi-level approval requisition (1 level), tanpa budget check
  headcount vs formasi, tanpa SLA/time-to-hire tracking.
- Offer 1:1 dengan lamaran (re-offer = tolak/terbitkan ulang manual).
- `hired` via endpoint move tidak membuat Employment (hanya accept
  offer yang menciptakan karyawan) — disengaja agar data kepegawaian
  selalu lahir dari jalur e-offer yang tervalidasi.
- Batas unit manager memakai `insert` pada `requisition` sebagai
  pembeda HR vs manager (bukan nama role) — role kustom dengan kombinasi
  izin berbeda bisa lolos/batasi di luar niat; didokumentasikan di sini.
- Accept publik memakai akun superadmin tenant sebagai `created_by`
  JobInfo (kolom NOT NULL) — jejak aktor manusianya ada di audit
  (`channel="public"`, actor NULL, IP tercatat).
- Kolom `phone` ditambahkan ke `Person` (aditif; ikut di PersonCreate/
  PersonOut/PATCH) untuk menampung data dari form accept offer.
