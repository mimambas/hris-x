# ADR-0008: Absensi, Cuti Multi-Level, Lembur + Integrasi Payroll (Sprint 5)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §10 (TIM/LEV, ATT/LEV) + §24.2 baris S5. Sprint ini menghidupkan
modul operasional harian yang datanya mengalir ke payroll (uang makan,
potongan mangkir, upah lembur).

## Keputusan

1. **Shift**: katalog per tenant (`Shift`: jam mulai/selesai, flag
   `is_overnight`, `grace_minutes`). Penugasan per employment bertanggal
   efektif (`ShiftAssignment` + cek tumpang-tindih). Seed: Pagi 08:00–17:00,
   Siang 13:00–22:00, Malam 22:00–07:00. *Simplifikasi*: penugasan shift
   memakai `valid_from/valid_to` polos (bukan katalog event lifecycle —
   ini penjadwalan operasional, bukan peristiwa kepegawaian).
2. **Absensi**: check-in/out per employment per hari (satu record/hari).
   Telat = lewat `jam_mulai + grace`; pulang-cepat vs jam selesai.
   **Koreksi (TIM-021)**: alasan WAJIB; koreksi = versi baru (`version`,
   `is_current`), versi lama tetap tersimpan; jam yang dikoreksi
   **dihitung ulang** keterlambatannya terhadap shift yang berlaku.
   *Simplifikasi vs PRD*: tanpa GPS/geofence, face matching, deteksi fake-GPS,
   mode offline, dan integrasi mesin (TIM-010–015) — kolom `source` disiapkan
   untuk itu; waktu input dianggap sudah dalam tz lokasi kerja (TIM-016).
3. **Cuti multi-level**: alur `draft → submitted → approved_l1 → approved`
   (+ `rejected`/`cancelled`). L1 = atasan langsung (dibaca dari JobInfo
   per hari ini via `is_manager_of`) atau superadmin; L2 = HR (izin
   `correct` pada `leave_request`) atau superadmin. Larangan menyetujui
   pengajuan sendiri (kecuali approver tanpa employment, mis. superadmin
   sistem — cek dilewati bila `approver_employment_id` None).
4. **Saldo**: counter per employment/jenis/tahun (`entitled/used/remaining`),
   BUKAN ledger append-only — setiap mutasi tetap tercatat di audit log.
   Akrual pro-rata: `kuota × sisa_bulan/12` (gabung Juli → 6 hari).
   Hari cuti = Senin–Jumat minus libur nasional (cuti bersama ikut
   mengurangi bila `deducts_leave`). Saldo dipotong saat approval **final**,
   dikembalikan bila dibatalkan sebelum tanggal mulai. Jenis `izin` tidak
   memotong saldo.
5. **Cuti bersama massal**: satu panggilan memotong 1 hari saldo tahunan
   seluruh employment aktif; idempoten via flag `Holiday.mass_leave_applied`.
6. **Lembur**: pengajuan pra-persetujuan (maks 4 jam/hari, PP 35/2021),
   approval 2 level seperti cuti. Upah = 1,5× jam pertama + 2× sisanya;
   upah/jam = `gaji_pokok/173` (PP 35/2021). Multiplier & divisor di tabel
   `OvertimeRate` bertanggal efektif (siap bila regulasi berubah).
   `pay_amount` **dikunci saat approval final**.
7. **Integrasi payroll (ATT-010)**: `evaluate_employment` menerima variabel
   `hari_hadir`, `hari_mangkir`, `jam_lembur`, `upah_lembur`,
   `potongan_mangkir_aktif` (dari `TenantAttendancePolicy.deduct_absent`).
   Seed katalog: `uang_makan = hari_hadir × 50.000`,
   `lembur = jam_lembur × upah_per_jam + upah_lembur`,
   `potongan_mangkir = hari_mangkir × (gaji/25) × potongan_mangkir_aktif`.
   Lembur approved otomatis ter-merge ke run (`approved_for_period`).
   **Fallback kompatibilitas**: employment tanpa record absensi di periode
   → `hari_hadir = hari_kerja`, `hari_mangkir = 0` (run lama reproduksibel).
   Variabel integrasi terekspos di `PayrollLineOut.inputs_snapshot`
   (rekonsiliasi).
8. **RBP/ESS**: `role_emp` (Karyawan) dapat `view+insert` atas
   `attendance`, `leave_request`, `overtime_request` (self-service);
   `role_mgr` dapat `view+correct` atas ketiganya + `leave_type/holiday/shift`
   (persetujuan tim). Pengajuan orang lain tetap dibatasi populasi target.

## Konsekuensi / simplifikasi jujur

- Tanpa GPS/geofence/face-match/offline/mesin finger (kolom `source`
  disiapkan; PRD TIM-010–015 = pekerjaan lanjutan F1).
- Saldo cuti = counter, bukan ledger (audit log sebagai jejak).
- Akrual pro-rata bulanan sederhana; belum ada carry-over tahunan.
- `cuti_besar` kuota 0 (syarat 72 bulan masa kerja divalidasi).
- Potongan mangkir = gaji/25 per hari (praktik umum; dapat diubah via formula).
- Jam lembur manual (`jam_lembur` di create run) dan lembur approved
  (`upah_lembur`) adalah dua jalur terpisah — tidak dijumlahkan ganda.
