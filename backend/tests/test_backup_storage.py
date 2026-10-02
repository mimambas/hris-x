"""Test infrastruktur backup/restore + abstraksi object storage.

- StorageBackend local: round-trip save/load/delete, kompatibilitas kunci
  lama tanpa prefix.
- Cloudinary backend: dimock (tanpa kredensial asli).
- Endpoint /admin/backup: otorisasi superadmin, struktur dump valid,
  ekspor tercatat di audit.
- Skrip restore_backup.py: round-trip dump -> SQLite kosong -> verifikasi.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

from app.services import storage as storage_service

from .conftest import login_headers  # noqa: F401


# ---------------------------------------------------------- storage lokal
def test_local_storage_roundtrip(tmp_path):
    backend = storage_service.LocalStorageBackend(base_dir=tmp_path)
    key = backend.save("tenant-1", "cv.pdf", b"isi-berkas", "application/pdf")
    assert key.startswith("local:")
    assert backend.load(key) == b"isi-berkas"
    backend.delete(key)
    with pytest.raises(FileNotFoundError):
        backend.load(key)


def test_local_storage_kunci_lama_tanpa_prefix(tmp_path):
    backend = storage_service.LocalStorageBackend(base_dir=tmp_path)
    (tmp_path / "t1").mkdir()
    (tmp_path / "t1" / "lama.pdf").write_bytes(b"lama")
    assert backend.load("t1/lama.pdf") == b"lama"
    assert storage_service.scheme_of("t1/lama.pdf") == "local"
    assert storage_service.scheme_of("cloudinary:abc") == "cloudinary"


def test_get_storage_default_local(tmp_path, monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    assert isinstance(storage_service.get_storage(),
                      storage_service.LocalStorageBackend)


def test_cloudinary_tanpa_url_gagal_jelas(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "cloudinary")
    monkeypatch.delenv("CLOUDINARY_URL", raising=False)
    with pytest.raises(RuntimeError):
        storage_service.get_storage()


def _mock_cloudinary(monkeypatch):
    fake = types.ModuleType("cloudinary")
    uploaded = {}

    class _Uploader:
        @staticmethod
        def upload(data, **kw):
            uploaded["kw"] = kw
            return {"public_id": kw["public_id"]}

        @staticmethod
        def destroy(public_id, **kw):
            uploaded["destroyed"] = public_id

    class _Utils:
        @staticmethod
        def cloudinary_url(public_id, **kw):
            uploaded["signed_kw"] = kw
            return ("https://signed.example/" + public_id, None)

    fake.uploader = _Uploader
    fake.utils = _Utils
    fake.config = lambda **kw: None
    monkeypatch.setitem(sys.modules, "cloudinary", fake)
    monkeypatch.setitem(sys.modules, "cloudinary.uploader", types.ModuleType("x"))
    monkeypatch.setitem(sys.modules, "cloudinary.api", types.ModuleType("y"))
    return uploaded


def test_cloudinary_backend_dimock(monkeypatch):
    uploaded = _mock_cloudinary(monkeypatch)
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://k:s@demo")
    backend = storage_service.CloudinaryStorageBackend()
    key = backend.save("tenant-9", "struk.png", b"PNG", "image/png")
    assert key.startswith("cloudinary:hris-x/tenant-9/")
    # Upload harus privat (authenticated), bukan publik.
    assert uploaded["kw"]["type"] == "authenticated"
    backend.delete(key)
    assert uploaded["destroyed"] in key


# ---------------------------------------------------------- endpoint backup
def _admin_headers(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def test_backup_info_hanya_superadmin(client, ctx):
    r = client.get("/api/v1/admin/backup/info", headers=_admin_headers(client))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_rows"] > 0
    assert any(t["table"] == "persons" for t in body["tables"])

    staff = login_headers(client, "hashiru", "u_staff@x.id")
    r2 = client.get("/api/v1/admin/backup/info", headers=staff)
    assert r2.status_code == 403

    r3 = client.get("/api/v1/admin/backup/info")
    assert r3.status_code == 401


def test_backup_export_dump_valid_dan_diaudit(client, ctx, tmp_path):
    r = client.get("/api/v1/admin/backup/export", headers=_admin_headers(client))
    assert r.status_code == 200, r.text
    assert "attachment" in r.headers["content-disposition"]
    dump = json.loads(r.content.decode("utf-8"))
    assert dump["format"] == "hrisx-backup/1"
    assert dump["tables"]["persons"], "dump harus memuat persons"
    # Setiap baris persons tenant ini.
    for row in dump["tables"]["persons"]:
        assert row["tenant_id"] == dump["tenant_id"]

    # Ekspor tercatat di audit.
    r2 = client.get(
        "/api/v1/audit-logs",
        params={"object_type": "backup"},
        headers=_admin_headers(client),
    )
    assert r2.status_code == 200, r2.text
    entries = [e for e in r2.json() if e["action"] == "export"]
    assert entries, "ekspor backup harus tercatat di audit log"


def test_backup_export_non_admin_ditolak(client, ctx):
    staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get("/api/v1/admin/backup/export", headers=staff)
    assert r.status_code == 403


# ---------------------------------------------------------- skrip restore
def test_restore_roundtrip_ke_sqlite_kosong(client, ctx, tmp_path):
    import subprocess

    dump_file = tmp_path / "dump.json"
    r = client.get("/api/v1/admin/backup/export", headers=_admin_headers(client))
    assert r.status_code == 200
    dump_file.write_bytes(r.content)
    dump = json.loads(dump_file.read_text())
    n_persons = len(dump["tables"]["persons"])
    assert n_persons > 0
    # Baris tenants wajib ikut di dump (akar semua FK tenant_id).
    assert dump["tenant"]["id"] == dump["tenant_id"]
    assert dump["tenant"]["slug"] == "hashiru"

    target = tmp_path / "restore.db"
    env = {
        "DATABASE_URL": f"sqlite:///{target}",
        "PATH": "/usr/bin:/bin",
    }
    proc = subprocess.run(
        [sys.executable, "scripts/restore_backup.py", str(dump_file)],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "RESTORE OK" in proc.stdout
    assert f"verifikasi persons: dump={n_persons} db={n_persons} OK" in proc.stdout
    assert "verifikasi tenants: OK" in proc.stdout
    # Baris tenants benar-benar ada di target (SQLite tidak enforce FK,
    # jadi cek eksplisit — di Postgres kegagalan ini fatal).
    import sqlite3

    con = sqlite3.connect(target)
    try:
        row = con.execute("SELECT slug, name FROM tenants").fetchone()
    finally:
        con.close()
    assert row == ("hashiru", "Hashiru")

    # Target yang sudah berisi data ditolak tanpa --force.
    proc2 = subprocess.run(
        [sys.executable, "scripts/restore_backup.py", str(dump_file)],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc2.returncode == 3


def test_restore_roundtrip_ke_postgres_kosong(client, ctx, tmp_path):
    """Round-trip dump -> Postgres KOSONG -> verifikasi jumlah baris.

    Bukti nyata restore di Postgres (bukan SQLite): dijalankan di CI dengan
    service postgres:16 (lihat .github/workflows/restore-verify.yml).
    Di-skip otomatis bila env HRISX_TEST_PG_URL tidak diset.
    """
    import subprocess

    pg_url = os.environ.get("HRISX_TEST_PG_URL", "").strip()
    if not pg_url:
        pytest.skip("HRISX_TEST_PG_URL tidak diset (butuh Postgres asli)")

    dump_file = tmp_path / "dump.json"
    r = client.get("/api/v1/admin/backup/export", headers=_admin_headers(client))
    assert r.status_code == 200
    dump_file.write_bytes(r.content)
    dump = json.loads(dump_file.read_text())
    n_persons = len(dump["tables"]["persons"])
    assert n_persons > 0
    # Baris tenants wajib ikut di dump (akar semua FK tenant_id).
    assert dump["tenant"]["id"] == dump["tenant_id"]
    assert dump["tenant"]["slug"] == "hashiru"

    env = {"DATABASE_URL": pg_url, "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, "scripts/restore_backup.py", str(dump_file)],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "RESTORE OK" in proc.stdout
    assert "verifikasi tenants: OK" in proc.stdout
    assert f"verifikasi persons: dump={n_persons} db={n_persons} OK" in proc.stdout


def test_backup_export_generator_pulihkan_konteks_tenant(client, ctx):
    """Regresi bug 2026-10-01 (staging Postgres): setiap next() pada generator
    StreamingResponse berjalan di worker thread dengan SALINAN BARU konteks
    dari event loop, yang ContextVar tenant-nya sudah direset middleware.
    Akibatnya transaksi DB pertama di dalam generator tidak mendapat
    SET LOCAL app.tenant_id dan RLS memfilter SEMUA baris (64 tabel kosong).
    _iter_rows wajib me-set ulang konteks tepat sebelum db.execute."""
    from starlette.requests import Request

    from app.api.v1 import backup as backup_api
    from app.core.rls import (
        clear_request_tenant_id,
        current_tenant_id,
        set_request_tenant_id,
    )
    from app.models import Tenant, User

    db = ctx["db"]
    ta = db.query(Tenant).filter_by(slug="hashiru").one()
    admin = db.query(User).filter_by(email="admin_a@x.id").one()

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/v1/admin/backup/export",
        "headers": [],
        "client": ("127.0.0.1", 1234),
    }
    set_request_tenant_id(ta.id)
    resp = backup_api.export_backup(Request(scope), False, admin, db)
    # Simulasi middleware: finally mereset konteks sebelum body terkirim.
    clear_request_tenant_id()
    assert current_tenant_id.get() is None

    async def _consume():
        parts = []
        async for chunk in resp.body_iterator:
            parts.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
        return b"".join(parts)

    import anyio

    # Spy: pastikan generator me-set ulang konteks tenant saat dikonsumsi
    # (di konteks thread worker tempat StreamingResponse berjalan).
    calls = []
    real_set = backup_api.set_request_tenant_id
    backup_api.set_request_tenant_id = lambda tid: calls.append(str(tid)) or real_set(tid)
    try:
        body = anyio.run(_consume)
    finally:
        backup_api.set_request_tenant_id = real_set
    assert calls and calls[0] == str(ta.id), "generator harus me-set ulang tenant"
    dump = json.loads(body.decode("utf-8"))
    assert dump["format"] == "hrisx-backup/1"
    assert dump["tables"]["persons"], "dump harus memuat persons"
