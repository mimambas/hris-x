# ADR-0003: Strategi Multi-Tenant

Tanggal: 2026-09-30 · Sprint 1 · Status: diterima

## Konteks

PRD 15.9 (PLT-080) mewajibkan isolasi tenant via `tenant_id` di semua tabel
dan row-level security Postgres. PRD 18.1 menetapkan modular monolith
dengan satu database bersama sebagai default, dengan opsi single-tenant
untuk klien yang mensyaratkannya.

## Keputusan

- **Satu database, satu skema.** Semua tabel bisnis (kecuali `tenants`
  sendiri) punya kolom `tenant_id` + ForeignKey ke `tenants.id`, termasuk
  tabel bertanggal efektif (`job_info`, `comp_info`) agar filter isolasi
  tidak butuh join.
- **Penegakan di lapisan aplikasi pada S1**: setiap query bisnis memfilter
  `tenant_id` dari JWT; endpoint mengembalikan 404 (bukan 403) untuk objek
  tenant lain agar tidak membocorkan keberadaan data.
- **Postgres RLS adalah hardening produksi** (S2+), bukan S1: policy
  `USING (tenant_id = current_setting('app.tenant_id')::uuid)` per tabel
  bisnis, dengan `SET app.tenant_id` per koneksi/request. Aplikasi tetap
  memfilter di query sebagai pertahanan berlapis.
- **Primary key UUIDv7** (PRD 18.4 aturan 7): terurut waktu, aman dibuat di
  aplikasi tanpa round-trip DB, dan tidak membocorkan urutan/auto-increment
  lintas tenant. Diimplementasikan manual di `app/core/ids.py` (Python
  3.12 belum punya `uuid.uuid7()`); tipe kolom `sqlalchemy.Uuid` yang
  portabel Postgres ↔ SQLite.
- **Uang sebagai integer rupiah** di JSON komponen (PRD 18.4 aturan 3);
  divalidasi di API (`422` bila bukan integer).

## Alternatif yang dipertimbangkan

1. **Skema per tenant** — isolasi kuat, tetapi migrasi × N tenant dan
   operasional berat untuk tim kecil; ditolak untuk default SaaS.
2. **Database per tenant** — opsi untuk klien enterprise yang
   mensyaratkan (F3, single-tenant); codebase sama, connection routing
   per tenant. Tidak dikerjakan di S1.
3. **RLS sejak hari pertama** — ideal, tetapi RLS + connection pooling +
   migrasi menambah kompleksitas saat fondasi lain (effective dating, RBP)
   belum stabil. Dijadwalkan S2 bersama uji penetrasi lintas tenant.

## Konsekuensi

- Test isolasi tenant (test_tenant_isolation.py) adalah gerbang regresi:
  user tenant A tidak bisa membaca/menulis data tenant B.
- Semua endpoint baru WAJIB memfilter `tenant_id`; ini dikawal oleh
  code review + pola `require_permission` (belum ada linter otomatis —
  backlog).
