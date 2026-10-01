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
from app.models import Base, User
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


def _generate_dump(db: Session, tenant_id: uuid.UUID):
    yield '{"format": ' + json.dumps(BACKUP_FORMAT)
    yield ', "tenant_id": ' + json.dumps(str(tenant_id))
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
