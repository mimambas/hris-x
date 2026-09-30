# ADR-0012: Dasbor & Laporan Standar (Sprint 9)

Tanggal: 2026-09-30
Status: Diterima
Konteks: PRD §24.2 baris S9, §13.4 (ANL-001 s/d ANL-004). Demo goal PRD:
"Direktur melihat headcount dan turnover real-time."

## Keputusan

1. **Semua dasbor dihitung dari data live, tanpa cache** (kriteria ANL-001):
   `GET /api/v1/dashboard/headcount|turnover|attendance|leave|payroll|demographics`.
   Agregasi memakai effective dating (`ed.as_of`) per employment — mahal
   untuk ribuan karyawan, tetapi benar per tanggal. Bila skala jadi masalah,
   materialisasi (tabel ringkasan harian) adalah langkah berikutnya.
2. **Definisi "aktif" historis yang benar**: `status IN (active, probation)`
   dengan `start_date <= as_of` dan (`end_date` kosong atau `>= as_of`),
   DITAMBAH karyawan `terminated` yang `end_date >= as_of` — karyawan yang
   keluar *setelah* tanggal tetap dihitung aktif per tanggal tersebut.
   Tanpa ini, turnover rate (pembagi = rata-rata headcount) salah.
3. **Turnover = ANL-004 baku**: terminasi (`status=terminated`, `end_date`
   dalam periode) ÷ rata-rata headcount (awal+akhir periode)/2 × 100%,
   plus breakdown per unit dan tren 12 bulan.
4. **Izin objek baru `dashboard` (view)** untuk 5 dasbor umum; dasbor
   payroll memakai izin `payroll` view yang sudah ada (data gaji sensitif).
   Manajer terfilter otomatis ke timnya via target population; karyawan
   biasa 403. Seed: grant `dashboard` view ke role Manajer.
5. **Laporan XLSX** (openpyxl, sudah ada): `GET /reports/employees.xlsx`
   (izin `person` view) dan `GET /reports/payroll-summary.xlsx?period=`
   (izin `payroll` view); keduanya menghormati target population dan
   tercatat di audit trail (aksi `export`, object `report`).
6. **Kolom baru `Person.gender`** (nullable, "L"/"P", validasi
   `validate_gender`; dinormalisasi ke huruf besar). Aditif di
   PersonCreate/PersonUpdate/PersonOut + AcceptOfferCreate, masuk
   `_PERSON_FIELDS` (snapshot audit). Nilai lain → 422.

## Bug yang tertangkap saat build

1. Headcount historis mengecualikan karyawan yang terminasi setelah
   tanggal as_of (status filter terlalu sempit) → turnover rate salah
   pembagi. Diperbaiki dengan klausa `terminated AND end_date >= as_of`.
2. `require_permission` dipakai sebagai pemanggilan langsung (tak pernah
   memeriksa!) — pola codebase yang benar adalah
   `Depends(require_permission(...))`. Diperbaiki di kedua router baru.
3. Endpoint laporan tidak `db.commit()` setelah `write_audit` → entri
   export hilang. Ditambah commit eksplisit.

## Simplifikasi vs PRD

- ANL-002 (ekspor CSV/PDF terjadwal): hanya XLSX on-demand; tanpa jadwal.
- Metrik absensi dari record absensi tercatat saja (bukan hari kerja
  terjadwal); catatan ini dikembalikan di respons (`note`).
- Gender hanya L/P/tidak-diisi; tanpa kategori lain.
- Tren turnover 12 bulan dihitung per bulan (36 query ringan), bukan
  dari tabel agregat.
- Data demo seed: Rina Kartika berstatus employment `contract` (bukan
  `active`/`probation` hasil derivasi lifecycle) sehingga tidak masuk
  headcount — quirk data seed Sprint 1, bukan bug Sprint 9.
