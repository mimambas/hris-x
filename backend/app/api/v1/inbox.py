"""Kotak masuk approval terpadu (EXP-010, PRD 13.2).

Satu antrean untuk semua pengajuan yang menunggu aksi pengguna saat
ini: cuti, lembur, klaim (L1 oleh atasan langsung / penerima delegasi;
final oleh HR), dan pinjaman (keputusan HR). Aksi setujui/tolak tetap
lewat endpoint modul masing-masing agar aturan bisnisnya tidak dobel.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import (
    Claim,
    ClaimType,
    Employment,
    LeaveRequest,
    LeaveType,
    Loan,
    OvertimeRequest,
    Person,
    User,
)
from app.schemas.schemas import InboxItemOut, InboxOut
from app.services import leave as leave_service
from app.services import population as population_service
from app.services import rbp as rbp_service

router = APIRouter(tags=["inbox"])


def _person_name(db: Session, employment_id) -> str:
    emp = db.get(Employment, employment_id)
    if emp is None:
        return "?"
    person = db.get(Person, emp.person_id)
    return person.full_name if person is not None else "?"


def _rp(amount: int | None) -> str:
    return f"Rp{(amount or 0):,}".replace(",", ".")


@router.get("/inbox/approvals", response_model=InboxOut)
def approval_inbox(user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    # Tanpa gerbang objek tunggal: isi kotak masuk SELALU difilter ke
    # item yang benar-benar bisa ditindak pengguna ini (atasan langsung
    # / penerima delegasi / HR), jadi karyawan biasa menerima daftar
    # kosong — bukan data orang lain.
    own = population_service.get_user_employment(db, user)
    own_id = own.id if own is not None else None
    is_hr = user.is_superadmin or rbp_service.is_hr(db, user)
    items: list[InboxItemOut] = []

    def can_l1(requester_employment_id) -> bool:
        if user.is_superadmin:
            return True
        return leave_service.is_manager_of(
            db, user.tenant_id, own_id, requester_employment_id)

    leaves = db.execute(
        select(LeaveRequest).where(
            LeaveRequest.tenant_id == user.tenant_id,
            LeaveRequest.status.in_(["submitted", "approved_l1"]))
    ).scalars().all()
    for req in leaves:
        if req.status == "submitted":
            if not can_l1(req.employment_id):
                continue
            stage = "L1"
        else:
            if not is_hr:
                continue
            stage = "final"
        lt = db.get(LeaveType, req.leave_type_id)
        items.append(InboxItemOut(
            kind="cuti", id=req.id,
            requester_name=_person_name(db, req.employment_id),
            summary=(f"{lt.name if lt else 'Cuti'} · "
                     f"{req.start_date} s.d. {req.end_date} "
                     f"({req.days} hari)"),
            stage=stage, status=req.status,
            submitted_at=req.submitted_at or req.created_at))

    overtimes = db.execute(
        select(OvertimeRequest).where(
            OvertimeRequest.tenant_id == user.tenant_id,
            OvertimeRequest.status.in_(["submitted", "approved_l1"]))
    ).scalars().all()
    for req in overtimes:
        if req.status == "submitted":
            if not can_l1(req.employment_id):
                continue
            stage = "L1"
        else:
            if not is_hr:
                continue
            stage = "final"
        items.append(InboxItemOut(
            kind="lembur", id=req.id,
            requester_name=_person_name(db, req.employment_id),
            summary=f"Lembur {req.date} · {req.hours} jam",
            stage=stage, status=req.status,
            submitted_at=req.created_at))

    claims = db.execute(
        select(Claim).where(
            Claim.tenant_id == user.tenant_id,
            Claim.status.in_(["submitted", "approved_l1"]))
    ).scalars().all()
    for claim in claims:
        if claim.status == "submitted":
            if not can_l1(claim.employment_id):
                continue
            stage = "L1"
        else:
            if not is_hr:
                continue
            stage = "final"
        ct = db.get(ClaimType, claim.claim_type_id)
        items.append(InboxItemOut(
            kind="klaim", id=claim.id,
            requester_name=_person_name(db, claim.employment_id),
            summary=(f"{ct.name if ct else 'Klaim'} · "
                     f"{_rp(claim.amount)} · {claim.claim_date}"),
            stage=stage, status=claim.status,
            submitted_at=claim.submitted_at or claim.created_at))

    if is_hr:
        loans = db.execute(
            select(Loan).where(Loan.tenant_id == user.tenant_id,
                               Loan.status == "submitted")
        ).scalars().all()
        for loan in loans:
            items.append(InboxItemOut(
                kind="pinjaman", id=loan.id,
                requester_name=_person_name(db, loan.employment_id),
                summary=(f"Pinjaman {_rp(loan.principal_amount)} · "
                         f"{loan.tenor_months} bulan"),
                stage="final", status=loan.status,
                submitted_at=loan.submitted_at or loan.created_at))

    items.sort(key=lambda x: (x.submitted_at is None, x.submitted_at))
    counts: dict[str, int] = {}
    for item in items:
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return InboxOut(items=items, counts=counts)
