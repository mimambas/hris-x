"""Custom field / metadata (Sprint 2, PLT-001 & PLT-003, CHR-009).

- Definisi dibuat admin tanpa deploy; langsung tersedia di API.
- Nilai: kolom bertipe (text/number/date), bukan JSON blob.
- Nonaktifkan definisi -> data lama tetap terbaca.
- Hapus definisi = soft delete (is_active=False) + audit.
- Izin: FieldPermission object_name + field_name="custom:<field_key>";
  bila tidak ada baris spesifik, jatuh ke izin object-level "*".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import CustomFieldDefinition, CustomFieldValue, User
from app.schemas.schemas import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionOut,
    CustomFieldDefinitionUpdate,
    CustomFieldValueOut,
    CustomFieldValueSet,
)
from app.services import custom_fields as cf
from app.services.audit import write_audit

router = APIRouter(tags=["custom-fields"])
_view = [Depends(require_permission("custom_field", "view"))]
_insert = [Depends(require_permission("custom_field", "insert"))]

_DEF_FIELDS = ["id", "object_name", "field_key", "label_id", "label_en",
               "field_type", "required", "options", "is_active"]


def _audit(db, user, request, action, object_type, object_id, new_values, reason,
           old_values=None):
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        old_values=old_values,
        new_values=new_values,
        reason=reason,
        channel="api",
        ip=client_ip(request),
    )


def _get_def_or_404(db, user, definition_id) -> CustomFieldDefinition:
    defn = db.get(CustomFieldDefinition, definition_id)
    if defn is None or defn.tenant_id != user.tenant_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Definisi custom field tidak ditemukan"
        )
    return defn


def _target_record_exists(db, user, defn: CustomFieldDefinition, record_id: uuid.UUID) -> bool:
    """Record target harus ada di tenant ini (cegah nilai yatim)."""
    model = cf._LOOKUP_MODELS.get(defn.object_name)
    if model is None:
        return False
    row = db.get(model, record_id)
    return row is not None and row.tenant_id == user.tenant_id


# ---------------------------------------------------------------------------
# Definisi
# ---------------------------------------------------------------------------
@router.post(
    "/custom-fields/definitions",
    response_model=CustomFieldDefinitionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def create_definition(
    body: CustomFieldDefinitionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        cf.validate_definition_payload(
            object_name=body.object_name,
            field_key=body.field_key,
            field_type=body.field_type,
            options=body.options,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    exists = (
        db.execute(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.tenant_id == user.tenant_id,
                CustomFieldDefinition.object_name == body.object_name,
                CustomFieldDefinition.field_key == body.field_key,
            )
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"field_key '{body.field_key}' sudah dipakai untuk objek '{body.object_name}'",
        )
    defn = CustomFieldDefinition(
        tenant_id=user.tenant_id,
        object_name=body.object_name,
        field_key=body.field_key,
        label_id=body.label_id,
        label_en=body.label_en,
        field_type=body.field_type,
        required=body.required,
        options=body.options,
        created_by_user_id=user.id,
    )
    db.add(defn)
    db.flush()
    _audit(db, user, request, "create", "custom_field_definition", defn.id,
           snapshot(defn, _DEF_FIELDS), body.reason)
    db.commit()
    return defn


@router.get(
    "/custom-fields/definitions",
    response_model=list[CustomFieldDefinitionOut],
    dependencies=_view,
)
def list_definitions(
    object_name: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(CustomFieldDefinition).where(
        CustomFieldDefinition.tenant_id == user.tenant_id
    )
    if object_name is not None:
        stmt = stmt.where(CustomFieldDefinition.object_name == object_name)
    if active_only:
        stmt = stmt.where(CustomFieldDefinition.is_active.is_(True))
    return (
        db.execute(stmt.order_by(CustomFieldDefinition.object_name,
                                 CustomFieldDefinition.field_key))
        .scalars()
        .all()
    )


@router.patch(
    "/custom-fields/definitions/{definition_id}",
    response_model=CustomFieldDefinitionOut,
    dependencies=_insert,
)
def update_definition(
    definition_id: uuid.UUID,
    body: CustomFieldDefinitionUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    defn = _get_def_or_404(db, user, definition_id)
    old = snapshot(defn, _DEF_FIELDS)
    fields_set = body.model_fields_set
    if "label_id" in fields_set and body.label_id is not None:
        defn.label_id = body.label_id
    if "label_en" in fields_set:
        defn.label_en = body.label_en
    if body.required is not None:
        defn.required = body.required
    if body.options is not None:
        try:
            cf.validate_definition_payload(
                object_name=defn.object_name,
                field_key=defn.field_key,
                field_type=defn.field_type,
                options=body.options,
            )
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
        defn.options = body.options
    if body.is_active is not None:
        defn.is_active = body.is_active
    db.flush()
    _audit(db, user, request, "update", "custom_field_definition", defn.id,
           snapshot(defn, _DEF_FIELDS), body.reason, old_values=old)
    db.commit()
    return defn


@router.delete(
    "/custom-fields/definitions/{definition_id}",
    dependencies=_insert,
)
def delete_definition(
    definition_id: uuid.UUID,
    request: Request,
    reason: str = Query(min_length=1, max_length=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft delete: is_active=False + audit. Nilai lama tetap tersimpan
    dan tetap terbaca (PLT-003)."""
    defn = _get_def_or_404(db, user, definition_id)
    if not defn.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Definisi sudah nonaktif")
    old = snapshot(defn, _DEF_FIELDS)
    defn.is_active = False
    db.flush()
    _audit(db, user, request, "delete", "custom_field_definition", defn.id,
           snapshot(defn, _DEF_FIELDS), reason, old_values=old)
    db.commit()
    return {"id": str(defn.id), "is_active": False}


