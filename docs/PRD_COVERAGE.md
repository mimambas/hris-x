# Audit Cakupan PRD — HRIS-X

Disusun 2026-10-06 dari catatan putaran terverifikasi (test suite,
smoke staging, UAT browser, CI) dan pemeriksaan kode pada tanggal
yang sama. Status hanya mengklaim yang punya bukti; penyederhanaan
sadar terhadap PRD dicatat apa adanya, bukan disembunyikan.

Legenda: **Live** = terverifikasi di staging. **Live\*** = inti live
dengan penyederhanaan tercatat. **Belum** = belum dibangun.
**AI** = ditunda sadar (lapisan AI, pola tanpa-AI dipakai).
**User** = menunggu aksi/keputusan pemilik produk.

## Bagian 11 — Payroll (PAY)

| Kode | Item | Status | Catatan |
|---|---|---|---|
| PAY-001 | Komponen gaji ber-atribut (pajak/BPJS/prorata/rumus) | Live | Formula dikonfigurasi; konstanta BPJS 2026 masih hardcode. |
| PAY-002 | Pay group per entitas (NPWP) | Live | Satu employment satu grup aktif. |
| PAY-003 | PPh 21 TER + rekonsiliasi; gross/gross-up/net | Live\* | **Deviasi sadar**: progresif tahunan dibagi 12, bukan tarif TER PMK 168/2023. Metode gross, gross-up (iteratif), dan net tersedia di mesin PPh 21. |
| PAY-004 | PPh pegawai tidak tetap / bukan pegawai / PPh 26 | Belum | Tidak ada jenis bukti potong selain pegawai tetap. |
| PAY-005 | Flag PPh 21 DTP per masa + uji batas Rp10 jt | Belum | |
| PAY-006 | Ekspor XML BPMP/BPA1 siap Coretax + pembetulan | Live\* | BPA1 XML mengikuti template resmi DJP + PDF ber-PIN; **belum pernah diuji unggah ke Coretax** (butuh akun DJP); BPMP & alur pembetulan belum. |
| PAY-007 | Iuran BPJS Kes & TK + batas upah + tarif JKK | Live\* | Tarif JKK belum per-entitas. |
| PAY-008 | THR, bonus, off-cycle | Live\* | THR & bonus sebagai komponen run; run off-cycle khusus belum dipisah. |
| PAY-009 | Validasi pra-approval & panel anomali | Live\* | Validasi kunci run ada; panel anomali khusus belum. |
| PAY-010 | Approval berlapis & pemisahan tugas | Live | Alur siapkan → setujui → kunci; periode wajib berurutan. |
| PAY-011 | Slip digital (PIN), riwayat, unduh BPA1 | Live | PIN slip + PDF BPA1 ber-PIN sama; tanpa tanda tangan digital. |
| PAY-012 | File transfer bank (BCA/Mandiri/BRI/BNI) | Live\* | CSV generik; format spesifik per bank belum. |
| PAY-013 | Retro pay dari perubahan berlaku mundur | Live\* | Selisih sebulan penuh; prorata per periode belum. |
| PAY-014 | Final pay (pesangon/UPMK/UPH per alasan PHK) | Belum | Terminasi belum menghitung komponen final pay. |
| PAY-015 | Jurnal payroll per cost center | Belum | Model cost center ada; jurnal belum dibuat. |
| PAY-016 | Simulasi payroll what-if | Belum | |

## Bagian 12 — Talent Management

