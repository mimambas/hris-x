"""Konfigurasi aplikasi dari environment variables."""

from __future__ import annotations

import os


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./hrisx.db")


# Sprint 10: SECRET_KEY default yang ditolak saat ENV=production.
DEFAULT_SECRET_KEY = "dev-only-secret-key-ganti-di-produksi"


def get_secret_key() -> str:
    return os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)


def get_env() -> str:
    """Lingkungan berjalan: development | staging | production."""
    return os.environ.get("ENV", "development").strip().lower()


def get_allowed_origins() -> list[str]:
    """Daftar origin CORS dari env ALLOWED_ORIGINS (koma-dipisah).

    Default kosong = TIDAK ADA CORS (same-origin saja). Lihat ADR-0013.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))


def get_upload_dir() -> str:
    """Direktori penyimpanan berkas dokumen (struk, CV, dll).

    Default: <backend>/uploads. Di Vercel serverless, filesystem deployment
    read-only kecuali /tmp -> set UPLOAD_DIR=/tmp/hris-uploads agar upload
    tidak 500. Isi /tmp ephemeral (hilang saat instance didaur ulang);
    object storage persisten adalah solusi produksi (backlog infra).
    """
    return os.environ.get("UPLOAD_DIR", "").strip()
