"""Klaim reimbursement karyawan: jenis, pengajuan, approval 2 level,
tandai dibayar (PRD Bagian 11.5, BEN-001)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, resolve_employment, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Claim, ClaimType, User
from app.schemas.schemas import (
    ClaimCreate,
    ClaimDecision,
    ClaimOut,
    ClaimPaid,
    ClaimSummaryOut,
    ClaimTypeCreate,
    ClaimTypeOut,
    ClaimUpdate,
)
from app.services import claims as claims_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["claims"])

OBJECT = "claim"
TYPE_OBJECT = "claim_type"


def _out(claim: Claim) -> ClaimOut:
    return ClaimOut.model_validate(claim)


def _audit(db, user: User, request: Request, claim: Claim, action: str,
           old_status: str, reason: str | None, channel: str = "api"):
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action=action, object_type=OBJECT, object_id=claim.id,
        old_values={"status": old_status},
        new_values={"status": claim.status, "amount": claim.amount,
                    "paid_via": claim.paid_via},
        reason=reason, channel=channel, ip=client_ip(request),
    )


def _claim_or_404(db: Session, user: User, claim_id: uuid.UUID) -> Claim:
    try:
        return claims_service.get_claim(db, user.tenant_id, claim_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Klaim tidak ditemukan")


def _own_employment(db: Session, user: User):
    return population_service.get_user_employment(db, user)


def _is_hr(db: Session, user: User) -> bool:
    return (user.is_superadmin
            or rbp_service.has_permission(db, user, OBJECT, "correct"))


def _approve_employment_id(db: Session, user: User):
    """Employment approver, atau None bila user superadmin tanpa employment."""
    own = _own_employment(db, user)
    if own is not None:
        return own.id
    if user.is_superadmin:
        return None
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "Akun Anda tidak terhubung ke data karyawan")


def _submit_or_404(db, user, claim_id):
    claim = _claim_or_404(db, user, claim_id)
    own = _own_employment(db, user)
    if (not user.is_superadmin and own is not None
            and str(own.id) != str(claim.employment_id)
            and not _is_hr(db, user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Klaim tidak ditemukan")
    return claim


# ------------------------------------------------------------- Jenis klaim
@router.post("/claims/types",
             dependencies=[Depends(require_permission(TYPE_OBJECT, "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_claim_type(
    body: ClaimTypeCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    exists = db.execute(
        select(ClaimType.id).where(ClaimType.tenant_id == user.tenant_id,
                                   ClaimType.code == body.code.strip())
    ).first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Kode klaim '{body.code}' sudah dipakai")
    ct = ClaimType(tenant_id=user.tenant_id, code=body.code.strip(),
                   name=body.name.strip(), limit_per_year=body.limit_per_year,
                   limit_per_claim=body.limit_per_claim,
                   requires_receipt=body.requires_receipt)
    db.add(ct)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type=TYPE_OBJECT, object_id=ct.id,
                new_values=snapshot(ct, ["id", "code", "name"]),
                reason="Jenis klaim baru", channel="api",
                ip=client_ip(request))
    db.commit()
    return ClaimTypeOut.model_validate(ct)


@router.get("/claims/types",
            dependencies=[Depends(require_permission(TYPE_OBJECT, "view"))])
def list_claim_types(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    rows = (db.execute(
        select(ClaimType)
        .where(ClaimType.tenant_id == user.tenant_id)
        .order_by(ClaimType.code))
        .scalars().all())
    return [ClaimTypeOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------- Pengajuan
@router.post("/claims",
             dependencies=[Depends(require_permission(OBJECT, "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_claim(
    body: ClaimCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, OBJECT, "insert")
    try:
        claim = claims_service.create_claim(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            claim_type_id=body.claim_type_id, amount=body.amount,
            claim_date=body.claim_date, description=body.description,
            receipt_document_id=body.receipt_document_id,
            paid_via=body.paid_via, created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type=OBJECT, object_id=claim.id,
                new_values=snapshot(claim, ["id", "amount", "status"]),
                reason="Pengajuan klaim baru (draft)", channel="api",
                ip=client_ip(request))
    db.commit()
    return _out(claim)


@router.patch("/claims/{claim_id}",
              dependencies=[Depends(require_permission(OBJECT, "correct"))])
def update_claim(
    claim_id: uuid.UUID, body: ClaimUpdate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _submit_or_404(db, user, claim_id)
    if claim.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya klaim 'draft' yang bisa diubah")
    old = snapshot(claim, ["amount", "claim_date", "description", "paid_via"])
    for field in ("claim_type_id", "amount", "claim_date", "description",
                  "receipt_document_id", "paid_via"):
        value = getattr(body, field)
        if value is not None:
            setattr(claim, field, value)
    db.flush()
    try:
        claims_service._check_limits(db, user.tenant_id, claim)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type=OBJECT, object_id=claim.id,
                old_values=old, new_values=snapshot(
                    claim, ["amount", "claim_date", "description", "paid_via"]),
                reason="Ubah klaim draft", channel="api",
                ip=client_ip(request))
    db.commit()
    return _out(claim)


@router.post("/claims/{claim_id}/submit",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def submit_claim(
    claim_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _submit_or_404(db, user, claim_id)
    old_status = claim.status
    try:
        claims_service.submit_claim(db=db, tenant_id=user.tenant_id,
                                    claim_id=claim.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, claim, "submit", old_status,
           "Submit pengajuan klaim")
    db.commit()
    return _out(claim)


@router.get("/claims/summary/yearly",
            dependencies=[Depends(require_permission(OBJECT, "view"))])
def claim_summary(
    employment_id: uuid.UUID, year: int = Query(ge=2000, le=2100),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    resolve_employment(db, user, employment_id, OBJECT, "view")
    rows = claims_service.claim_summary(db, user.tenant_id, employment_id,
                                       year)
    return [ClaimSummaryOut.model_validate(r) for r in rows]


@router.get("/claims/{claim_id}",
            dependencies=[Depends(require_permission(OBJECT, "view"))])
def get_claim(
    claim_id: uuid.UUID, user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _out(_submit_or_404(db, user, claim_id))


@router.get("/claims",
            dependencies=[Depends(require_permission(OBJECT, "view"))])
def list_claims(
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
    status_q: str | None = Query(default=None, alias="status"),
    employment_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
):
    q = select(Claim).where(Claim.tenant_id == user.tenant_id)
    if status_q:
        q = q.where(Claim.status == status_q)
    if employment_id:
        own = _own_employment(db, user)
        if (not user.is_superadmin and own is not None
                and str(own.id) != str(employment_id)
                and not _is_hr(db, user)):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Employment tidak ditemukan")
        q = q.where(Claim.employment_id == employment_id)
    rows = (db.execute(q.order_by(Claim.claim_date.desc())
                       .limit(limit)).scalars().all())
    return [_out(r) for r in rows]


# ----------------------------------------------------------------- Approval
@router.post("/claims/{claim_id}/approve-l1",
             dependencies=[Depends(require_permission(OBJECT, "view"))])
def approve_l1(
    claim_id: uuid.UUID, body: ClaimDecision, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _claim_or_404(db, user, claim_id)
    own = _approve_employment_id(db, user)
    old_status = claim.status
    try:
        claims_service.approve_l1(
            db=db, tenant_id=user.tenant_id, claim_id=claim.id,
            approver_user=user, approver_employment_id=own)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, claim, "approve_l1", old_status,
           body.reason or "Approve atasan (L1)")
    db.commit()
    return _out(claim)


@router.post("/claims/{claim_id}/approve",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def approve_final(
    claim_id: uuid.UUID, body: ClaimDecision, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _claim_or_404(db, user, claim_id)
    own = _approve_employment_id(db, user)
    old_status = claim.status
    try:
        claims_service.approve_final(
            db=db, tenant_id=user.tenant_id, claim_id=claim.id,
            approver_user=user, approver_employment_id=own,
            can_approve=_is_hr(db, user))
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, claim, "approve", old_status,
           body.reason or "Approve final HR/Finance")
    db.commit()
    return _out(claim)


@router.post("/claims/{claim_id}/reject",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def reject_claim(
    claim_id: uuid.UUID, body: ClaimDecision, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _claim_or_404(db, user, claim_id)
    if not body.reason or not body.reason.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Alasan penolakan wajib diisi")
    old_status = claim.status
    try:
        claims_service.reject_claim(
            db=db, tenant_id=user.tenant_id, claim_id=claim.id,
            approver_user=user, reason=body.reason)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, claim, "reject", old_status, body.reason)
    db.commit()
    return _out(claim)


@router.post("/claims/{claim_id}/cancel",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def cancel_claim(
    claim_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _submit_or_404(db, user, claim_id)
    old_status = claim.status
    try:
        claims_service.cancel_claim(db=db, tenant_id=user.tenant_id,
                                    claim_id=claim.id)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, claim, "cancel", old_status,
           "Batalkan pengajuan klaim")
    db.commit()
    return _out(claim)


@router.post("/claims/{claim_id}/mark-paid",
             dependencies=[Depends(require_permission(OBJECT, "correct"))])
def mark_paid(
    claim_id: uuid.UUID, body: ClaimPaid, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    claim = _claim_or_404(db, user, claim_id)
    if not _is_hr(db, user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tandai dibayar hanya oleh HR/Finance")
    old_status = claim.status
    try:
        claims_service.mark_paid(
            db=db, tenant_id=user.tenant_id, claim_id=claim.id,
            paid_by_user_id=user.id, payment_ref=body.payment_ref)
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, claim, "mark_paid", old_status,
           body.payment_ref or "Klaim dibayar")
    db.commit()
    return _out(claim)