| Kode | Item | Status | Catatan |
|---|---|---|---|
| REC-001 | Requisition dari posisi/MPP + approval | Live\* | Tanpa budget check headcount & tanpa SLA. |
| REC-002 | Career site + posting job portal | Belum | Halaman karier publik & integrasi portal belum ada. |
| REC-003 | Pipeline tahap terkonfigurasi (kanban) | Live\* | Pipeline ada; template email & SLA tahap belum. |
| REC-004 | Parsing CV & scoring AI | AI | Tanpa-AI: peninjauan manual. |
| REC-005 | Jadwal interview + scorecard | Live | |
| REC-006 | Asesmen/psikotes via mitra | Belum | Terverifikasi tidak ada di kode. |
| REC-007 | Offer + e-sign; kandidat → karyawan | Live\* | PDF biasa tanpa e-sign; accept publik membuat Person/Employment. |
| REC-008 | Talent pool kandidat & retensi data | Belum | Pool di Suksesi adalah SUC-003, bukan pool kandidat rekrutmen. |
| ONB-001 | Portal preboarding dokumen & BPJS | Live | |
| ONB-002 | Checklist lintas tim + tenggat | Live\* | Eskalasi otomatis keterlambatan belum. |
| ONB-003 | Buddy, agenda, kursus wajib | Live\* | Buddy ada; agenda minggu pertama otomatis parsial. |
| ONB-004 | Offboarding (clearance, final pay, paklaring) | Live\* | Final pay mengikuti keterbatasan PAY-014. |
| PRF-001 | Library goal; OKR/KPI berbobot | Live\* | Tanpa cascading OKR. |
| PRF-002 | Check-in & continuous feedback | Live | |
| PRF-003 | Template review self/atasan/360 | Live\* | Tanpa 360°/peer review; skor self tidak masuk final. |
| PRF-004 | Kalibrasi (9-box, distribusi) | Live\* | Kalibrasi potensi per penilaian pada fase `calibration` + matriks 9-box agregat khusus HR; bukan sesi kalibrasi distribusi rating tersendiri. |
| PRF-005 | PIP formal | Belum | Terverifikasi tidak ada di kode. |
| PRF-006 | AI draft goal & ringkasan feedback | AI | Rekomendasi statis. |
| CMP-001 | Pay grade, salary band, compa-ratio | Live | |
| CMP-002 | Siklus merit/bonus + guideline + approval | Live | Guideline = rating digeser compa-ratio (±2 poin). |
| CMP-003 | Total rewards statement | Live | PDF; memakai konstanta BPJS employer payroll. |
| CMP-004 | Analitik kesetaraan upah per level & gender | Live | `GET /compensation/analytics/pay-equity` (izin objek analitik): rata-rata & median gaji pokok per grade × gender + gap persen. **Supresi grup kecil diterapkan (2026-10-06)**: grup <5 orang → rata-rata/median null + `suppressed: true`, gap hanya bila kedua grup ≥5 (`min_group: 5`); test statistik grup cukup + smoke staging lolos. |
| CMP-005 | Hasil siklus → perubahan CompInfo efektif | Live\* | Siklus bonus difinalisasi tanpa mengubah CompInfo (dibayar via payroll terpisah). |
| LRN-001 | Katalog kursus (PDF/video/tautan; SCORM F3) | Live\* | SCORM belum (terverifikasi tidak ada). |
| LRN-002 | Penugasan wajib per peran/lokasi | Live | |
| LRN-003 | Pre/post-test, sertifikat, masa berlaku | Live | |
| LRN-004 | Q&A AI atas konten pelatihan | AI | |
| SUC-001 | Profil talent (skill, pengalaman, mobilitas) | Live | |
| SUC-002 | Posisi kunci & nominasi suksesor | Live | |
| SUC-003 | 9-box & talent pool | Live | |
| SUC-004 | IDP & jalur karier | Live | |
| SUC-005 | Marketplace internal + privasi atasan | Live | |
| SUC-006 | Ontologi skill; inferensi AI ditinjau | Live\* | Governance manual + persetujuan HR; tanpa inferensi AI. Dropdown kandidat non-HR ditutup 2026-10-06 (`/talent/candidates`). |

## Bagian 13 — ESS/MSS, Engagement & Analytics

| Kode | Item | Status | Catatan |
|---|---|---|---|
| EXP-001 | Beranda karyawan | Live | |
| EXP-002 | Pengajuan terpadu | Live | |
| EXP-003 | Slip gaji, BPA1, riwayat (PIN) | Live | PIN migrasi 008; BPA1 per 2026-10-06. |
| EXP-004 | Perubahan data via approval + OTP | Live\* | OTP masih assisted/manual — **wajib diganti kanal nyata sebelum produksi**. |
| EXP-005 | Notifikasi push/email/in-app/WA | Live\* | In-app + preferensi live; email & WhatsApp belum terhubung. |
| EXP-006 | Bilingual ID/EN; Android ringan | Live\* | UI Bahasa Indonesia saja; web responsif, bukan aplikasi Android ≤40 MB. |
| EXP-007 | Asisten AI aplikasi | AI | |
| EXP-010 | Inbox approval terpadu + massal | Live | Swipe mobile belum (web). |
| EXP-011 | Dashboard tim | Live | |
| EXP-012 | Roster tim & tukar shift | Live | Kelola penugasan (tutup/ganti pola) ditutup 2026-10-06 via API + UI Roster. |
| EXP-013 | Delegasi approval saat cuti | Live | Berakhir otomatis di end_date. |
| EXP-020 | Pengumuman bertarget + tanda dibaca | Live | |
| EXP-021 | Survei pulse & eNPS anonim | Live | Ambang grup minimum diterapkan. |
| EXP-022 | Kudos antarkaryawan | Live | |
| EXP-023 | HR helpdesk (tiket, SLA, KB) + defleksi AI | Live\* | Tiket + SLA + basis pengetahuan live; defleksi AI ditunda. |
| ANL-001 | Laporan standar | Live | Headcount, turnover, kehadiran, lembur, payroll register. |
| ANL-002 | Report builder + jadwal kirim + ekspor | Live\* | Builder + XLSX live; **jadwal kirim menunggu kanal email**. |
| ANL-003 | Dashboard per peran | Live | Populasi mengikuti peran pemanggil. |
| ANL-004 | Definisi metrik baku | Live | Delapan metrik + definisi terbuka; voluntary turnover terklasifikasi per 2026-10-06. |
| ANL-005 | Ekspor data warehouse/BI | Live | API inkremental + kunci API per pengguna (migrasi 013). |
| ANL-006 | Analitik percakapan (bahasa alami) | AI | |

