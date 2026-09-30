"""Custom field: validasi nilai & izin tingkat field (Sprint 2).

PLT-001: field didefinisikan admin tanpa deploy; langsung tersedia di API.
PLT-003: picklist terkelola (nilai bisa ditambah/dinonaktifkan; nilai lama
         yang dinonaktifkan tetap terbaca).
PLT-041: field tanpa izin tidak bisa dibaca/ditulis. Izin spesifik
         "custom:<field_key>" mengalahkan izin object-level "*".
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CUSTOM_FIELD_TYPES,
    LOOKUP_TARGETS,
    CustomFieldDefinition,
    CustomFieldValue,
    FieldPermission,
    Job,
    LegalEntity,
    Location,
    OrgUnit,
    Person,
    Position,
)
from app.services import rbp as rbp_service

FIELD_KEY_RE = re.compile(r"^[a-z0-9_]{1,50}$")

# target lookup -> model (untuk validasi keberadaan record).
_LOOKUP_MODELS = {
    "org_unit": OrgUnit,
    "legal_entity": LegalEntity,
    "location": Location,
    "job": Job,
    "position": Position,
    "person": Person,
}

_ACTION_FLAG = {
    "view": "can_view",
    "insert": "can_insert",
    "correct": "can_correct",
    "delete": "can_delete",
}


def validate_definition_payload(
    *, object_name: str, field_key: str, field_type: str, options
) -> None:
    """Validasi definisi; melempar ValueError dengan pesan jelas."""
    from app.models import CUSTOM_FIELD_OBJECTS

    if object_name not in CUSTOM_FIELD_OBJECTS:
        raise ValueError(
            f"object_name harus salah satu dari {list(CUSTOM_FIELD_OBJECTS)}"
        )
    if not FIELD_KEY_RE.match(field_key or ""):
        raise ValueError(
            "field_key hanya boleh huruf kecil/angka/underscore, maks 50 karakter"
        )
    if field_type not in CUSTOM_FIELD_TYPES:
        raise ValueError(f"field_type harus salah satu dari {list(CUSTOM_FIELD_TYPES)}")
    if field_type == "select":
        if not isinstance(options, list) or not options:
            raise ValueError("field_type 'select' wajib punya options list tidak kosong")
        seen = set()
        for opt in options:
            if not isinstance(opt, dict) or "value" not in opt:
                raise ValueError("Setiap option select wajib punya 'value'")
            if opt["value"] in seen:
                raise ValueError(f"Nilai option '{opt['value']}' duplikat")
            seen.add(opt["value"])
            opt.setdefault("is_active", True)
            opt.setdefault("label_id", str(opt["value"]))
    elif field_type == "lookup":
        if not isinstance(options, dict) or options.get("target") not in LOOKUP_TARGETS:
            raise ValueError(
                f"field_type 'lookup' wajib punya options.target salah satu dari "
                f"{list(LOOKUP_TARGETS)}"
            )


def _active_option_values(defn: CustomFieldDefinition) -> set[str]:
    return {
        str(o["value"]) for o in (defn.options or []) if o.get("is_active", True)
    }


def parse_value(defn: CustomFieldDefinition, raw) -> dict:
    """Validasi & ubah nilai mentah menjadi kolom typed.

    Mengembalikan {"value_text":..., "value_number":..., "value_date":...}.
    Melempar ValueError bila tidak valid.
    """
    out = {"value_text": None, "value_number": None, "value_date": None}
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if defn.required:
            raise ValueError(f"Field '{defn.field_key}' wajib diisi")
        return out

    ftype = defn.field_type
    if ftype == "text" or ftype == "attachment":
        out["value_text"] = str(raw)
    elif ftype == "number":
        try:
            out["value_number"] = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"Field '{defn.field_key}' harus berupa angka")
    elif ftype == "date":
        try:
            out["value_date"] = (
                raw if isinstance(raw, date)
                else datetime.strptime(str(raw), "%Y-%m-%d").date()
            )
        except (ValueError, TypeError):
            raise ValueError(
                f"Field '{defn.field_key}' harus tanggal format YYYY-MM-DD"
            )
    elif ftype == "select":
        val = str(raw)
        if val not in _active_option_values(defn):
            raise ValueError(
                f"Nilai '{val}' tidak tersedia untuk field '{defn.field_key}'"
            )
        out["value_text"] = val
    elif ftype == "lookup":
        target = (defn.options or {}).get("target")
        try:
            uuid.UUID(str(raw))
        except (ValueError, TypeError):
            raise ValueError(f"Field '{defn.field_key}' harus berupa UUID valid")
        out["value_text"] = str(raw)
        out["_lookup_target"] = target  # dipakai validasi keberadaan di bawah
    else:
        raise ValueError(f"Tipe field '{ftype}' tidak dikenal")
    return out


def validate_lookup_target(db: Session, tenant_id, target: str, raw: str) -> None:
    model = _LOOKUP_MODELS.get(target)
    if model is None:
        raise ValueError(f"Target lookup '{target}' tidak dikenal")
    row = db.get(model, uuid.UUID(raw))
    if row is None or row.tenant_id != tenant_id:
        raise ValueError(f"Record lookup '{raw}' tidak ditemukan di tenant ini")


def has_custom_permission(db: Session, user, defn: CustomFieldDefinition, action: str) -> bool:
    """Izin baca/tulis satu custom field.

    Aturan: bila ada baris FieldPermission spesifik "custom:<field_key>"
    untuk role user, baris itu yang menentukan; bila tidak ada, jatuh ke
    izin object-level "*". Superadmin selalu lolos.
    """
    if user.is_superadmin:
        return True
    flag = _ACTION_FLAG.get(action)
    if flag is None:
        return False
    specific_key = f"custom:{defn.field_key}"
    specific_found = False
    specific_grant = False
    fallback_grant = False
    for role in rbp_service.get_user_roles(db, user):
        perms = (
            db.execute(
                select(FieldPermission).where(
                    FieldPermission.tenant_id == user.tenant_id,
                    FieldPermission.role_id == role.id,
                    FieldPermission.object_name.in_([defn.object_name, "*"]),
                    FieldPermission.field_name.in_([specific_key, "*"]),
                )
            )
            .scalars()
            .all()
        )
        for p in perms:
            if p.field_name == specific_key:
                specific_found = True
                specific_grant = specific_grant or bool(getattr(p, flag))
            else:
                fallback_grant = fallback_grant or bool(getattr(p, flag))
    if specific_found:
        return specific_grant
    return fallback_grant


def serialize_value(defn: CustomFieldDefinition, val: CustomFieldValue | None) -> dict:
    """Satu nilai custom field untuk response API."""
    if val is None:
        return {
            "field_key": defn.field_key,
            "label_id": defn.label_id,
            "label_en": defn.label_en,
            "field_type": defn.field_type,
            "value": None,
            "definition_active": defn.is_active,
        }
    raw = val.value_text
    if defn.field_type == "number" and val.value_number is not None:
        raw = str(val.value_number)
    elif defn.field_type == "date" and val.value_date is not None:
        raw = val.value_date.isoformat()
    return {
        "field_key": defn.field_key,
        "label_id": defn.label_id,
        "label_en": defn.label_en,
        "field_type": defn.field_type,
        "value": raw,
        "definition_active": defn.is_active,
    }
