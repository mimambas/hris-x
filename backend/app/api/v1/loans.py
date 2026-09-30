"""Pinjaman/kasbon karyawan: kebijakan, pengajuan, approval, pelunasan
(PRD Bagian 11.5, BEN-003)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, resolve_employment, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Loan, User
from app.schemas.schemas import (
    LoanCreate,
    LoanInstallmentOut,
    LoanOut,
    LoanPolicyOut,
    LoanPolicyUpdate,
)
from app.schemas.schemas import ClaimDecision as LoanDecision
from app.services import loans as loans_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["loans"])

OBJECT = "loan"
POLICY_OBJECT = "loan_policy"


def _out(loan: Loan) -> LoanOut:
    return LoanOut.model_validate(loan)


def _audit(db, user: User, request: Request, loan: Loan, action: str,
           old_status: str, reason: str | None, channel: str = "api"):
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action=action, object_type=OBJECT, object_id=loan.id,
        old_values={"status": old_status},
        new_values={"status": loan.status,
                    "principal_amount": loan.principal_amount,
                    "remaining_total": loan.remaining_total},
        reason=reason, channel=channel, ip=client_ip(request),
    )


def _loan_or_404(db: Session, user: User, loan_id: uuid.UUID) -> Loan:
    try:
        return loans_service.get_loan(db, user.tenant_id, loan_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pinjaman tidak ditemukan")


def _own_employment(db: Session, user: User):
    return population_service.get_user_employment(db, user)


def _is_hr(db: Session, user: User) -> bool:
    return (user.is_superadmin
            or rbp_service.has_permission(db, user, OBJECT, "correct"))


def _scope_loan(db, user, loan: Loan) -> Loan:
    """Batasi pinjaman orang lain dari karyawan non-HR (404 anti-bocor)."""
    own = _own_employment(db, user)
    if (not user.is_superadmin and own is not None
            and str(own.id) != str(loan.employment_id)
            and not _is_hr(db, user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pinjaman tidak ditemukan")
    return loan


# -------------------------------------------------------------- Kebijakan
@router.get("/loans/policy",
            dependencies=[Depends(require_permission(POLICY_OBJECT, "view"))])
def get_loan_policy(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return LoanPolicyOut.model_validate(
        loans_service.get_loan_policy(db, user.tenant_id))


@router.put("/loans/policy",
            dependencies=[Depends(require_permission(POLICY_OBJECT,
                                                     "correct"))])
def update_loan_policy(
    body: LoanPolicyUpdate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    policy = loans_service.get_loan_policy(db, user.tenant_id)
    def _policy_snap(p):
        return {"max_amount_multiplier": float(p.max_amount_multiplier),
                "max_tenor_months": int(p.max_tenor_months),
                "default_interest_rate": float(p.default_interest_rate),
                "allow_multiple_active": bool(p.allow_multiple_active)}
    old = _policy_snap(policy)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        policy = loans_service.update_loan_policy(db, user.tenant_id, **fields)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type=POLICY_OBJECT,
                object_id=policy.id, old_values=old,
                new_values=_policy_snap(policy),
                reason="Ubah kebijakan pinjaman", channel="api",
                ip=client_ip(request))
    db.commit()
    return LoanPolicyOut.model_validate(policy)


# ---------------------------------------------------------------- Pengajuan
@router.post("/loans",
             dependencies=[Depends(require_permission(OBJECT, "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_loan(
    body: LoanCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, OBJECT, "insert")
    try:
        loan = loans_service.create_loan(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            amount=body.amount, tenor_months=body.tenor_months,
            purpose=body.purpose, interest_rate=body.interest_rate,
            created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type=OBJECT, object_id=loan.id,
                new_values=snapshot(loan, ["id", "principal_amount", "status"]),
                reason="Pengajuan pinjaman baru (draft)", channel="api",
                ip=client_ip(request))
    db.commit()
    return _out(loan)


@router.get("/loans/{loan_id}",
            dependencies=[Depends(require_permission(OBJECT, "view"))])
def get_loan(
    loan_id: uuid.UUID, user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _out(_scope_loan(db, user, _loan_or_404(db, user, loan_id)))


@router.get("/loans",
            dependencies=[Depends(require_permission(OBJECT, "view"))])
def list_loans(
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
    status_q: str | None = Query(default=None, alias="status"),
    employment_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
):
    q = select(Loan).where(Loan.tenant_id == user.tenant_id)
    if status_q:
        q = q.where(Loan.status == status_q)
    if employment_id:
        own = _own_employment(db, user)
        if (not user.is_superadmin and own is not None
                and str(own.id) != str(employment_id)
                and not _is_hr(db, user)):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Employment tidak ditemukan")
        q = q.where(Loan.employment_id == employment_id)
    else:
        own = _own_employment(db, user)
        if not user.is_superadmin and not _is_hr(db, user):
            if own is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "Akun Anda tidak terhubung ke data karyawan")
            q = q.where(Loan.employment_id == own.id)
    rows = (db.execute(q.order_by(Loan.created_at.desc())
                       .limit(limit)).scalars().all())
    return [_out(r) for r in rows]


@router.post("/loans/{loan_id}/submit",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def submit_loan(
    loan_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    loan = _scope_loan(db, user, _loan_or_404(db, user, loan_id))
    old_status = loan.status
    try:
        loans_service.submit_loan(db=db, tenant_id=user.tenant_id,
                                  loan_id=loan.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, loan, "submit", old_status,
           "Submit pengajuan pinjaman")
    db.commit()
    return _out(loan)


@router.post("/loans/{loan_id}/approve",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def approve_loan(
    loan_id: uuid.UUID, body: LoanDecision, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    loan = _loan_or_404(db, user, loan_id)
    if not _is_hr(db, user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Persetujuan pinjaman hanya oleh HR/Finance")
    old_status = loan.status
    try:
        loans_service.approve_loan(
            db=db, tenant_id=user.tenant_id, loan_id=loan.id,
            approver_user=user, can_approve=_is_hr(db, user))
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, loan, "approve", old_status,
           body.reason or "Pinjaman disetujui HR/Finance")
    db.commit()
    return _out(loan)


@router.post("/loans/{loan_id}/reject",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def reject_loan(
    loan_id: uuid.UUID, body: LoanDecision, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    loan = _loan_or_404(db, user, loan_id)
    if not _is_hr(db, user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Penolakan pinjaman hanya oleh HR/Finance")
    if not body.reason or not body.reason.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Alasan penolakan wajib diisi")
    old_status = loan.status
    try:
        loans_service.reject_loan(
            db=db, tenant_id=user.tenant_id, loan_id=loan.id,
            approver_user=user, reason=body.reason)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, loan, "reject", old_status, body.reason)
    db.commit()
    return _out(loan)


@router.post("/loans/{loan_id}/cancel",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def cancel_loan(
    loan_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    loan = _scope_loan(db, user, _loan_or_404(db, user, loan_id))
    old_status = loan.status
    try:
        loans_service.cancel_loan(db=db, tenant_id=user.tenant_id,
                                  loan_id=loan.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, loan, "cancel", old_status,
           "Batalkan pengajuan pinjaman")
    db.commit()
    return _out(loan)


@router.post("/loans/{loan_id}/payoff",
             dependencies=[Depends(require_permission(OBJECT, "correct"))],
             status_code=status.HTTP_201_CREATED)
def payoff_loan(
    loan_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    loan = _scope_loan(db, user, _loan_or_404(db, user, loan_id))
    try:
        inst = loans_service.payoff_loan(db=db, tenant_id=user.tenant_id,
                                         loan_id=loan.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="payoff_schedule", object_type=OBJECT,
                object_id=loan.id,
                new_values={"installment_id": str(inst.id),
                            "period": inst.period, "amount": inst.amount},
                reason="Pelunasan dipercepat dijadwalkan",
                channel="api", ip=client_ip(request))
    db.commit()
    return LoanInstallmentOut.model_validate(inst)


@router.get("/loans/{loan_id}/installments",
            dependencies=[Depends(require_permission(OBJECT, "view"))])
def list_installments(
    loan_id: uuid.UUID, user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    loan = _scope_loan(db, user, _loan_or_404(db, user, loan_id))
    rows = loans_service.loan_installments(db, user.tenant_id, loan.id)
    return [LoanInstallmentOut.model_validate(r) for r in rows]
