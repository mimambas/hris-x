"""Konteks tenant per-request untuk Postgres RLS (ADR-0014).

Masalah yang dipecahkan
------------------------
Policy RLS (`migrations/001_rls.sql`) memaksa GUC ``app.tenant_id`` ter-set
*sebelum* query bisnis pertama dijalankan. Pendekatan lama (``SET LOCAL``
manual lewat ``set_rls_tenant_id`` di awal ``get_current_user`` / endpoint
publik) rapuh:

1. ``get_current_user`` me-resolve User/Tenant *dulu*, baru set tenant —
   di bawah RLS query tersebut mengembalikan 0 baris → 401 di Postgres.
2. Login me-resolve tenant by slug pre-auth — tabel ``tenants`` juga kena
   RLS → login gagal total di Postgres.
3. ``SET LOCAL`` hilang setelah ``db.commit()`` di tengah request — query
   setelah commit berjalan tanpa tenant.

Desain
------
Tenant id disimpan di ``ContextVar`` (``current_tenant_id``); handler event
SQLAlchemy ``after_begin`` — didaftarkan SEKALI saat modul ini diimport —
menjalankan ``SET LOCAL app.tenant_id = '<uuid>'`` di setiap awal transaksi
baru, termasuk transaksi setelah ``commit()``/``rollback()`` di tengah
request. Aman dari injeksi SQL: hanya UUID yang sudah tervalidasi ketat
yang disisipkan ke string SQL (bound parameter tidak didukung untuk
perintah ``SET`` di semua driver).

Penggunaan:

- Request HTTP: middleware ``rls_tenant_context`` di ``app/main.py``
  me-reset contextvar di awal & akhir setiap request (higiene anti-bocor
  antar-request pada worker async yang dipakai ulang).
- ``get_current_user``: decode JWT dulu (tanpa DB) → ambil klaim
  ``tenant_id`` → ``set_request_tenant_id()`` → baru query User/Tenant.
- Login: tenant di-resolve dari slug (tabel ``tenants`` dikecualikan dari
  RLS — lihat ADR-0014) → ``set_request_tenant_id()`` → baru query user.
- Endpoint publik ``/public/jobs`` & accept offer: set tenant dari
  slug / prefix token sebelum query pertama.
- Skrip batch (``scripts/seed.py``, demo) yang jalan langsung ke Postgres
  HARUS set GUC manual (``SET LOCAL app.tenant_id = ...`` per transaksi
  atau ``SET`` per sesi) — contextvar tidak terisi di luar request HTTP.

No-op di SQLite (dev/test): handler keluar lebih awal bila dialect bukan
``postgresql`` dan contextvar kosong, sehingga 193 test tetap hijau tanpa
perubahan.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.orm import Session

# Tenant aktif untuk request saat ini (None = belum diidentifikasi /
# request anonim). ContextVar => aman untuk concurrency async.
current_tenant_id: ContextVar[str | None] = ContextVar(
    "hrisx_current_tenant_id", default=None
)


def set_request_tenant_id(tid: str | uuid.UUID | None) -> str:
    """Set tenant id request saat ini, dengan validasi ketat.

    Hanya menerima UUID valid (``str`` 32/36 char atau objek ``UUID``);
    nilai lain — termasuk ``None`` — menaikkan ``ValueError`` agar
    pemanggil bisa mengubahnya menjadi 401/404 sesuai konteks.
    Mengembalikan representasi string kanonis (36 char dengan dash).

    Untuk me-reset (akhir request), pakai ``clear_request_tenant_id()``.
    """
    if tid is None:
        raise ValueError("tenant_id tidak boleh None")
    try:
        parsed = tid if isinstance(tid, uuid.UUID) else uuid.UUID(str(tid))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"tenant_id bukan UUID valid: {tid!r}") from exc
    canonical = str(parsed)
    current_tenant_id.set(canonical)
    return canonical


def clear_request_tenant_id() -> None:
    """Reset konteks tenant ke None (dipakai middleware HTTP per request)."""
    current_tenant_id.set(None)


def _apply_rls_after_begin(session, transaction, connection) -> None:
    """Handler ``Session.after_begin``: SET LOCAL app.tenant_id per transaksi.

    Dijalankan setiap transaksi baru dimulai — termasuk transaksi setelah
    ``commit()``/``rollback()`` di tengah request — sehingga konteks RLS
    tidak pernah hilang di tengah request (masalah #3 desain lama).
    """
    if connection.dialect.name != "postgresql":
        return
    tid = current_tenant_id.get()
    if tid is None:
        return
    # `tid` sudah tervalidasi UUID di set_request_tenant_id() → aman
    # disisipkan langsung ke string SQL.
    connection.exec_driver_sql(f"SET LOCAL app.tenant_id = '{tid}'")


# Daftarkan sekali saat modul diimport. `app/core/db.py` mengimpor modul
# ini sehingga registrasi terjadi untuk seluruh aplikasi.
event.listen(Session, "after_begin", _apply_rls_after_begin)
