"""Engine & session SQLAlchemy.

Satu database untuk semua tenant (modular monolith, PRD 18.1).
Isolasi tenant ditegakkan di lapisan aplikasi (semua query bisnis
memfilter tenant_id); Postgres RLS adalah hardening produksi (ADR-0003).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_engine = None
_SessionLocal = None


def init_db(database_url: str):
    global _engine, _SessionLocal
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url == "sqlite://":
            kwargs["poolclass"] = StaticPool
    _engine = create_engine(database_url, **kwargs)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        raise RuntimeError("Database belum diinisialisasi. Panggil init_db() dulu.")
    return _engine


def new_session():
    return _SessionLocal()


def get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
