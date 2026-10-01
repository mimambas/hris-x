"""Engine & session SQLAlchemy.

Satu database untuk semua tenant (modular monolith, PRD 18.1).
Isolasi tenant ditegakkan di lapisan aplikasi (semua query bisnis
memfilter tenant_id); Postgres RLS adalah hardening produksi (ADR-0003).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

# Impor agar event handler after_begin (SET LOCAL app.tenant_id per
# transaksi) terdaftar sekali untuk seluruh aplikasi. Lihat ADR-0014.
from app.core.rls import clear_request_tenant_id, set_request_tenant_id  # noqa: F401

_engine = None
_SessionLocal = None


def init_db(database_url: str):
    global _engine, _SessionLocal
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url == "sqlite://":
            kwargs["poolclass"] = StaticPool
    # Serverless (Vercel): DB_POOL=null → NullPool agar koneksi tidak dipegang
    # antar-invocation. Tidak berlaku untuk SQLite agar dev/test tidak berubah.
    if (not database_url.startswith("sqlite")
            and os.environ.get("DB_POOL", "").strip().lower() == "null"):
        kwargs["poolclass"] = NullPool
    _engine = create_engine(database_url, **kwargs)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        raise RuntimeError("Database belum diinisialisasi. Panggil init_db() dulu.")
    return _engine


def new_session():
    return _SessionLocal()


def set_rls_tenant_id(db: Session, tenant_id) -> None:
    """(Legacy) Set tenant untuk RLS Postgres.

    Sekarang delegasi ke ``app.core.rls.set_request_tenant_id``: handler
    ``after_begin`` menerapkan ``SET LOCAL app.tenant_id`` otomatis di
    setiap awal transaksi — termasuk setelah ``db.commit()`` di tengah
    request. Disimpan untuk kompatibilitas pemanggil lama; kode baru
    memakai ``set_request_tenant_id`` langsung.
    """
    set_request_tenant_id(tenant_id)


def get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
