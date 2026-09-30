"""Impor karyawan dari Excel (CHR-007): template, dry-run, commit atomik."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import User
from app.schemas.schemas import (
    ImportCommitResponse,
    ImportDryRunResponse,
)
from app.services import imports as import_service
from app.services.imports import ImportValidationError, build_template

router = APIRouter(tags=["imports"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TEMPLATE_FILENAME = "template_impor_karyawan.xlsx"


def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    name = (file.filename or "").strip()
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Berkas harus Excel (.xlsx)",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Berkas kosong"
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Berkas melebihi batas {MAX_UPLOAD_BYTES // 1024 // 1024} MB",
        )
    return name, data


@router.get(
    "/imports/employees/template",
    dependencies=[Depends(require_permission("import", "view"))],
)
def download_template():
    data = build_template()
    return StreamingResponse(
        iter([data]),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f"attachment; filename={TEMPLATE_FILENAME}"},
    )


@router.post(
    "/imports/employees/dry-run",
    response_model=ImportDryRunResponse,
    dependencies=[Depends(require_permission("import", "insert"))],
)
def dry_run_import(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validasi semua baris TANPA menulis database. Laporan per baris."""
    filename, data = _read_upload(file)
    try:
        _, report = import_service.validate_all(db, user.tenant_id, filename, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return report


@router.post(
    "/imports/employees/commit",
    response_model=ImportCommitResponse,
    dependencies=[Depends(require_permission("import", "insert"))],
)
def commit_import(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Commit atomik: validasi-semua-dulu; gagal satu baris -> 422, DB utuh."""
    filename, data = _read_upload(file)
    try:
        return import_service.commit(
            db, user.tenant_id, user, filename, data,
            ip=client_ip(request) if request else None,
        )
    except ImportValidationError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.report.model_dump(mode="json"),
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
