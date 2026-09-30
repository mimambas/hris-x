# ADR-0004: Struktur Organisasi Bertanggal Efektif (Identitas + Info Berversi)

Tanggal: 2026-09-30 · Sprint 2 · Status: diterima

## Konteks

PRD 9.2 (CHR-001) mewajibkan struktur organisasi bertanggal efektif:
legal entity, org unit, location, dan cost center berubah dari waktu ke
waktu, dan **laporan per tanggal X harus memakai struktur yang berlaku
saat itu** — reorganisasi masa depan tidak boleh mengubah laporan lama.
Sprint 1 hanya menyimpan master data organisasi tanpa versi.

## Keputusan

Pola **tabel identitas + tabel info berversi** (bukan satu tabel
berversi langsung):

- `legal_entities` / `org_units` / `locations` / `cost_centers`:
  identitas stabil — hanya `id` + `tenant_id`. ID inilah yang dirujuk
  FK dari `JobInfo`/`Employment`, sehingga referensi historis tidak
  pernah patah saat nama/parent berubah.
- `legal_entity_info` / `org_unit_info` / `location_info` /
  `cost_center_info`: atribut berversi (`EffectiveDatedMixin` +
  kolom spesifik). Setiap perubahan (rename, pindah parent, pindah
  legal entity, nonaktif) = **record baru**, bukan UPDATE — memakai
  `effective_dating.insert_record` yang sama dengan JobInfo/CompInfo
  (ADR-0001, PLT-010).

Aturan bisnis yang ditegakkan di `app/services/org.py` + API:

1. **Pindah parent = versi baru.** Chart historis per tanggal otomatis
   benar karena `build_chart(as_of)` membaca versi yang berlaku.
2. **Siklus ditolak.** `assert_no_cycle` menelusuri rantai parent per
   tanggal validitas; parent sirkular (termasuk diri sendiri) → 422.
3. **Unit berpenghuni tidak bisa dinonaktifkan.** Versi dengan
   `is_active=False` ditolak (422 + pesan jelas) bila masih ada
   employment aktif yang org_unit-nya unit tersebut — cegah data
   yatim; pindahkan dulu karyawannya.
4. **Chart hanya menampilkan unit aktif** per tanggal yang diminta;
   unit nonaktif hilang dari pohon tetapi riwayatnya tetap ada di
   timeline.

## Alternatif yang dipertimbangkan

1. **Satu tabel berversi dengan parent_id menunjuk versi** — referensi
   antar-versi rapuh (versi baru memutus rantai lama); ditolak.
2. **Adjacency list tanpa versi (Sprint 1)** — tidak memenuhi CHR-001.
3. **Closure table / materialized path** — query subtree lebih cepat,
   tetapi menambah tabel turunan yang harus dijaga konsistensinya di
   setiap versi; hierarki HRIS dangkal (≤6 level) sehingga penelusuran
   Python per-request cukup.

## Konsekuensi

- Endpoint baca S1 (`GET /org/units` dsb.) dipertahankan dengan kontrak
  aditif: field lama sama, ditambah info versi.
- Endpoint baru: create + `/versions` + `/timeline` per entitas, dan
  `GET /org/chart?as_of=YYYY-MM-DD`.
- Seed membuat versi awal 2022-01-01 untuk seluruh struktur demo.
