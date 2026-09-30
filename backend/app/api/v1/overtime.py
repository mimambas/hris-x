"""Lembur: pengajuan + approval 2 level + kalkulasi upah
(PRD Bagian 10.4, TIM-030). Yang dibayar = lembur approved (pra-persetujuan);
integrasi ke payroll via upah_lembur (ATT-010)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, resolve_employment
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import OvertimeRequest, User
from app.schemas.schemas import (
    LeaveDecisionRequest,
    OvertimeRateOut,
    OvertimeRequestCreate,
    OvertimeRequestOut,
)
from app.services import leave as leave_service
from app.services import overtime as ot_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["overtime"])


def _out(req: OvertimeRequest) -> OvertimeRequestOut:
    return OvertimeRequestOut.model_validate(req)


def _get_or_404(db: Session, user: User, request_id: uuid.UUID) -> OvertimeRequest:
    req = db.get(OvertimeRequest, request_id)
    if req is None or req.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pengajuan lembur tidak ditemukan")
    return req


def _audit(db, user: User, request: Request, req: OvertimeRequest,
           action: str, old_status: str, reason: str | None):
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action=action, object_type="overtime_request", object_id=req.id,
        old_values={"status": old_status},
        new_values={"status": req.status, "hours": float(req.hours),
                    "pay_amount": req.pay_amount,
                    "date": req.date.isoformat()},
        reason=reason, channel="api", ip=client_ip(request),
    )


@router.post("/overtime/requests",
             dependencies=[Depends(require_permission("overtime_request",
                                                       "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_request(
    body: OvertimeRequestCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, "overtime_request",
                             "insert")
    try:
        req = ot_service.create_request(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            day=body.date, start_time=body.start_time,
            end_time=body.end_time, reason=body.reason,
            created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, req, "create", "", body.reason)
    db.commit()
    return _out(req)


@router.get("/overtime/requests",
            dependencies=[Depends(require_permission("overtime_request",
                                                      "view"))])
def list_requests(
    employment_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    stmt = select(OvertimeRequest).where(
        OvertimeRequest.tenant_id == user.tenant_id)
    if employment_id is not None:
        resolve_employment(db, user, employment_id, "overtime_request",
                           "view")
        stmt = stmt.where(OvertimeRequest.employment_id == employment_id)
    elif not user.is_superadmin and not rbp_service.has_permission(
        db, user, "overtime_request", "correct"
    ):
        own = population_service.get_user_employment(db, user)
        if own is None:
            return []
        stmt = stmt.where(OvertimeRequest.employment_id == own.id)
    if status_filter:
        stmt = stmt.where(OvertimeRequest.status == status_filter)
    rows = db.execute(
        stmt.order_by(OvertimeRequest.date.desc())).scalars().all()
    return [_out(r) for r in rows]


@router.post("/overtime/requests/{request_id}/submit",
             dependencies=[Depends(require_permission("overtime_request",
                                                       "insert"))])
def submit_request(
    request_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _get_or_404(db, user, request_id)
    resolve_employment(db, user, req.employment_id, "overtime_request",
                       "insert")
    try:
        old = req.status
        req = ot_service.submit_request(db=db, tenant_id=user.tenant_id,
                                        request_id=req.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, req, "submit", old, "Pengajuan disubmit")
    db.commit()
    return _out(req)


@router.post("/overtime/requests/{request_id}/approve-l1",
             dependencies=[Depends(require_permission("overtime_request",
                                                       "view"))])
def approve_l1(
    request_id: uuid.UUID, body: LeaveDecisionRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _get_or_404(db, user, request_id)
    own = population_service.get_user_employment(db, user)
    approver_emp_id = own.id if own is not None else None
    is_manager = (
        own is not None
        and leave_service.is_manager_of(db, user.tenant_id, approver_emp_id,
                                        req.employment_id)
    )
    try:
        old = req.status
        req = ot_service.approve_l1(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            approver_user=user, approver_employment_id=approver_emp_id,
            is_manager=is_manager,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, req, "approve_l1", old, body.reason)
    db.commit()
    return _out(req)


@router.post("/overtime/requests/{request_id}/approve-l2",
             dependencies=[Depends(require_permission("overtime_request",
                                                       "correct"))])
def approve_l2(
    request_id: uuid.UUID, body: LeaveDecisionRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _get_or_404(db, user, request_id)
    own = population_service.get_user_employment(db, user)
    approver_emp_id = own.id if own is not None else None
    can = rbp_service.has_permission(db, user, "overtime_request", "correct")
    try:
        old = req.status
        req = ot_service.approve_l2(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            approver_user=user, approver_employment_id=approver_emp_id,
            can_approve=can,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, req, "approve_l2", old, body.reason)
    db.commit()
    return _out(req)


@router.post("/overtime/requests/{request_id}/reject",
             dependencies=[Depends(require_permission("overtime_request",
                                                       "view"))])
def reject_request(
    request_id: uuid.UUID, body: LeaveDecisionRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _get_or_404(db, user, request_id)
    own = population_service.get_user_employment(db, user)
    approver_emp_id = own.id if own is not None else None
    authorized = user.is_superadmin or (
        approver_emp_id is not None and (
            leave_service.is_manager_of(db, user.tenant_id, approver_emp_id,
                                        req.employment_id)
            or rbp_service.has_permission(db, user, "overtime_request",
                                          "correct")))
    if not authorized:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya atasan langsung atau HR yang bisa menolak")
    try:
        old = req.status
        req = ot_service.reject_request(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            approver_user=user, reason=body.reason,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, req, "reject", old, body.reason)
    db.commit()
    return _out(req)


@router.get("/overtime/rate",
            dependencies=[Depends(require_permission("overtime_request",
                                                      "view"))])
def get_rate(
    on: date = Query(default_factory=date.today),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    rate = ot_service.get_rate(db, user.tenant_id, on)
    return OvertimeRateOut(
        first_hour_mult=float(rate.first_hour_mult),
        next_hour_mult=float(rate.next_hour_mult),
        divisor=rate.divisor,
    )
