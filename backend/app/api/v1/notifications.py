"""Notifikasi in-app & preferensi notifikasi (EXP-005, PRD 13.1).

Kriteria penerimaan PRD: preferensi notifikasi diatur karyawan.
Kanal in-app aktif dan menghormati preferensi; kanal email/WhatsApp
belum terhubung — preferensinya tetap dapat disimpan dan berlaku
saat kanal pengiriman tersedia (ditandai channel_available=False).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import Notification, NotificationPreference, User
from app.schemas.schemas import (
    NotificationListOut,
    NotificationOut,
    NotificationPreferenceItem,
    NotificationPreferenceUpdate,
)
from app.services import notify as notify_service

router = APIRouter(tags=["notifications"])


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _out(row: Notification) -> NotificationOut:
    out = NotificationOut.model_validate(row)
    out.created_at = _aware(out.created_at)  # type: ignore[arg-type]
    out.read_at = _aware(out.read_at)
    return out


@router.get("/notifications", response_model=NotificationListOut)
def list_notifications(unread_only: bool = Query(default=False),
                       limit: int = Query(default=50, ge=1, le=100),
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    stmt = select(Notification).where(
        Notification.tenant_id == user.tenant_id,
        Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    rows = db.execute(
        stmt.order_by(Notification.created_at.desc())
        .limit(limit)).scalars().all()
    unread = db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.tenant_id == user.tenant_id,
            Notification.user_id == user.id,
            Notification.is_read.is_(False))).scalar_one()
    return NotificationListOut(items=[_out(r) for r in rows],
                               unread_count=int(unread))


@router.post("/notifications/{notification_id}/read",
             response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if row is None or row.tenant_id != user.tenant_id \
            or str(row.user_id) != str(user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Notifikasi tidak ditemukan")
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return _out(row)


@router.post("/notifications/read-all")
def mark_all_read(user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    rows = db.execute(
        select(Notification).where(
            Notification.tenant_id == user.tenant_id,
            Notification.user_id == user.id,
            Notification.is_read.is_(False))).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.commit()
    return {"marked": len(rows)}


def _matrix_from_rows(rows: list[NotificationPreference]
                      ) -> list[NotificationPreferenceItem]:
    explicit = {(p.category, p.channel): bool(p.enabled) for p in rows}
    items: list[NotificationPreferenceItem] = []
    for category, label in notify_service.CATEGORIES.items():
        for channel, meta in notify_service.CHANNELS.items():
            enabled = explicit.get((category, channel),
                                   channel == "in_app")
            items.append(NotificationPreferenceItem(
                category=category, category_label=label, channel=channel,
                channel_label=meta["label"],
                channel_available=bool(meta["available"]),
                enabled=enabled))
    return items


def _matrix(db: Session, user: User) -> list[NotificationPreferenceItem]:
    stored = db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user.id)).scalars().all()
    return _matrix_from_rows(list(stored))


@router.get("/notification-preferences",
            response_model=list[NotificationPreferenceItem])
def get_preferences(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return _matrix(db, user)


@router.put("/notification-preferences",
            response_model=list[NotificationPreferenceItem])
def update_preferences(body: NotificationPreferenceUpdate,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    # Muat semua baris sekali; matriks respons disusun dari objek sesi
    # ini (bukan query ulang pasca-commit, yang di Postgres ber-RLS
    # bisa membaca transaksi baru tanpa konteks yang sama).
    rows = list(db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user.id)).scalars().all())
    by_key = {(p.category, p.channel): p for p in rows}
    for entry in body.preferences:
        row = by_key.get((entry.category, entry.channel))
        if row is None:
            row = NotificationPreference(
                tenant_id=user.tenant_id, user_id=user.id,
                category=entry.category, channel=entry.channel,
                enabled=entry.enabled)
            db.add(row)
            rows.append(row)
            by_key[(entry.category, entry.channel)] = row
        else:
            row.enabled = entry.enabled
    db.commit()
    return _matrix_from_rows(rows)
