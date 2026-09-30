"""Katalog event lifecycle + alasan per tenant (CHR-002): baca & kelola."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import EventReason, LifecycleEvent, User
from app.schemas.schemas import (
    EventReasonOut,
    LifecycleEventCreate,
    LifecycleEventOut,
    LifecycleEventUpdate,
)
from app.services.audit import write_audit

router = APIRouter(tags=["lifecycle"])


def _out(db: Session, ev: LifecycleEvent) -> LifecycleEventOut:
    reasons = (
        db.execute(
            select(EventReason)
            .where(EventReason.event_id == ev.id)
            .order_by(EventReason.reason.asc())
        )
        .scalars()
        .all()
    )
    return LifecycleEventOut(
        id=ev.id,
        code=ev.code,
        name=ev.name,
        description=ev.description,
        applies_to=ev.applies_to,
        is_active=ev.is_active,
        reasons=[EventReasonOut.model_validate(r) for r in reasons],
    )


@router.get(
    "/lifecycle/events",
    response_model=list[LifecycleEventOut],
    dependencies=[Depends(require_permission("lifecycle", "view"))],
)
def list_events(
    applies_to: str | None = Query(default=None, pattern="^(lifecycle|org)$"),
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(LifecycleEvent).where(LifecycleEvent.tenant_id == user.tenant_id)
    if applies_to:
        stmt = stmt.where(LifecycleEvent.applies_to == applies_to)
    if not include_inactive:
        stmt = stmt.where(LifecycleEvent.is_active == True)  # noqa: E712
    events = db.execute(stmt.order_by(LifecycleEvent.code)).scalars().all()
    return [_out(db, ev) for ev in events]


@router.post(
    "/lifecycle/events",
    response_model=LifecycleEventOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("lifecycle", "insert"))],
)
def create_event(
    body: LifecycleEventCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.execute(
            select(LifecycleEvent).where(
                LifecycleEvent.tenant_id == user.tenant_id,
                LifecycleEvent.code == body.code.strip().lower(),
            )
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kode event '{body.code}' sudah dipakai di tenant ini",
        )
    ev = LifecycleEvent(
        tenant_id=user.tenant_id,
        code=body.code.strip().lower(),
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        applies_to=body.applies_to,
        is_active=True,
        created_by_user_id=user.id,
    )
    db.add(ev)
    db.flush()
    for reason in dict.fromkeys(r.strip() for r in body.reasons if r.strip()):
        db.add(EventReason(tenant_id=user.tenant_id, event_id=ev.id, reason=reason))
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="create",
        object_type="lifecycle_event",
        object_id=ev.id,
        new_values={"code": ev.code, "name": ev.name, "applies_to": ev.applies_to},
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return _out(db, ev)


@router.patch(
    "/lifecycle/events/{event_id}",
    response_model=LifecycleEventOut,
    dependencies=[Depends(require_permission("lifecycle", "correct"))],
)
def update_event(
    event_id: uuid.UUID,
    body: LifecycleEventUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ev = db.get(LifecycleEvent, event_id)
    if ev is None or ev.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event tidak ditemukan")
    old = {"name": ev.name, "description": ev.description, "is_active": ev.is_active}
    if body.name is not None:
        ev.name = body.name.strip()
    if body.description is not None:
        ev.description = body.description.strip() or None
    if body.is_active is not None:
        ev.is_active = body.is_active
    if body.reasons is not None:
        # Ganti seluruh daftar alasan: nonaktifkan yang hilang, tambah yang baru.
        wanted = [r.strip() for r in body.reasons if r.strip()]
        existing = (
            db.execute(select(EventReason).where(EventReason.event_id == ev.id))
            .scalars()
            .all()
        )
        for er in existing:
            er.is_active = er.reason in wanted
        known = {er.reason for er in existing}
        for reason in dict.fromkeys(wanted):
            if reason not in known:
                db.add(EventReason(
                    tenant_id=user.tenant_id, event_id=ev.id, reason=reason
                ))
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="update",
        object_type="lifecycle_event",
        object_id=ev.id,
        old_values=old,
        new_values={"name": ev.name, "description": ev.description,
                    "is_active": ev.is_active},
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return _out(db, ev)
