"""Konfigurasi aplikasi dari environment variables."""

from __future__ import annotations

import os


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./hrisx.db")


def get_secret_key() -> str:
    return os.environ.get("SECRET_KEY", "dev-only-secret-key-ganti-di-produksi")


JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))
