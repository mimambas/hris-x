"""Backup level aplikasi: ekspor JSON seluruh data tenant.

- ``GET /admin/backup/info``   : ringkasan (jumlah baris per tabel, backend storage).
- ``GET /admin/backup/export`` : unduh dump JSON tenant (streaming).

Hanya superadmin. Setiap ekspor dicatat di audit log. Dump dapat
dimuat kembali dengan ``backend/scripts/restore_backup.py`` (untuk uji
restore ke database kosong, mis. Neon branch baru).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.rls import set_request_tenant_id
from app.models import Base, Tenant, User
from app.services import storage as storage_service
from app.services.audit import write_audit

router = APIRouter(prefix="/admin/backup", tags=["admin-backup"])

BACKUP_FORMAT = "hrisx-backup/1"


def _require_superadmin(user: User) -> None:
    if not user.is_superadmin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Hanya superadmin yang dapat mengakses backup."
        )


def _tenant_mappers():
    """Mapper SQLAlchemy yang punya kolom tenant_id, urut dependensi FK."""
    tables = Base.metadata.sorted_tables
    out = []
    for table in tables:
        if "tenant_id" not in table.c:
            continue
        for mapper in Base.registry.mappers:
            if mapper.persist_selectable is table:
                out.append((table.name, mapper.class_))
                break
    return out


def _serialize(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return value


def _iter_rows(db: Session, model, tenant_id: uuid.UUID):
    # Dipanggil dari generator streaming: SETIAP pemanggilan next() pada
    # generator berjalan di worker thread dengan SALINAN BARU konteks dari
    # event loop (yang ContextVar tenant-nya sudah direset middleware).
    # Akibatnya set di awal gen() tidak bertahan sampai transaksi DB
    # pertama dimulai -> after_begin RLS tidak menjalankan SET LOCAL ->
    # Postgres mengembalikan 0 baris (bug 2026-10-01). Set ulang di sini,
    # tepat sebelum db.execute, agar transaksi pertama melihat tenant.
    set_request_tenant_id(tenant_id)
    stmt = select(model).where(model.tenant_id == tenant_id)
    for row in db.execute(stmt).scalars():
        yield {
            col.name: _serialize(getattr(row, col.name))
            for col in row.__table__.columns
        }


def _tenant_payload(db: Session, tenant_id: uuid.UUID):
    """Baris tenants milik tenant ini, untuk dimasukkan ke dump.

    Tabel `tenants` tidak punya kolom tenant_id (ia adalah akar semua FK
    tenant_id), jadi tidak ikut _tenant_mappers/_iter_rows. Tanpa baris ini,
    restore ke database kosong gagal di Postgres asli: setiap INSERT ke
    63 tabel lain melanggar FK -> tenants.id (di SQLite lolos diam-diam
    karena FK tidak dienforce — bug 2026-10-02, ditemukan CI
    restore-verify). Tabel tenants dikecualikan dari RLS (ADR-0014).
    """
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return None
    return {
        col.name: _serialize(getattr(tenant, col.name))
        for col in Tenant.__table__.columns
    }


def _generate_dump(db: Session, tenant_id: uuid.UUID):
    yield '{"format": ' + json.dumps(BACKUP_FORMAT)
    yield ', "tenant_id": ' + json.dumps(str(tenant_id))
    yield ', "tenant": ' + json.dumps(_tenant_payload(db, tenant_id))
    yield ', "exported_at": ' + json.dumps(
        dt.datetime.now(dt.timezone.utc).isoformat()
    )
    yield ', "tables": {'
    first = True
    for table_name, model in _tenant_mappers():
        if not first:
            yield ", "
        first = False
        yield json.dumps(table_name) + ": ["
        row_first = True
        for row in _iter_rows(db, model, tenant_id):
            if not row_first:
                yield ", "
            row_first = False
            yield json.dumps(row, ensure_ascii=False)
        yield "]"
    yield "}}"


@router.get("/info")
def backup_info(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_superadmin(user)
    tables = []
    total = 0
    for table_name, model in _tenant_mappers():
        n = db.execute(
            select(model).where(model.tenant_id == user.tenant_id)
        ).scalars()
        count = sum(1 for _ in n)
        tables.append({"table": table_name, "rows": count})
        total += count
    return {
        "tenant_id": str(user.tenant_id),
        "storage_backend": os.environ.get("STORAGE_BACKEND", "local"),
        "tables": tables,
        "total_rows": total,
    }


@router.get("/export")
def export_backup(
    request: Request,
    include_files: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unduh dump JSON seluruh data tenant.

    ``include_files=true`` menyertakan isi berkas dokumen (base64 hex);
    default False agar unduhan tetap ringan (berkas di-storage terpisah).
    """
    _require_superadmin(user)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"hrisx-backup-{stamp}.json"

    def gen():
        # Konteks tenant juga di-set di awal sebagai dokumentasi niat;
        # jaminan sesungguhnya ada di _iter_rows (setiap next() generator
        # berjalan di salinan konteks baru tanpa ContextVar tenant).
        set_request_tenant_id(user.tenant_id)
        if not include_files:
            yield from _generate_dump(db, user.tenant_id)
            return
        # Varian dengan isi berkas: bungkus generator standar lalu sisipkan.
        # Disederhanakan: bangun dict per tabel dokumen dengan konten file.
        yield '{"format": ' + json.dumps(BACKUP_FORMAT)
        yield ', "tenant_id": ' + json.dumps(str(user.tenant_id))
        yield ', "tenant": ' + json.dumps(_tenant_payload(db, user.tenant_id))
        yield ', "exported_at": ' + json.dumps(
            dt.datetime.now(dt.timezone.utc).isoformat()
        )
        yield ', "include_files": true, "tables": {'
        first = True
        for table_name, model in _tenant_mappers():
            if not first:
                yield ", "
            first = False
            yield json.dumps(table_name) + ": ["
            row_first = True
            for row in _iter_rows(db, model, tenant_id=user.tenant_id):
                if not row_first:
                    yield ", "
                row_first = False
                if table_name == "documents":
                    try:
                        row["file_content_hex"] = storage_service.load_key(
                            row["file_path"]
                        ).hex()
                    except FileNotFoundError:
                        row["file_content_hex"] = None
                yield json.dumps(row, ensure_ascii=False)
            yield "]"
        yield "}}"

    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="export",
        object_type="backup",
        object_id=user.tenant_id,
        new_values={"include_files": include_files},
        reason="Ekspor backup data tenant",
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return StreamingResponse(
        gen(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/apply-rls")
def apply_rls(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Terapkan migrations/001_rls.sql ke database (idempoten).

    Hanya superadmin. SQL berasal dari file di codebase yang ter-deploy,
    BUKAN dari input user. Diperlukan setiap ada tabel baru ber-tenant_id
    (tanpa policy, tabel baru tidak terisolasi antar-tenant).
    """
    _require_superadmin(user)
    # app/api/v1/backup.py -> naik 3 level = direktori backend/.
    mig_path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "migrations", "001_rls.sql"))
    if not os.path.exists(mig_path):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            "File migrasi tidak ditemukan")
    with open(mig_path, "r", encoding="utf-8") as f:
        sql = f.read()
    # RLS migration hanya untuk Postgres; SQLite tidak mendukungnya.
    dialect = db.bind.dialect.name if db.bind else ""
    if dialect != "postgresql":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Migrasi RLS hanya untuk PostgreSQL")
    from sqlalchemy import text as _text
    conn = db.connection()

    def _split_statements(sql_text: str) -> list[str]:
        """Pecah skrip menjadi statement.

        Hormati blok dollar-quoted ($$...$$) dan abaikan ';' di dalam
        komentar baris (-- ...).
        """
        stmts, buf = [], []
        i, n = 0, len(sql_text)
        in_dollar = False
        while i < n:
            if sql_text.startswith("$$", i):
                in_dollar = not in_dollar
                buf.append("$$")
                i += 2
                continue
            if not in_dollar and sql_text.startswith("--", i):
                # Lewati komentar sampai akhir baris (tetap simpan agar
                # statement utuh, tapi ';' di dalamnya diabaikan).
                j = sql_text.find("\n", i)
                j = n if j == -1 else j
                buf.append(sql_text[i:j])
                i = j
                continue
            ch = sql_text[i]
            if ch == ";" and not in_dollar:
                stmt = "".join(buf).strip()
                if stmt:
                    stmts.append(stmt)
                buf = []
            else:
                buf.append(ch)
            i += 1
        tail = "".join(buf).strip()
        if tail:
            stmts.append(tail)
        # Buang statement yang murni komentar.
        out = []
        for s in stmts:
            code = [ln for ln in s.splitlines()
                    if ln.strip() and not ln.strip().startswith("--")]
            if code:
                out.append(s)
        return out

    for stmt in _split_statements(sql):
        try:
            conn.execute(_text(stmt))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Gagal menerapkan RLS: {e}") from e
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="apply",
        object_type="rls_migration",
        object_id=user.tenant_id,
        reason="Terapkan ulang policy RLS tenant",
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    # Verifikasi: daftar tabel yang kini punya policy tenant_isolation.
    rows = conn.execute(_text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND rowsecurity")).fetchall()
    return {"ok": True, "tables_with_rls": sorted(r[0] for r in rows)}
