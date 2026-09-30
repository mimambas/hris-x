# ADR-0010: Penilaian Kinerja, Matriks 9-Box & Pelatihan (Sprint 7)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §24.2 baris S7. Sprint ini menutup loop "goal → nilai →
kalibrasi → kembangkan": karyawan menetapkan goal, dinilai mandiri &
oleh atasan, dikalibrasi potensinya, dipetakan ke matriks 9-box, lalu
mendapat rekomendasi pelatihan.

## Keputusan

1. **Siklus**: `draft → goal_setting → mid_year → year_end → calibration
   → closed`. Hanya maju tepat satu langkah; lompat & mundur ditolak
   422. Status `closed` = immutable: semua mutasi goal/appraisal/
   enrollment terkait siklus itu ditolak 422 (`ensure_cycle_mutable`).
2. **Goal**: karyawan buat (draft) → submit → atasan/HR approve/reject.
   Atasan tidak bisa approve/reject goal miliknya sendiri (403).
   **Total bobot goal APPROVED per (employment, cycle) harus tepat 100%**
   — divalidasi saat approve goal maupun saat submit self-assessment
   (422 bila tidak).
3. **Appraisal**: satu per (tenant, employment, cycle). Alur fase:
   - self-assessment: hanya fase `goal_setting..year_end`; skor wajib
     mencakup tepat seluruh goal yang disetujui (tanpa duplikat).
   - manager score: hanya fase `year_end`; DITOLAK 422 bila self-assessment
     belum di-submit; pengisi bukan karyawan yang dinilai (403 bila
     menilai diri sendiri).
   - calibrate: hanya fase `calibration`; mengisi `potential_score`
     (1–5) dan menghitung `final_score = Σ(weight_i ×
     manager_score_i)/100` (Numeric(4,2)).
4. **9-box**: kategori performance dari `final_score` dan potential dari
   `potential_score` memakai ambang `TenantPerformancePolicy`
   (default: perf_low_max 2.5 / perf_med_max 3.75 / pot_low_max 2.5 /
   pot_med_max 3.5; bisa diubah via `PUT /performance/policy`).
   Pemetaan 9 kotak (performance × potential) + label ID/EN sesuai
   spesifikasi. Endpoint `GET .../nine-box` 422 bila siklus belum
   `calibration`/`closed`.
5. **Rekomendasi pelatihan: RULE-BASED deterministik, BUKAN AI.**
   `TRAINING_RECOMMENDATIONS` memetakan `box_key` → daftar kategori
   kursus (mis. star → ["Leadership Development", "Mentoring"],
   rough_diamond → ["Kepemimpinan Dasar", "Komunikasi Efektif"],
   low_performer → ["Pembinaan Kinerja (PIP)", "Keterampilan Inti"]).
   Tidak ada model, tidak ada inferensi — bisa diaudit baris per baris.
6. **RBP**: object baru `review_cycle`, `goal`, `appraisal`,
   `training_course`, `training_enrollment`. Grant penuh 5 objek ke role
   HR Admin di seed (eksplisit; "*" miliknya sudah mencakup). Manajer:
   `goal`/`appraisal` view+correct (scope tim via target population).
   Karyawan: self-service `goal` & `appraisal` milik sendiri (pola ESS
   Sprint 5) + baca siklus/kursus.
7. **Akses 9-box dibatasi HR**: endpoint memakai
   `require_permission("appraisal", "view")` LALU `_require_hr_scope`:
   superadmin, atau user yang izin appraisal/view-nya membawa target
   population `"all"` (dicek via
   `population_service._user_population_types`). Manajer dengan populasi
   "team" → 403. Baca appraisal/goal milik orang lain oleh karyawan
   biasa → 404 (jangan bocorkan keberadaan record); mutasi tak berizin
   → 403.
8. **RLS**: 6 tabel baru ditambahkan ke daftar eksplisit
   `migrations/001_rls.sql` (mengikuti preseden ADR-0009 — file memakai
   whitelist nama tabel, bukan loop semua tabel ber-tenant_id).
9. **Enrollment** opsional terikat `cycle_id`; bila terikat ke siklus
   closed, complete/cancel ditolak 422. `certificate_document_id`
   disimpan sebagai UUID nullable TANPA FK keras agar modul dokumen
   tetap opsional.

## Konsekuensi / simplifikasi jujur

- Tanpa 360°/peer review: hanya self + 1 atasan (manager score tunggal,
  bukan agregat multi-rater).
- Tanpa OKR cascading: goal bersifat per-karyawan, tidak ada
  keterkaitan goal atasan–bawahan atau alignment org.
- Tanpa PIP formal: "Pembinaan Kinerja (PIP)" hanya label kategori
  rekomendasi, bukan workflow PIP dengan milestone & review.
- Tanpa AI dalam bentuk apa pun: rekomendasi pelatihan adalah tabel
  statis box → kategori; tidak ada pembelajaran dari data historis.
- Approve goal memvalidasi total bobot approved == 100% SETIAP kali,
  sehingga pola yang didukung adalah goal berbobot total 100 yang
  di-approve bersamaan (demo memakai 1 goal @100 per karyawan);
  approval bertahap multi-goal (40+30+30 satu per satu) belum didukung.
- Self-assessment & manager score menimpa (overwrite) bila di-submit
  ulang — tidak ada riwayat versi skor.
- Tidak ada bobot antar-rater, tidak ada normalisasi distribusi skor
  (forced ranking), tidak ada kalibrasi komite multi-atasan.
- `final_score` memakai skor manager apa adanya; skor self tidak masuk
  hitungan (hanya arsip).
