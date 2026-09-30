# ADR-0007: Engine Payroll (Sprint 4)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §11.2–11.3, PAY-001…PAY-016; scope PRD menaruh payroll di S8–S10
tetapi instruksi sprint ini mendefinisikan Sprint 4 = payroll.

## Keputusan

1. **Struktur gaji**: komponen `earning`/`deduction` bertingkat tenant, berversi
   effective-dated (`SalaryComponentInfo`), ditugaskan per employment
   (`CompAssignment` + info berversi). Prioritas resolusi nominal fixed:
   override assignment → `components` JSON di comp-info (legacy/seed) →
   default katalog. Setiap insert/update/correct komponen WAJIB event
   `salary_structure` dari katalog lifecycle.
2. **Formula engine**: evaluator AST whitelist (`+ - * /`, unary, `min/max/round/abs`,
   konstanta numerik, referensi nama). TANPA `eval()`/`exec()`. Atribut, subscript,
   lambda, comprehension, IfExp, string, dan nama tak dikenal → `FormulaError`.
   Referensi antar-komponen diurutkan topologis; siklus → 422 saat simpan
   (bukan saat hitung).
3. **PPh 21**: metode **progresif-tahunan/12** (annualisasi + penyesuaian Desember),
   BUKAN tarif TER bulanan PMK 168/2023 — penyederhanaan yang disengaja dan
   terdokumentasi di sini. Tarif UU HPP (5/15/25/30/35%), PTKP TK/0–K/3,
   biaya jabatan 5% maks Rp6jt/thn, pengurang pensiun = iuran JHT 2% + JP 1%
   karyawan, PKP dibulatkan ke bawah ke ribuan. Tiga metode pemotongan:
   `gross` (karyawan), `gross_up` (iterasi titik-tetap s.d. konvergen —
   `tunjangan_pajak` == PPh21), `net` (perusahaan, tidak masuk slip).
   Penghasilan tidak teratur (THR + retro) diannualisasi ke perhitungan PPh 21.
   Penyesuaian Desember = pajak tahunan aktual − pajak YTD; boleh negatif.
4. **THR**: Permenaker 6/2016 — masa kerja ≥12 bulan → 1× basis; 1–11 bulan →
   bulan/12 × basis; <1 bulan → 0. Basis default `gaji_pokok`, dapat diubah ke
   `total_fixed` di policy. THR hanya bila `include_thr=true` + tanggal hari raya
   diisi.
5. **Run/lock/retro**: run per periode `YYYY-MM` (unik/tenant), status draft→locked.
   Lock memblokir bila ada error blocking (rekening kosong, take-home negatif).
   Periode harus dikunci berurutan (run baru ditolak bila periode sebelumnya
   masih draft). Retro = hitung-ulang run TERKUNCI terakhir dengan data kini,
   selisih per komponen (earning +, deduction −), dikurangi retro yang sudah
   dibayar untuk periode acuan itu (anti double-count).
6. **Output**: slip PDF per karyawan (reportlab) + file transfer CSV generik
   (`nama,no_rekening,nominal,berita`).

## Konsekuensi / simplifikasi jujur

- Bukan TER PMK 168/2023 (lihat #3). Migrasi ke TER adalah pekerjaan lanjutan.
- `hari_kerja` = hitung hari Senin–Jumat per periode; belum ada kalender libur
  nasional/cuti bersama.
- Konstanta BPJS di-hardcode untuk 2026: batas upah Kes Rp12jt, batas JP
  Rp10.547.300, JKK 0,54% (risiko sangat rendah; belum per-kelas risiko),
  JKM 0,3%, JHT perusahaan 3,7%, JP perusahaan 2%, Kes perusahaan 4%.
  Iuran perusahaan hanya informatif di `employer_cost` (tidak memotong gaji).
- `upah_per_jam` = gaji/173 (Permenaker 102/2004) untuk formula lembur.
- Retro memakai selisih komponen sebulan penuh (tanpa prorata tanggal efektif
  di tengah bulan) dan hanya melihat satu run terkunci ke belakang.
- File transfer CSV generik; format spesifik bank (BCA/Mandiri/BRI) belum ada.
- Slip PDF tanpa tanda tangan digital; satu karyawan per file.
- Belum ada golden test terhadap dataset DJP; angka acuan diuji dari
  perhitungan tangan (lihat `tests/test_sprint4.py::test_pph21_hitungan_tangan`:
  TK/0 Rp10jt/bln → PPh21 Rp235.000/bln; total tahunan Rp4.206.000 pada skenario
  kenaikan gaji tengah tahun dengan penyesuaian Desember Rp316.000).

## Alternatif yang ditolak

- TER bulanan: ditolak untuk sprint ini karena kompleksitas tabel kategori A/B/C
  dan kebutuhan mapping status PTKP→kategori; progresif/12 memberi angka yang
  dapat direkonsiliasi manual dan penyesuaian Desember tetap tepat tahunan.
- Formula via `eval()` sandbox: ditolak; AST whitelist lebih mudah diaudit.