## Bagian lain (ringkasan)

- **Bagian 9–10 (Core HR, Organisasi, Waktu & Cuti)** — Live:
  tenant, auth, RBP, audit, effective dating, katalog event
  lifecycle, absensi/cuti/lembur. Penyederhanaan tercatat: tanpa
  GPS/geofence/face-match/offline/fingerprint; hari kerja Senin–Jumat
  tanpa kalender libur nasional.
- **Bagian 14 (Lapisan AI & Agentic)** — Ditunda sadar seluruhnya;
  pola tanpa-AI dipakai (rekomendasi statis, usulan manual +
  persetujuan manusia). Membutuhkan keputusan penyedia & anggaran.
- **Bagian 15 (Platform Services)** — Live inti: effective dating,
  RBP + target population, audit trail, notifikasi in-app,
  multi-tenant ber-RLS. Rules engine umum & integration hub formal
  belum dibangun sebagai layanan tersendiri.
- **Bagian 16–17 (Kepatuhan & NFR)** — Sebagian: konstanta statutori
  2026 hardcode (belum rule pack bertanggal penuh); backup-restore
  terverifikasi di CI Postgres asli; PITR/immutability backup belum
  terverifikasi.

## Sisa pekerjaan non-AI yang masih bisa dibangun

1. **PAY-014** final pay & pesangon per alasan PHK — menutup
   ONB-004 secara penuh; tabel pesangon/UPMK/UPH terkonfigurasi.
2. **PAY-015** jurnal payroll per cost center (CSV debit=kredit).
3. **PAY-016** simulasi payroll what-if (tanpa menyentuh data
   produksi).
4. **PRF-005** PIP formal; **REC-008** talent pool kandidat;
   **REC-002** halaman karier publik; **REC-006** asesmen mitra;
   **PAY-004/PAY-005** bukti potong non-tetap & DTP.

## Checklist go-live (gerbang sebelum produksi)

- [ ] Secret repo `DATABASE_URL_BACKUP` diisi (pemilik, via
      GitHub/vault) — workflow "Backup database harian" sengaja
      gagal sampai itu terisi.
- [ ] Rotasi API Secret Cloudinary yang pernah terpapar di chat
      (2026-10-02) via vault; jangan pernah lewat chat.
- [ ] Kanal OTP & email nyata menggantikan assisted-OTP
      (EXP-004) dan membuka jadwal kirim laporan (ANL-002) serta
      notifikasi email (EXP-005). Perlu keputusan penyedia gratis
      tanpa kartu.
- [ ] Uji unggah XML BPA1 ke Coretax dengan akun DJP asli
      (PAY-006) sebelum musim lapor (paling lambat 31 Januari).
- [ ] Login cepat demo satu klik di halaman login **dihapus**
      dari build produksi; akun demo staging dimatikan.
- [ ] Data demo staging (tenant `hashiru`) dibersihkan / tenant
      produksi dibuat terpisah; grant & peran ditinjau ulang.
- [ ] PITR & immutability backup diverifikasi; uji restore
      berkala dijadwalkan (restore dasar sudah hijau di CI).
- [ ] Keputusan sadar yang perlu diterima tertulis: PPh 21
      progresif (bukan TER), CSV transfer generik, tanpa e-sign,
      tanpa 360°, UI Bahasa Indonesia saja.
