# ADR-0014: Bootstrap RLS Postgres via ContextVar + `after_begin`

Tanggal: 2026-10-01
Status: Diterima
Konteks: persiapan staging — known limitation Sprint 10 ("RLS Postgres belum
terverifikasi live") ditutup dengan menjalankan `migrations/001_rls.sql` di
Postgres staging. Saat persiapan itu ditemukan 3 cacat fatal pada mekanisme
`SET LOCAL` manual (`app/core/db.py::set_rls_tenant_id`):

1. `get_current_user` (deps.py) menjalankan `SET LOCAL app.tenant_id`
   *setelah* query User/Tenant — di bawah RLS
   (`FORCE ROW LEVEL SECURITY`, policy `tenant_id = app.current_tenant_id()`)
   query tanpa tenant ter-set mengembalikan 0 baris → **semua request
   terautentikasi 401** di Postgres.
2. `POST /auth/login` me-resolve tenant by slug *sebelum* SET LOCAL — tabel
   `tenants` juga punya policy RLS → **login gagal total** di Postgres.
3. `SET LOCAL` hilang setelah `db.commit()` di tengah request — query
   setelah commit berjalan **tanpa tenant** (policy memfilter habis /
   `WITH CHECK` menolak tulis).

## Keputusan

### A. Konteks tenant per-request via `ContextVar` + event `after_begin`

Modul baru `app/core/rls.py`:

- `current_tenant_id: ContextVar[str | None]` (default `None`).
- `set_request_tenant_id(tid)`: validasi ketat — hanya UUID valid
  (`uuid.UUID(str(tid))`, gagal → `raise ValueError`); simpan bentuk
  kanonis 36-char ke contextvar. `clear_request_tenant_id()` untuk reset.
- Handler `Session.after_begin(session, transaction, connection)`:
  bila `connection.dialect.name != "postgresql"` → return;
  bila contextvar `None` → return;
  bila tidak → `connection.exec_driver_sql(f"SET LOCAL app.tenant_id = '{tid}'")`.
  Didaftarkan **sekali** saat modul diimport
  (`event.listen(Session, "after_begin", _apply_rls_after_begin)`);
  `app/core/db.py` mengimpor modul ini sehingga registrasi terjadi untuk
  seluruh aplikasi. Aman dari injeksi SQL: hanya UUID tervalidasi yang
  disisipkan (bound parameter tidak didukung untuk perintah `SET`).

Mengapa `after_begin`, bukan SET LOCAL manual di awal request:

- Berlaku di **setiap awal transaksi baru**, termasuk transaksi setelah
  `commit()`/`rollback()` di tengah request → menutup cacat #3 secara
  struktural, bukan dengan disiplin pemanggil.
- Pemanggil cukup set contextvar *sebelum query DB pertama* — urutannya
  menjadi mustahil salah tempat selama dilakukan pre-query.
- No-op di SQLite (dev/test): handler keluar lebih awal; 193 test tetap
  hijau tanpa perubahan.

### B. Middleware reset per request (`app/main.py::create_app`)

Middleware HTTP ringan `rls_tenant_context`: `clear_request_tenant_id()` di
awal, `try: await call_next(request) finally: clear_request_tenant_id()`.
Higiene agar tenant tidak bocor antar-request pada worker async yang
dipakai ulang. Didaftarkan pertama → middleware terluar → `finally`-nya
jalan paling akhir.

### C. `get_current_user`: urutan baru (menutup cacat #1)

1. Decode JWT **tanpa query DB** (fungsi yang sudah ada di
   `app/core/security.py`); ambil klaim `tenant_id`.
2. `set_request_tenant_id(tenant_id_dari_jwt)`.
3. Baru query User & Tenant (berjalan di bawah RLS).
4. Tetap verifikasi `user.tenant_id == tenant.id` (defense in depth:
   klaim JWT cocok dengan baris DB yang lolos policy).

Pemanggilan `set_rls_tenant_id` lama dihapus; fungsinya dipertahankan di
`app/core/db.py` sebagai alias legacy yang kini delegasi ke
`set_request_tenant_id` (kompatibilitas pemanggil lama).

### D. `tenants` dikecualikan dari RLS (menutup cacat #2)

`migrations/001_rls.sql`: `'tenants'` dihapus dari daftar tabel ber-policy,
ditambah (idempoten, aman untuk DB yang sudah dimigrasi versi lama):

```sql
DROP POLICY IF EXISTS tenant_isolation ON tenants;
ALTER TABLE tenants DISABLE ROW LEVEL SECURITY;
```

Rasional: tabel `tenants` hanya berisi `id`/`slug`/`nama`/`is_active` —
slug bersifat **semi-publik** (sudah terekspos di
`GET /public/jobs?tenant=<slug>`) dan wajib bisa di-resolve **sebelum**
autentikasi (pola bootstrap standar: login me-resolve tenant by slug
pre-auth). Tanpa pengecualian ini, tidak ada jalur login yang bisa bekerja
di bawah RLS. Di endpoint login: setelah tenant ter-resolve dari slug →
`set_request_tenant_id(tenant.id)` → baru query `users` (yang tetap kena
RLS).

### E. Format token offer publik: `<tenant_hex32>.<random>`

`send_offer` kini menerbitkan
`f"{tenant_id.hex}.{secrets.token_urlsafe(32)}"` (32 char hex tanpa dash +
titik + 43 char random). `POST /public/offers/{token}/accept`:
split token di `'.'`, validasi bagian pertama sebagai UUID via
`set_request_tenant_id` (gagal → 404) → query offer by token penuh.
Token tetap tak tertebak (bagian random 256-bit; prefix tenant bukan
rahasia — slug tenant memang publik). Kolom `offer_token` diperlebar
`String(64)` → `String(128)` (76 char dibutuhkan).

`GET /public/jobs` sudah resolve tenant dari slug; kini memakai
`set_request_tenant_id` (contextvar) agar konsisten.

## Catatan untuk skrip batch

Skrip yang jalan **langsung ke Postgres di luar request HTTP**
(`scripts/seed.py`, skrip `demo_*`) **tidak** mendapat konteks otomatis —
contextvar kosong. Mereka HARUS menyetel GUC manual per transaksi/sesi:

```sql
SET LOCAL app.tenant_id = '<tenant-uuid>';  -- per transaksi
-- atau
SET app.tenant_id = '<tenant-uuid>';         -- per sesi (hati-hati pool)
```

atau dijalankan sebelum `migrations/001_rls.sql` diterapkan.
`migrations/verify_rls.py` memang memakai pola manual ini dan tetap valid.

## Konsekuensi

- Staging Postgres: RLS kini benar-benar berfungsi end-to-end —
  known limitation Sprint 10 tertutup (verifikasi live tetap via
  `migrations/verify_rls.py` + smoke test login).
- Kontrak API tidak berubah; format `offer_token` berubah (token lama yang
  sudah terkirim sebelum deploy ini menjadi tidak valid — dapat diterima
  untuk fase staging; di produksi nanti butuh masa transisi bila token
  sudah beredar).
- Tidak ada dependensi baru; overhead per transaksi = satu `SET LOCAL`
  (murah, round-trip yang sama dengan koneksi).
