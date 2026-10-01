"""Abstraksi penyimpanan berkas dokumen.

Backend yang tersedia:
- ``local``      : filesystem (default; cocok untuk dev & fallback).
- ``cloudinary`` : Cloudinary (akun gratis, tanpa kartu kredit) untuk
  penyimpanan durable di serverless (Vercel). Butuh env ``CLOUDINARY_URL``
  dan paket ``cloudinary``.

Kunci penyimpanan (``Document.file_path``) memakai prefix skema agar
self-describing dan tahan pindah backend tanpa migrasi DB:
- ``local:<relpath>``      mis. ``local:9f3c.../ab12_cv.pdf``
- ``cloudinary:<public_id>`` mis. ``cloudinary:hris-x/9f3c.../ab12_cv``
Baris lama tanpa prefix dianggap ``local:`` (kompatibel mundur).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Protocol


class StorageBackend(Protocol):
    def save(
        self, tenant_id: str, filename: str, data: bytes, mime_type: str
    ) -> str:
        """Simpan berkas; kembalikan kunci penyimpanan (dengan prefix skema)."""
        ...

    def load(self, key: str) -> bytes:
        """Baca berkas; raise FileNotFoundError bila tidak ada."""
        ...

    def delete(self, key: str) -> None:
        """Hapus berkas; abaikan bila tidak ada."""
        ...


def _upload_dir() -> Path:
    from app.core.config import get_upload_dir

    base = get_upload_dir()
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent.parent / "uploads"


class LocalStorageBackend:
    scheme = "local"

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or _upload_dir()

    def save(
        self, tenant_id: str, filename: str, data: bytes, mime_type: str
    ) -> str:
        stored = f"{uuid.uuid4().hex}_{filename}"
        tenant_dir = self.base_dir / str(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        (tenant_dir / stored).write_bytes(data)
        return f"local:{tenant_id}/{stored}"

    def load(self, key: str) -> bytes:
        rel = _strip_scheme(key, "local")
        path = self.base_dir / rel
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        rel = _strip_scheme(key, "local")
        path = self.base_dir / rel
        if path.is_file():
            path.unlink()


class CloudinaryStorageBackend:
    """Penyimpanan Cloudinary untuk file privat.

    Upload memakai ``type="authenticated"`` sehingga berkas TIDAK bisa
    diakses lewat URL publik; unduhan selalu diproksi lewat endpoint
    backend yang berautentikasi. Folder: ``hris-x/<tenant_id>``.
    """

    scheme = "cloudinary"

    def __init__(self) -> None:
        try:
            import cloudinary
            import cloudinary.uploader
            import cloudinary.api  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Paket 'cloudinary' belum terinstal; "
                "tambah ke requirements atau set STORAGE_BACKEND=local."
            ) from exc
        url = os.environ.get("CLOUDINARY_URL", "").strip()
        if not url:
            raise RuntimeError(
                "CLOUDINARY_URL belum diset untuk STORAGE_BACKEND=cloudinary."
            )
        cloudinary.config(cloudinary_url=url, secure=True)
        self._cloudinary = cloudinary

    def save(
        self, tenant_id: str, filename: str, data: bytes, mime_type: str
    ) -> str:
        public_id = f"hris-x/{tenant_id}/{uuid.uuid4().hex}_{Path(filename).stem}"
        result = self._cloudinary.uploader.upload(
            data,
            public_id=public_id,
            resource_type="auto",
            type="authenticated",
            filename=filename,
        )
        return f"cloudinary:{result['public_id']}"

    def load(self, key: str) -> bytes:
        import urllib.request

        public_id = _strip_scheme(key, "cloudinary")
        # Unduh server-side via URL bertanda tangan (tetap privat).
        url, _ = self._cloudinary.utils.cloudinary_url(
            public_id,
            resource_type="auto",
            type="authenticated",
            sign_url=True,
        )
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    def delete(self, key: str) -> None:
        public_id = _strip_scheme(key, "cloudinary")
        self._cloudinary.uploader.destroy(
            public_id, resource_type="auto", type="authenticated"
        )


def _strip_scheme(key: str, scheme: str) -> str:
    prefix = f"{scheme}:"
    if key.startswith(prefix):
        return key[len(prefix):]
    return key


def scheme_of(key: str) -> str:
    if key.startswith("cloudinary:"):
        return "cloudinary"
    return "local"


def get_storage(scheme: str | None = None) -> StorageBackend:
    """Backend penyimpanan untuk upload baru.

    ``scheme`` default diambil dari env ``STORAGE_BACKEND`` (``local``).
    """
    name = (scheme or os.environ.get("STORAGE_BACKEND", "local")).strip().lower()
    if name == "cloudinary":
        return CloudinaryStorageBackend()
    return LocalStorageBackend()


def load_key(key: str) -> bytes:
    """Baca berkas memakai backend sesuai skema kunci (untuk unduhan)."""
    if scheme_of(key) == "cloudinary":
        return CloudinaryStorageBackend().load(key)
    return LocalStorageBackend().load(key)


def delete_key(key: str) -> None:
    """Hapus berkas memakai backend sesuai skema kunci."""
    if scheme_of(key) == "cloudinary":
        CloudinaryStorageBackend().delete(key)
    else:
        LocalStorageBackend().delete(key)
