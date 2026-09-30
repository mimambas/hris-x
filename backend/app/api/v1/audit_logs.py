"""Audit log: baca & filter (PRD 15.6, PLT-053). Append-only: tanpa endpoint ubah/hapus."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import AuditLog, CompInfo, Employment, JobInfo, User
from app.schemas.schemas import AuditLogOut

router = APIRouter(tags=["audit"])


@router.get(
    "/audit-logs",
    response_model=list[AuditLogOut],
    dependencies=[Depends(require_permission("audit_log", "view"))],
)
def list_audit_logs(
    object_type: str | None = Query(default=None),
    object_id: str | None = Query(default=None),
    employment_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if employment_id:
        # Pastikan employment milik tenant ini.
        emp = db.get(Employment, employment_id)
        if emp is None or emp.tenant_id != user.tenant_id:
            return []
        # object_id disimpan sebagai string UUID bertanda hubung, jadi
        # bandingkan dalam bentuk string (portabel SQLite/Postgres).
        emp_str = str(employment_id)
        job_ids = [
            str(row[0])
            for row in db.execute(
                select(JobInfo.id).where(
                    JobInfo.tenant_id == user.tenant_id,
                    JobInfo.employment_id == employment_id,
                )
            ).all()
        ]
        comp_ids = [
            str(row[0])
            for row in db.execute(
                select(CompInfo.id).where(
                    CompInfo.tenant_id == user.tenant_id,
                    CompInfo.employment_id == employment_id,
                )
            ).all()
        ]
        stmt = stmt.where(
            or_(
                and_(AuditLog.object_type == "employment",
                     AuditLog.object_id == emp_str),
                and_(AuditLog.object_type == "job_info",
                     AuditLog.object_id.in_(job_ids)),
                and_(AuditLog.object_type == "comp_info",
                     AuditLog.object_id.in_(comp_ids)),
            )
        )
    if date_from:
        stmt = stmt.where(
            AuditLog.created_at >= datetime.combine(date_from, time.min)
        )
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(date_to, time.max))
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    return db.execute(stmt).scalars().all()
