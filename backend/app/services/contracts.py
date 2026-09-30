"""Helper domain kontrak kerja (CHR-006), dipakai API & impor Excel."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ContractInfo, TenantContractPolicy


def get_policy(db: Session, tenant_id) -> TenantContractPolicy:
    """Kebijakan kontrak tenant; buat default (60 bln, 1x perpanjangan) bila belum ada."""
    policy = (
        db.execute(
            select(TenantContractPolicy).where(
                TenantContractPolicy.tenant_id == tenant_id
            )
        )
        .scalars()
        .first()
    )
    if policy is None:
        policy = TenantContractPolicy(tenant_id=tenant_id)
        db.add(policy)
        db.flush()
    return policy


def months_between(start: date, end: date) -> int:
    """Durasi kalender dalam bulan (parsial dibulatkan ke atas)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        months += 1
    return max(months, 1)


def ensure_number_unique(
    db: Session, tenant_id, number: str, exclude_contract_id=None
) -> None:
    stmt = select(ContractInfo).where(
        ContractInfo.tenant_id == tenant_id,
        func.lower(ContractInfo.contract_number) == number.strip().lower(),
    )
    if exclude_contract_id is not None:
        stmt = stmt.where(ContractInfo.contract_id != exclude_contract_id)
    if db.execute(stmt.limit(1)).first():
        raise ValueError(f"Nomor kontrak '{number}' sudah dipakai di tenant ini")


def auto_number(db: Session, tenant_id, contract_type: str, start: date) -> str:
    """Nomor kontrak otomatis: PKWT/2026/0001 (unik per tenant)."""
    base = f"{contract_type}/{start.year}"
    count = (
        db.execute(
            select(func.count()).where(
                ContractInfo.tenant_id == tenant_id,
                ContractInfo.contract_number.like(f"{base}/%"),
            )
        ).scalar()
        or 0
    )
    n = count + 1
    while True:
        candidate = f"{base}/{n:04d}"
        try:
            ensure_number_unique(db, tenant_id, candidate)
            return candidate
        except ValueError:
            n += 1


def latest_version(db: Session, tenant_id, contract_id) -> ContractInfo | None:
    return (
        db.execute(
            select(ContractInfo)
            .where(
                ContractInfo.tenant_id == tenant_id,
                ContractInfo.contract_id == contract_id,
            )
            .order_by(ContractInfo.valid_from.desc(), ContractInfo.seq_no.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def all_versions(db: Session, tenant_id, contract_id) -> list[ContractInfo]:
    return (
        db.execute(
            select(ContractInfo)
            .where(
                ContractInfo.tenant_id == tenant_id,
                ContractInfo.contract_id == contract_id,
            )
            .order_by(ContractInfo.valid_from.asc(), ContractInfo.seq_no.asc())
        )
        .scalars()
        .all()
    )
