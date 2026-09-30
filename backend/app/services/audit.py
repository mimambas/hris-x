"""Penulisan audit trail (PRD 15.6, PLT-050).

Setiap mutasi data WAJIB memanggil write_audit: siapa, kapan, dari mana
(IP), nilai lama & baru, alasan, kanal. Tanpa pengecualian.
Append-only: tidak ada fungsi update/delete di sini, dan API tidak
menyediakan endpoint ubah/hapus audit log.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import AuditLog


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def write_audit(
    *,
    db: Session,
    tenant_id,
    actor_user_id,
    action: str,
    object_type: str,
    object_id=None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    reason: str | None = None,
    channel: str = "api",
    ip: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        old_values=_jsonable(old_values) if old_values is not None else None,
        new_values=_jsonable(new_values) if new_values is not None else None,
        reason=reason,
        channel=channel,
        ip=ip,
    )
    db.add(entry)
    db.flush()
    return entry
