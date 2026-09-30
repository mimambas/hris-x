"""Cuti/izin: jenis, saldo, pengajuan + approval 2 level, kebijakan
(PRD Bagian 10.5, LEV-001 s/d LEV-007)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, resolve_employment, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Employment,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    User,
)
from app.schemas.schemas import (
    LeaveBalanceOut,
    LeaveDecisionRequest,
    LeavePolicyOut,
    LeavePolicyUpdate,
    LeaveRequestCreate,
    LeaveRequestOut,
    LeaveTypeCreate,
    LeaveTypeOut,
)
from app.services import leave as leave_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["leave"])


def _out(req: LeaveRequest) -> LeaveRequestOut:
    return LeaveRequestOut.model_validate(req)


def _audit_transition(db, user: User, request: Request, req: LeaveRequest,
                      action: str, old_status: str, reason: str | None,
                      channel: str = "api"):
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action=action, object_type="leave_request", object_id=req.id,
        old_values={"status": old_status},
        new_values={"status": req.status,
                    "days": req.days,
                    "start_date": req.start_date.isoformat(),
                    "end_date": req.end_date.isoformat()},
        reason=reason, channel=channel, ip=client_ip(request),
    )


def _request_or_404(db: Session, user: User, request_id: uuid.UUID) -> LeaveRequest:
    req = db.get(LeaveRequest, request_id)
    if req is None or req.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pengajuan cuti tidak ditemukan")
    return req


def _own_employment(db: Session, user: User):
    return population_service.get_user_employment(db, user)


def _can_act_on_request(db: Session, user: User, req: LeaveRequest) -> bool:
    """True bila user adalah pemohon sendiri, superadmin, atau HR
    (izin correct pada leave_request)."""
    if user.is_superadmin:
        return True
    own = _own_employment(db, user)
    if own is not None and str(own.id) == str(req.employment_id):
        return True
    return rbp_service.has_permission(db, user, "leave_request", "correct")


# ------------------------------------------------------------------ Jenis cuti
@router.post("/leave/types",
             dependencies=[Depends(require_permission("leave_type",
                                                       "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_leave_type(
    body: LeaveTypeCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    exists = db.execute(
        select(LeaveType.id).where(LeaveType.tenant_id == user.tenant_id,
                                   LeaveType.code == body.code.strip())
    ).first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Kode cuti '{body.code}' sudah dipakai")
    lt = LeaveType(tenant_id=user.tenant_id, code=body.code.strip(),
                   name=body.name.strip(), quota_days=body.quota_days,
                   accrual=body.accrual,
                   min_service_months=body.min_service_months,
                   requires_doc=body.requires_doc,
                   deducts_balance=body.deducts_balance)
    db.add(lt)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="leave_type", object_id=lt.id,
                new_values=snapshot(lt, ["id", "code", "name", "quota_days"]),
                reason="Jenis cuti baru", channel="api",
                ip=client_ip(request))
    db.commit()
    return LeaveTypeOut.model_validate(lt)


@router.get("/leave/types",
            dependencies=[Depends(require_permission("leave_type", "view"))])
def list_leave_types(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    rows = (db.execute(
        select(LeaveType).where(LeaveType.tenant_id == user.tenant_id,
                                LeaveType.is_active.is_(True))
        .order_by(LeaveType.code))
        .scalars().all())
    return [LeaveTypeOut.model_validate(r) for r in rows]


# ------------------------------------------------------------------ Saldo
@router.get("/leave/balances",
            dependencies=[Depends(require_permission("leave_request",
                                                      "view"))])
def list_balances(
    employment_id: uuid.UUID, year: int = Query(...),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, employment_id, "leave_request", "view")
    out = []
    for lt in db.execute(
        select(LeaveType).where(LeaveType.tenant_id == user.tenant_id,
                                LeaveType.is_active.is_(True))
    ).scalars().all():
        bal = leave_service.ensure_balance(db, user.tenant_id, emp, lt, year)
        row = LeaveBalanceOut.model_validate(bal)
        row.leave_type_code = lt.code
        out.append(row)
    db.commit()
    return out


# ------------------------------------------------------------------ Pengajuan
@router.post("/leave/requests",
             dependencies=[Depends(require_permission("leave_request",
                                                       "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_request(
    body: LeaveRequestCreate, request: Request,
    source: str = Query(default="web", pattern=r"^(web|mobile)$"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, "leave_request",
                             "insert")
    try:
        req = leave_service.create_request(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            leave_type_id=body.leave_type_id, start_date=body.start_date,
            end_date=body.end_date, reason=body.reason,
            created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        code = (status.HTTP_404_NOT_FOUND if isinstance(e, KeyError)
                else status.HTTP_422_UNPROCESSABLE_ENTITY)
        raise HTTPException(code, str(e))
    _audit_transition(db, user, request, req, "create", "", body.reason,
                      channel="mobile" if source == "mobile" else "api")
    db.commit()
    return _out(req)


@router.get("/leave/requests",
            dependencies=[Depends(require_permission("leave_request",
                                                      "view"))])
def list_requests(
    employment_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    stmt = select(LeaveRequest).where(
        LeaveRequest.tenant_id == user.tenant_id)
    if employment_id is not None:
        resolve_employment(db, user, employment_id, "leave_request", "view")
        stmt = stmt.where(LeaveRequest.employment_id == employment_id)
    elif not user.is_superadmin:
        # Non-admin tanpa filter: batasi ke data sendiri kecuali punya
        # izin correct (HR) — konsisten pola ESS.
        if not rbp_service.has_permission(db, user, "leave_request", "correct"):
            own = _own_employment(db, user)
            if own is None:
                return []
            stmt = stmt.where(LeaveRequest.employment_id == own.id)
    if status_filter:
        stmt = stmt.where(LeaveRequest.status == status_filter)
    rows = db.execute(stmt.order_by(LeaveRequest.created_at.desc())).scalars().all()
    return [_out(r) for r in rows]


@router.get("/leave/requests/{request_id}",
            dependencies=[Depends(require_permission("leave_request",
                                                      "view"))])
def get_request(
    request_id: uuid.UUID, user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = _request_or_404(db, user, request_id)
    if not _can_act_on_request(db, user, req):
        # Karyawan lain: cek target population via person.
        emp = db.get(Employment, req.employment_id)
        if not population_service.can_view_person(db, user, emp.person_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")
    return _out(req)


@router.post("/leave/requests/{request_id}/submit",
             dependencies=[Depends(require_permission("leave_request",
                                                       "insert"))])
def submit_request(
    request_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _request_or_404(db, user, request_id)
    if not _can_act_on_request(db, user, req):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya pemohon atau HR yang bisa submit")
    try:
        old = req.status
        req = leave_service.submit_request(db=db, tenant_id=user.tenant_id,
                                           request_id=req.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit_transition(db, user, request, req, "submit", old,
                      "Pengajuan disubmit")
    db.commit()
    return _out(req)


@router.post("/leave/requests/{request_id}/approve-l1",
             dependencies=[Depends(require_permission("leave_request",
                                                       "view"))])
def approve_l1(
    request_id: uuid.UUID, body: LeaveDecisionRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _request_or_404(db, user, request_id)
    own = _own_employment(db, user)
    if own is None and not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment")
    approver_emp_id = own.id if own is not None else None
    try:
        old = req.status
        req = leave_service.approve_l1(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            approver_user=user, approver_employment_id=approver_emp_id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit_transition(db, user, request, req, "approve_l1", old, body.reason,
                      channel="api")
    db.commit()
    return _out(req)


@router.post("/leave/requests/{request_id}/approve-l2",
             dependencies=[Depends(require_permission("leave_request",
                                                       "correct"))])
def approve_l2(
    request_id: uuid.UUID, body: LeaveDecisionRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _request_or_404(db, user, request_id)
    own = _own_employment(db, user)
    approver_emp_id = own.id if own is not None else None
    can = rbp_service.has_permission(db, user, "leave_request", "correct")
    try:
        old = req.status
        req = leave_service.approve_l2(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            approver_user=user, approver_employment_id=approver_emp_id,
            can_approve=can,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit_transition(db, user, request, req, "approve_l2", old, body.reason)
    db.commit()
    return _out(req)


@router.post("/leave/requests/{request_id}/reject",
             dependencies=[Depends(require_permission("leave_request",
                                                       "view"))])
def reject_request(
    request_id: uuid.UUID, body: LeaveDecisionRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _request_or_404(db, user, request_id)
    own = _own_employment(db, user)
    approver_emp_id = own.id if own is not None else None
    authorized = user.is_superadmin or (
        approver_emp_id is not None and (
            leave_service.is_manager_of(db, user.tenant_id, approver_emp_id,
                                        req.employment_id)
            or rbp_service.has_permission(db, user, "leave_request",
                                          "correct")))
    if not authorized:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya atasan langsung atau HR yang bisa menolak")
    try:
        old = req.status
        req = leave_service.reject_request(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            approver_user=user, reason=body.reason,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit_transition(db, user, request, req, "reject", old, body.reason)
    db.commit()
    return _out(req)


@router.post("/leave/requests/{request_id}/cancel",
             dependencies=[Depends(require_permission("leave_request",
                                                       "insert"))])
def cancel_request(
    request_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _request_or_404(db, user, request_id)
    if not _can_act_on_request(db, user, req):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya pemohon atau HR yang bisa membatalkan")
    own = _own_employment(db, user)
    cancelled_by = own.id if own is not None else req.employment_id
    try:
        old = req.status
        req = leave_service.cancel_request(
            db=db, tenant_id=user.tenant_id, request_id=req.id,
            cancelled_by_employment_id=cancelled_by,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit_transition(db, user, request, req, "cancel", old,
                      "Pengajuan dibatalkan")
    db.commit()
    return _out(req)


# ------------------------------------------------------------------ Kebijakan
@router.get("/leave/policy",
            dependencies=[Depends(require_permission("leave_request",
                                                      "view"))])
def get_policy(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    return LeavePolicyOut.model_validate(
        leave_service.get_leave_policy(db, user.tenant_id))


@router.put("/leave/policy",
            dependencies=[Depends(require_permission("leave_request",
                                                      "correct"))])
def update_policy(
    body: LeavePolicyUpdate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    policy = leave_service.get_leave_policy(db, user.tenant_id)
    old = {"max_consecutive_days": policy.max_consecutive_days,
           "blackout_dates": policy.blackout_dates}
    if body.max_consecutive_days is not None:
        policy.max_consecutive_days = body.max_consecutive_days
    if body.blackout_dates is not None:
        # Validasi ringan format tanggal.
        for b in body.blackout_dates:
            date.fromisoformat(b["start"])
            date.fromisoformat(b["end"])
        policy.blackout_dates = body.blackout_dates
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="tenant_leave_policy",
                object_id=policy.id, old_values=old,
                new_values={"max_consecutive_days": policy.max_consecutive_days,
                            "blackout_dates": policy.blackout_dates},
                reason=body.reason, channel="api", ip=client_ip(request))
    db.commit()
    return LeavePolicyOut.model_validate(policy)
