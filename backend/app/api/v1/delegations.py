"""Delegasi approval (EXP-013, PRD 13.2).

Atasan mendelegasikan kewenangan approval L1 (cuti, lembur, klaim) ke
karyawan lain selama ia cuti; delegasi berakhir otomatis di end_date.
Integrasi approval ada di services.leave.is_manager_of — di sini hanya
pengelolaan data delegasinya.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    ApprovalDelegation,
    Employment,
    Job,
    JobInfo,
    Person,
    User,
)
from app.schemas.schemas import (
    DelegationCandidateOut,
    DelegationCreate,
    DelegationOut,
)
from app.services import delegation as delegation_service
from app.services import effective_dating as ed
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["delegations"])

_OBJECT = "delegation"


def _audit(db: Session, user: User, request: Request, action: str,
           obj: ApprovalDelegation, new_values: dict | None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type="approval_delegation",
                object_id=obj.id, old_values=None, new_values=new_values,
                reason=None, channel="api", ip=client_ip(request))


def _person_name(db: Session, employment: Employment | None) -> str | None:
    if employment is None:
        return None
    person = db.get(Person, employment.person_id)
    return person.full_name if person is not None else None


def _out(db: Session, row: ApprovalDelegation) -> DelegationOut:
    delegator = db.get(Employment, row.delegator_employment_id)
    delegate = db.get(Employment, row.delegate_employment_id)
    today = date.today()
    return DelegationOut(
        id=row.id,
        delegator_employment_id=row.delegator_employment_id,
        delegator_name=_person_name(db, delegator),
        delegate_employment_id=row.delegate_employment_id,
        delegate_name=_person_name(db, delegate),
        start_date=row.start_date, end_date=row.end_date,
        status=row.status,
        effective_now=(row.status == "aktif"
                       and row.start_date <= today <= row.end_date),
        note=row.note, created_at=row.created_at)


def _own_or_403(db: Session, user: User) -> Employment:
    own = population_service.get_user_employment(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment")
    return own


@router.post("/delegations", response_model=DelegationOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def create_delegation(body: DelegationCreate, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Buat delegasi dari employment sendiri ke karyawan lain."""
    own = _own_or_403(db, user)
    try:
        row = delegation_service.create_delegation(
            db, user.tenant_id, own.id, body.delegate_employment_id,
            body.start_date, body.end_date, body.note, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    out = _out(db, row)
    _audit(db, user, request, "create", row,
           {"delegate_employment_id": str(row.delegate_employment_id),
            "start_date": str(row.start_date),
            "end_date": str(row.end_date)})
    db.commit()
    return out


@router.get("/delegations/mine", response_model=list[DelegationOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def my_delegations(user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    own = _own_or_403(db, user)
    rows = db.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.tenant_id == user.tenant_id,
            (ApprovalDelegation.delegator_employment_id == own.id)
            | (ApprovalDelegation.delegate_employment_id == own.id))
        .order_by(ApprovalDelegation.start_date.desc())
    ).scalars().all()
    out = []
    for r in rows:
        item = _out(db, r)
        item.direction = ("diberikan"
                          if str(r.delegator_employment_id) == str(own.id)
                          else "diterima")
        out.append(item)
    return out


@router.get("/delegations/candidates",
            response_model=list[DelegationCandidateOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def delegation_candidates(user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Karyawan aktif satu tenant sebagai kandidat penerima delegasi."""
    rows = db.execute(
        select(Employment).where(Employment.tenant_id == user.tenant_id,
                                 Employment.status == "active")
    ).scalars().all()
    out = []
    for emp in rows:
        info = ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                        identity_field="employment_id",
                        identity_value=emp.id, as_of_date=date.today())
        job = db.get(Job, info.job_id) if info is not None else None
        out.append(DelegationCandidateOut(
            employment_id=emp.id,
            person_name=_person_name(db, emp) or "?",
            job_title=job.title if job is not None else None))
    out.sort(key=lambda x: x.person_name)
    return out


@router.get("/delegations", response_model=list[DelegationOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_delegations(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Semua delegasi tenant — hanya HR / superadmin."""
    if not (user.is_superadmin or rbp_service.is_hr(db, user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Daftar semua delegasi hanya untuk HR")
    rows = db.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.tenant_id == user.tenant_id)
        .order_by(ApprovalDelegation.start_date.desc())
    ).scalars().all()
    return [_out(db, r) for r in rows]


@router.delete("/delegations/{delegation_id}",
               response_model=DelegationOut,
               dependencies=[Depends(require_permission(_OBJECT, "delete"))])
def revoke_delegation(delegation_id: uuid.UUID, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Cabut delegasi (oleh delegator sendiri atau HR)."""
    row = db.get(ApprovalDelegation, delegation_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Delegasi tidak ditemukan")
    own = population_service.get_user_employment(db, user)
    is_own = own is not None and str(own.id) == str(
        row.delegator_employment_id)
    if not (user.is_superadmin or is_own or rbp_service.is_hr(db, user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya delegator atau HR yang bisa mencabut")
    if row.status != "aktif":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Delegasi sudah tidak aktif")
    row.status = "dicabut"
    db.flush()
    out = _out(db, row)
    _audit(db, user, request, "revoke", row, {"status": "dicabut"})
    db.commit()
    return out
