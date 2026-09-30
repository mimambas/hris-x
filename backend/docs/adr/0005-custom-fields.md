# ADR-0005: Custom Field / Metadata Tanpa Deploy

Tanggal: 2026-09-30 · Sprint 2 · Status: diterima

## Konteks

PRD 9.2 (CHR-009) + 15.1 (PLT-001, PLT-003): admin harus bisa menambah
field sendiri per objek (person, employment, org unit, ...) **tanpa
perubahan skema/deploy**, langsung tersedia di API. Nonaktifkan definisi
tidak boleh menghapus data lama; hapus = soft delete + audit.

## Keputusan

Dua tabel + kolom bertipe (bukan JSON blob):

- `custom_field_definitions`: `object_name` (person/employment/org_unit/
  legal_entity/location/cost_center), `field_key` (unik per objek,
  snake_case), `label_id`/`label_en`, `field_type`
  (text/number/date/select/lookup/attachment), `required`, `options`
  (JSON), `is_active`, soft-delete via `is_active=False`.
- `custom_field_values`: satu baris per (definition_id, record_id) dengan
  **kolom bertipe** — `value_text`, `value_number` (Numeric 20,4),
  `value_date` — sesuai `field_type`. Bisa diindeks/difilter di DB,
  tidak seperti JSON blob.

Aturan validasi (`app/services/custom_fields.py`):

1. **select** wajib punya `options` picklist; setiap opsi punya
   `value` + `label_id`/`label_en` + flag `active`. Nilai yang ditulis
   harus cocok dengan opsi aktif (label dua bahasa ikut terbaca).
2. **lookup** memakai `options.target` (job/org_unit/location/
   legal_entity/cost_center/person); nilai harus UUID record yang ada
   di tenant yang sama — cegah nilai yatim.
3. **Nonaktif ≠ hapus.** Definisi nonaktif: nilai lama tetap terbaca
   (`definition_active=False` di respons), penulisan baru ditolak 422.
   DELETE endpoint = soft delete + audit; nilai tidak dihapus.
4. **Izin per field** (CHR-009): `FieldPermission` dengan
   `object_name` + `field_name="custom:<field_key>"`. Bila tidak ada
   baris spesifik, jatuh ke izin object-level `"*"`. Baris spesifik
   menang atas wildcard — deny eksplisit tidak bisa diakali.

## Alternatif yang dipertimbangkan

1. **JSONB satu kolom** — fleksibel tetapi tidak tervalidasi di DB,
   sulit difilter/diindeks per tipe; ditolak.
2. **EAV generik** — setara secara konsep; dipilih kolom bertipe
   eksplisit agar query dan validasi lebih sederhana.
3. **Deklarasi field di kode (tanpa definisi runtime)** — tidak
   memenuhi "tanpa deploy" (PLT-001).

## Konsekuensi

- Admin mengelola definisi lewat `POST/PATCH/DELETE
  /custom-fields/definitions` (perlu izin `custom_field` insert);
  nilai lewat `POST /custom-fields/values` dan
  `GET /custom-fields/values?object_name=&record_id=`.
- Objek yang didukung didaftar di `CUSTOM_FIELD_OBJECTS`; menambah
  objek baru = satu baris konstanta + (opsional) target lookup.
- Seed menyertakan definisi demo `person.ukuran_seragam` (select).