# ---------------------------------------------------------------------------
# Nilai
# ---------------------------------------------------------------------------
@router.post(
    "/custom-fields/values",
    response_model=CustomFieldValueOut,
    status_code=status.HTTP_201_CREATED,
)
def set_value(
    body: CustomFieldValueSet,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    defn = _get_def_or_404(db, user, body.definition_id)
    if not defn.is_active:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Definisi field sudah nonaktif; nilai lama tetap terbaca tetapi "
            "tidak bisa diubah",
        )
    if not _target_record_exists(db, user, defn, body.record_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Record target '{defn.object_name}' tidak ditemukan",
        )
    if not cf.has_custom_permission(db, user, defn, "insert"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Tidak punya izin tulis untuk field '{defn.field_key}'",
        )
    try:
        parsed = cf.parse_value(defn, body.value)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    lookup_target = parsed.pop("_lookup_target", None)
    if lookup_target is not None:
        try:
            cf.validate_lookup_target(db, user.tenant_id, lookup_target,
                                      parsed["value_text"])
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    existing = (
        db.execute(
            select(CustomFieldValue).where(
                CustomFieldValue.definition_id == defn.id,
                CustomFieldValue.record_id == str(body.record_id),
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        val = CustomFieldValue(
            tenant_id=user.tenant_id,
            definition_id=defn.id,
            record_id=str(body.record_id),
            updated_by_user_id=user.id,
            **parsed,
        )
        db.add(val)
        action = "create"
    else:
        if not cf.has_custom_permission(db, user, defn, "correct"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Tidak punya izin ubah untuk field '{defn.field_key}'",
            )
        for k, v in parsed.items():
            setattr(existing, k, v)
        existing.updated_by_user_id = user.id
        val = existing
        action = "update"
    db.flush()
    _audit(db, user, request, action, "custom_field_value", val.id,
           {"definition_id": str(defn.id), "record_id": str(body.record_id),
            "field_key": defn.field_key, "value": body.value}, body.reason)
    db.commit()
    return cf.serialize_value(defn, val)


@router.get(
    "/custom-fields/values",
    response_model=list[CustomFieldValueOut],
    dependencies=_view,
)
def list_values(
    object_name: str = Query(min_length=1),
    record_id: uuid.UUID = Query(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Semua nilai custom field untuk satu record; hanya field yang boleh
    dibaca user. Nilai dari definisi nonaktif tetap dikembalikan
    (definition_active=False) — data lama tetap terbaca (PLT-003)."""
    defns = (
        db.execute(
            select(CustomFieldDefinition).where(
                CustomFieldDefinition.tenant_id == user.tenant_id,
                CustomFieldDefinition.object_name == object_name,
            )
        )
        .scalars()
        .all()
    )
    out = []
    for defn in defns:
        if not cf.has_custom_permission(db, user, defn, "view"):
            continue
        val = (
            db.execute(
                select(CustomFieldValue).where(
                    CustomFieldValue.definition_id == defn.id,
                    CustomFieldValue.record_id == str(record_id),
                )
            )
            .scalars()
            .first()
        )
        out.append(cf.serialize_value(defn, val))
    out.sort(key=lambda o: o["field_key"])
    return out
