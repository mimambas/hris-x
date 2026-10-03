"""Delegasi approval (EXP-013, PRD 13.2).

Delegator (atasan) menunjuk delegate untuk menjalankan approval L1
(cuti, lembur, klaim) selama jendela tanggal tertentu — lazimnya saat
delegator cuti. Delegasi berakhir otomatis ketika end_date terlewati;
tidak perlu job pembersih karena pengecekan selalu berbasis tanggal.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalDelegation, Employment


def _employment_or_none(db: Session, tenant_id, employment_id):
    if employment_id is None:
        return None
    return db.execute(
        select(Employment).where(Employment.tenant_id == tenant_id,
                                 Employment.id == employment_id)
    ).scalars().first()


def active_delegation(db: Session, tenant_id, delegator_employment_id,
                      delegate_employment_id, on_date: date | None = None):
    """Delegasi aktif antara delegator & delegate pada tanggal tertentu."""
    today = on_date or date.today()
    return db.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.tenant_id == tenant_id,
            ApprovalDelegation.delegator_employment_id
            == delegator_employment_id,
            ApprovalDelegation.delegate_employment_id
            == delegate_employment_id,
            ApprovalDelegation.status == "aktif",
            ApprovalDelegation.start_date <= today,
            ApprovalDelegation.end_date >= today)
    ).scalars().first()


def is_delegate_of(db: Session, tenant_id, delegate_employment_id,
                   delegator_employment_id,
                   on_date: date | None = None) -> bool:
    if delegate_employment_id is None or delegator_employment_id is None:
        return False
    if str(delegate_employment_id) == str(delegator_employment_id):
        return False
    return active_delegation(db, tenant_id, delegator_employment_id,
                             delegate_employment_id, on_date) is not None


def delegator_ids_for(db: Session, tenant_id, delegate_employment_id,
                      on_date: date | None = None) -> set:
    """Employment id para delegator yang saat ini mendelegasikan ke user."""
    today = on_date or date.today()
    rows = db.execute(
        select(ApprovalDelegation.delegator_employment_id).where(
            ApprovalDelegation.tenant_id == tenant_id,
            ApprovalDelegation.delegate_employment_id
            == delegate_employment_id,
            ApprovalDelegation.status == "aktif",
            ApprovalDelegation.start_date <= today,
            ApprovalDelegation.end_date >= today)
    ).scalars().all()
    return set(rows)


def create_delegation(db: Session, tenant_id, delegator_employment_id,
                      delegate_employment_id, start_date: date,
                      end_date: date, note: str | None,
                      created_by_user_id) -> ApprovalDelegation:
    if str(delegator_employment_id) == str(delegate_employment_id):
        raise ValueError("Tidak bisa mendelegasikan ke diri sendiri")
    if end_date < start_date:
        raise ValueError("Tanggal selesai tidak boleh sebelum tanggal mulai")
    delegator = _employment_or_none(db, tenant_id, delegator_employment_id)
    if delegator is None or delegator.status != "active":
        raise ValueError("Employment delegator tidak ditemukan/aktif")
    delegate = _employment_or_none(db, tenant_id, delegate_employment_id)
    if delegate is None or delegate.status != "active":
        raise ValueError("Employment penerima delegasi tidak ditemukan/aktif")
    overlap = db.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.tenant_id == tenant_id,
            ApprovalDelegation.delegator_employment_id
            == delegator_employment_id,
            ApprovalDelegation.status == "aktif",
            ApprovalDelegation.start_date <= end_date,
            ApprovalDelegation.end_date >= start_date)
    ).scalars().first()
    if overlap is not None:
        raise ValueError(
            "Sudah ada delegasi aktif yang tumpang tindih pada periode itu")
    row = ApprovalDelegation(
        tenant_id=tenant_id,
        delegator_employment_id=delegator_employment_id,
        delegate_employment_id=delegate_employment_id,
        start_date=start_date, end_date=end_date, status="aktif",
        note=note, created_by_user_id=created_by_user_id)
    db.add(row)
    db.flush()
    return row
