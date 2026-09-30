"""Dokumen karyawan (CHR-012 dasar, tanpa e-sign).

Upload berversi per (person/employment, doc_type): versi lama tetap
tersimpan (is_current=False). Berkas disimpan di <backend>/uploads/
(ditentukan di .gitignore). Unduh & daftar memakai pemeriksaan RBP +
target population seperti endpoint person.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import DOCUMENT_TYPES, Document, Employment, Person, User
from app.schemas.schemas import DocumentOut
from app.services import population as pop_service
from app.services.audit import write_audit

router = APIRouter(tags=["documents"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx"}


def _subject_person_id(
    db: Session, user: User, person_id: uuid.UUID | None,
    employment_id: uuid.UUID | None,
) -> uuid.UUID:
    """Validasi subjek dokumen; kembalikan person_id untuk cek populasi."""
    if person_id is None and employment_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "person_id atau employment_id wajib diisi",
        )
    if person_id is not None:
        person = db.get(Person, person_id)
        if person is None or person.tenant_id != user.tenant_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Person tidak ditemukan")
    if employment_id is not None:
        emp = db.get(Employment, employment_id)
        if emp is None or emp.tenant_id != user.tenant_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Employment tidak ditemukan"
            )
        return emp.person_id
    return person_id


def _check_population(db: Session, user: User, subject_person_id: uuid.UUID) -> None:
    if not pop_service.can_view_person(db, user, subject_person_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan")


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("document", "insert"))],
)
def upload_document(
    request: Request,
    doc_type: str = Form(...),
    person_id: uuid.UUID | None = Form(None),
    employment_id: uuid.UUID | None = Form(None),
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc_type = (doc_type or "").strip().lower()
    if doc_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"doc_type harus salah satu: {', '.join(DOCUMENT_TYPES)}",
        )
    subject_person_id = _subject_person_id(db, user, person_id, employment_id)
    _check_population(db, user, subject_person_id)

    original = (file.filename or "").strip()
    ext = "." + original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Ekstensi '{ext or '?'}' tidak diizinkan "
            f"({', '.join(sorted(ALLOWED_EXT))})",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Berkas kosong"
        )
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Berkas melebihi batas {MAX_FILE_BYTES // 1024 // 1024} MB",
        )

    # Versi = max+1 dalam scope (person, employment, doc_type); lama nonaktif.
    existing = (
        db.execute(
            select(Document).where(
                Document.tenant_id == user.tenant_id,
                Document.person_id == person_id,
                Document.employment_id == employment_id,
                Document.doc_type == doc_type,
            )
        )
        .scalars()
        .all()
    )
    for old in existing:
        old.is_current = False
    version = max([d.version for d in existing], default=0) + 1

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", original) or "dokumen"
    stored = f"{uuid.uuid4().hex}_{safe_name}"
    tenant_dir = UPLOAD_DIR / str(user.tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    (tenant_dir / stored).write_bytes(data)

    doc = Document(
        tenant_id=user.tenant_id,
        person_id=person_id,
        employment_id=employment_id,
        doc_type=doc_type,
        file_name=original,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        file_path=str(Path(str(user.tenant_id)) / stored),
        version=version,
        is_current=True,
        notes=(notes or "").strip() or None,
        uploaded_by_user_id=user.id,
    )
    db.add(doc)
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="create",
        object_type="document",
        object_id=doc.id,
        new_values={"doc_type": doc_type, "file_name": original,
                    "version": version},
        reason=f"Upload dokumen {doc_type} v{version}",
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return doc


@router.get(
    "/documents",
    response_model=list[DocumentOut],
    dependencies=[Depends(require_permission("document", "view"))],
)
def list_documents(
    person_id: uuid.UUID | None = None,
    employment_id: uuid.UUID | None = None,
    doc_type: str | None = None,
    include_old: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Document).where(Document.tenant_id == user.tenant_id)
    if person_id is not None:
        stmt = stmt.where(Document.person_id == person_id)
    if employment_id is not None:
        stmt = stmt.where(Document.employment_id == employment_id)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type.strip().lower())
    if not include_old:
        stmt = stmt.where(Document.is_current == True)  # noqa: E712
    docs = db.execute(stmt.order_by(Document.created_at.desc())).scalars().all()
    # Saring populasi: hanya dokumen milik person yang terlihat user.
    visible = []
    for d in docs:
        pid = d.person_id
        if pid is None and d.employment_id is not None:
            emp = db.get(Employment, d.employment_id)
            pid = emp.person_id if emp else None
        if pid is not None and not pop_service.can_view_person(db, user, pid):
            continue
        visible.append(d)
    return visible


@router.get(
    "/documents/{document_id}/download",
    dependencies=[Depends(require_permission("document", "view"))],
)
def download_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if doc is None or doc.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan")
    pid = doc.person_id
    if pid is None and doc.employment_id is not None:
        emp = db.get(Employment, doc.employment_id)
        pid = emp.person_id if emp else None
    if pid is not None:
        _check_population(db, user, pid)
    path = UPLOAD_DIR / doc.file_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Berkas tidak ditemukan")
    return FileResponse(path, media_type=doc.mime_type, filename=doc.file_name)
