# ADR-0002: Model RBP Tiga Sumbu

Tanggal: 2026-09-30 · Sprint 1 · Status: diterima

## Konteks

PRD 15.5 menuntut izin mengikuti pola SAP SuccessFactors: **permission role**
(apa yang boleh dilakukan) diberikan kepada **granted group** (siapa)
terhadap **target population** (data siapa). Grup bersifat dinamis —
misalnya "semua HRBP di Jawa Barat" — dan diperbarui otomatis saat data
karyawan berubah. PLT-041 menuntut izin tingkat field (lihat kini, lihat
riwayat, insert, correct, hapus).

## Keputusan

Empat tabel (semua ber-tenant_id):

- `permission_roles` — APA (mis. "HR Admin", "Manajer").
- `permission_groups` — SIAPA, dengan `population_rule` JSON yang
  dievaluasi **saat request**, bukan disimpan sebagai daftar anggota
  statis. Aturan yang didukung S1: `{"type":"all"}`,
  `{"field":"location_id"|"org_unit_id"|"job_id"|"legal_entity_id",
  "op":"="|"in", "value":...}` terhadap JobInfo user yang berlaku hari ini.
- `role_assignments` — sumbu ketiga: role × group → target population.
- `field_permissions` — (role, object_name, field_name) → lima flag boolean.
  `field_name="*"` berarti grant object-level.

Evaluasi di `app/services/rbp.py`:

- `require_permission(object, action)` sebagai dependency FastAPI;
  **default DENY** — tanpa role yang cocok, semua ditolak (403).
- Izin `insert` vs `correct` dibedakan (aksi berbeda untuk data bertanggal
  efektif, sesuai PRD 15.2).
- `is_superadmin` melewati pemeriksaan (jalur bootstrap/ops).

## Alternatif yang dipertimbangkan

1. **Keanggotaan grup materialized** (tabel anggota yang di-refresh oleh
   worker) — lebih cepat untuk populasi besar, tetapi menambah komponen
   async di S1; evaluasi request-time cukup untuk skala awal dan selalu
   konsisten dengan data terkini.
2. **Casbin / Oso** — library policy engine; ditolak karena model tiga
   sumbu + field-level + effective dating cukup spesifik sehingga
   adaptornya akan sama rumitnya dengan implementasi langsung, dan
   menambah dependensi berat.

## Konsekuensi / disederhanakan di S1

- **Scoping per-user belum ada**: "Karyawan" boleh view semua person dalam
  tenantnya (target population per-user = S2, bersamaan dengan MSS).
- Belum ada: SoD rules (PLT-043), masking data sensitif + audit buka
  (PLT-042), proxy login (PLT-044), laporan "siapa bisa lihat apa"
  (PLT-045) — semuanya tercatat sebagai backlog S2+.
- `User.person_id` nullable ditambahkan agar grup dinamis bisa dievaluasi
  dari data employment user; akun admin/sistem boleh tidak terikat Person.
