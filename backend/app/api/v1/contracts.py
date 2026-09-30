"""Kontrak kerja: versi kontrak PKWT/PKWTT + kebijakan tenant (CHR-006).

Pola identitas + info berversi (konsisten ADR-0004): masa berlaku kontrak =
valid_from..valid_to pada ContractInfo. PKWTT memakai valid_to = 9999-12-31
(kontrak terbuka, tak pernah masuk daftar expiring). Perpanjangan & konversi
= versi baru; aturan durasi diambil dari TenantContractPolicy (konfigurabel,
bukan hard-code).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    MAX_DATE,
    Contract,
    ContractInfo,
    Employment,
    JobInfo,
    TenantContractPolicy,
    User,
)
from app.schemas.schemas import (
    ContractConvertRequest,
    ContractCreate,
    ContractExtendRequest,
    ContractOut,
    ContractPolicyOut,
    ContractPolicyUpdate,
    ContractVersionOut,
)
from app.services import effective_dating as ed
from app.services import lifecycle
from app.services.contracts import (
    all_versions as _versions,
    auto_number as _auto_number,
    ensure_number_unique as _ensure_number_unique,
    get_policy,
    latest_version as _latest_version,
    months_between,
)
from app.services.audit import write_audit

router = APIRouter(tags=["contracts"])

_VERSION_FIELDS = [
    "id", "contract_id", "contract_type", "contract_number",
    "valid_from", "valid_to", "seq_no", "event", "event_reason",
]


def _out(db: Session, tenant_id, contract: Contract) -> ContractOut:
    versions = _versions(db, tenant_id, contract.id)
    latest = versions[-1] if versions else None
    return ContractOut(
        id=contract.id,
        employment_id=contract.employment_id,
        current_version=(
            ContractVersionOut.model_validate(latest) if latest else None
        ),
        versions=[ContractVersionOut.model_validate(v) for v in versions],
    )


def _get_contract_or_404(db: Session, user: User, contract_id: uuid.UUID) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None or contract.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kontrak tidak ditemukan")
    return contract


def _get_employment_or_404(db: Session, user: User, employment_id: uuid.UUID) -> Employment:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employment tidak ditemukan")
    return emp


def _job_sidecar(
    db: Session, user: User, request: Request,
    employment_id, valid_from: date, event: str, event_reason: str, reason: str,
) -> None:
    """Catat event kontrak juga di timeline JobInfo (fakta job disalin dari
    versi terakhir). Tanpa sidecar ini, timeline karyawan tak menunjukkan
    perpanjangan/konversi kontrak."""
    latest_job = (
        db.execute(
            select(JobInfo)
            .where(
                JobInfo.tenant_id == user.tenant_id,
                JobInfo.employment_id == employment_id,
            )
            .order_by(JobInfo.valid_from.desc(), JobInfo.seq_no.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if latest_job is None:
        return
    record = ed.insert_record(
        db=db,
        tenant_id=user.tenant_id,
        model=JobInfo,
        identity_field="employment_id",
        identity_value=employment_id,
        valid_from=valid_from,
        values={
            "job_id": latest_job.job_id,
            "org_unit_id": latest_job.org_unit_id,
            "location_id": latest_job.location_id,
            "manager_employment_id": latest_job.manager_employment_id,
        },
        event=event,
        event_reason=event_reason,
        created_by=user.id,
        event_applies_to="lifecycle",
    )
    emp = _get_employment_or_404(db, user, employment_id)
    lifecycle.derive_employment_status(db, emp)
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="insert",
        object_type="job_info",
        object_id=record.id,
        new_values=snapshot(record, [
            "id", "employment_id", "valid_from", "valid_to", "seq_no",
            "job_id", "org_unit_id", "location_id", "manager_employment_id",
            "event", "event_reason",
        ]),
        reason=reason,
        channel="api",
        ip=client_ip(request),
    )


@router.post(
    "/contracts",
    response_model=ContractOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("contract", "insert"))],
)
def create_contract(
    body: ContractCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    emp = _get_employment_or_404(db, user, body.employment_id)
    ctype = body.contract_type.upper()
    policy = get_policy(db, user.tenant_id)
    try:
        if ctype == "PKWT":
            if body.end_date is None:
                raise ValueError("Kontrak PKWT wajib memiliki tanggal berakhir")
            if body.end_date <= body.start_date:
                raise ValueError("Tanggal berakhir harus setelah tanggal mulai")
            if months_between(body.start_date, body.end_date) > policy.max_pkwt_months:
                raise ValueError(
                    f"Durasi PKWT melebihi batas kebijakan tenant "
                    f"({policy.max_pkwt_months} bulan)"
                )
        else:  # PKWTT
            if body.end_date is not None:
                raise ValueError("Kontrak PKWTT tidak memakai tanggal berakhir")
        number = (body.contract_number or "").strip() or _auto_number(
            db, user.tenant_id, ctype, body.start_date
        )
        _ensure_number_unique(db, user.tenant_id, number)

        contract = Contract(tenant_id=user.tenant_id, employment_id=emp.id)
        db.add(contract)
        db.flush()
        version = ed.insert_record(
            db=db,
            tenant_id=user.tenant_id,
            model=ContractInfo,
            identity_field="contract_id",
            identity_value=contract.id,
            valid_from=body.start_date,
            valid_to=body.end_date if ctype == "PKWT" else None,
            values={"contract_type": ctype, "contract_number": number},
            event=body.event,
            event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="lifecycle",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="insert",
        object_type="contract_info",
        object_id=version.id,
        new_values=snapshot(version, _VERSION_FIELDS),
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return _out(db, user.tenant_id, contract)


@router.get(
    "/contracts/expiring",
    dependencies=[Depends(require_permission("contract", "view"))],
)
def list_expiring_contracts(
    within_days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kontrak PKWT yang berakhir dalam N hari ke depan (peringatan HR)."""
    today = date.today()
    horizon = today + timedelta(days=within_days)
    contracts = (
        db.execute(
            select(Contract).where(Contract.tenant_id == user.tenant_id)
        )
        .scalars()
        .all()
    )
    result = []
    for contract in contracts:
        latest = _latest_version(db, user.tenant_id, contract.id)
        if latest is None:
            continue
        if latest.contract_type != "PKWT":
            continue
        if latest.valid_to == MAX_DATE:
            continue
        if today <= latest.valid_to <= horizon:
            emp = db.get(Employment, contract.employment_id)
            result.append({
                "contract_id": str(contract.id),
                "employment_id": str(contract.employment_id),
                "person_id": str(emp.person_id) if emp else None,
                "contract_type": latest.contract_type,
                "contract_number": latest.contract_number,
                "end_date": latest.valid_to.isoformat(),
                "days_remaining": (latest.valid_to - today).days,
            })
    result.sort(key=lambda r: r["end_date"])
    return result


@router.get(
    "/contracts",
    dependencies=[Depends(require_permission("contract", "view"))],
)
def list_contracts(
    employment_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Contract).where(Contract.tenant_id == user.tenant_id)
    if employment_id is not None:
        stmt = stmt.where(Contract.employment_id == employment_id)
    contracts = db.execute(stmt).scalars().all()
    return [_out(db, user.tenant_id, c) for c in contracts]


@router.get(
    "/contracts/policy",
    response_model=ContractPolicyOut,
    dependencies=[Depends(require_permission("contract", "view"))],
)
def get_contract_policy(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return get_policy(db, user.tenant_id)


@router.put(
    "/contracts/policy",
    response_model=ContractPolicyOut,
    dependencies=[Depends(require_permission("contract", "correct"))],
)
def update_contract_policy(
    body: ContractPolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policy = get_policy(db, user.tenant_id)
    old = {"max_pkwt_months": policy.max_pkwt_months,
           "max_extensions": policy.max_extensions}
    if body.max_pkwt_months is not None:
        policy.max_pkwt_months = body.max_pkwt_months
    if body.max_extensions is not None:
        policy.max_extensions = body.max_extensions
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="update",
        object_type="tenant_contract_policy",
        object_id=policy.id,
        old_values=old,
        new_values={"max_pkwt_months": policy.max_pkwt_months,
                    "max_extensions": policy.max_extensions},
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return policy


@router.get(
    "/contracts/{contract_id}",
    response_model=ContractOut,
    dependencies=[Depends(require_permission("contract", "view"))],
)
def get_contract(
    contract_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contract = _get_contract_or_404(db, user, contract_id)
    return _out(db, user.tenant_id, contract)


@router.post(
    "/contracts/{contract_id}/extend",
    response_model=ContractOut,
    dependencies=[Depends(require_permission("contract", "insert"))],
)
def extend_contract(
    contract_id: uuid.UUID,
    body: ContractExtendRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Perpanjangan PKWT: versi baru + sidecar di timeline JobInfo."""
    contract = _get_contract_or_404(db, user, contract_id)
    policy = get_policy(db, user.tenant_id)
    versions = _versions(db, user.tenant_id, contract.id)
    latest = versions[-1] if versions else None
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kontrak belum punya versi")
    try:
        if latest.contract_type != "PKWT":
            raise ValueError("Hanya kontrak PKWT yang dapat diperpanjang")
        extensions_done = len(versions) - 1
        if extensions_done >= policy.max_extensions:
            raise ValueError(
                f"Batas perpanjangan tercapai ({policy.max_extensions}x per kebijakan tenant)"
            )
        new_from = latest.valid_to + timedelta(days=1)
        if body.new_end_date <= latest.valid_to:
            raise ValueError("Tanggal berakhir baru harus setelah periode berjalan")
        if months_between(new_from, body.new_end_date) > policy.max_pkwt_months:
            raise ValueError(
                f"Durasi perpanjangan melebihi batas kebijakan tenant "
                f"({policy.max_pkwt_months} bulan)"
            )
        number = (body.new_contract_number or "").strip() or _auto_number(
            db, user.tenant_id, "PKWT", new_from
        )
        _ensure_number_unique(db, user.tenant_id, number,
                              exclude_contract_id=contract.id)
        version = ed.insert_record(
            db=db,
            tenant_id=user.tenant_id,
            model=ContractInfo,
            identity_field="contract_id",
            identity_value=contract.id,
            valid_from=new_from,
            valid_to=body.new_end_date,
            values={"contract_type": "PKWT", "contract_number": number},
            event="contract_extension",
            event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="lifecycle",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="insert",
        object_type="contract_info",
        object_id=version.id,
        new_values=snapshot(version, _VERSION_FIELDS),
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    _job_sidecar(db, user, request, contract.employment_id, new_from,
                 "contract_extension", body.event_reason, body.reason)
    db.commit()
    return _out(db, user.tenant_id, contract)


@router.post(
    "/contracts/{contract_id}/convert",
    response_model=ContractOut,
    dependencies=[Depends(require_permission("contract", "insert"))],
)
def convert_contract(
    contract_id: uuid.UUID,
    body: ContractConvertRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Konversi PKWT -> PKWTT: versi baru terbuka + sidecar di timeline JobInfo."""
    contract = _get_contract_or_404(db, user, contract_id)
    versions = _versions(db, user.tenant_id, contract.id)
    latest = versions[-1] if versions else None
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kontrak belum punya versi")
    try:
        if latest.contract_type != "PKWT":
            raise ValueError("Hanya kontrak PKWT yang dapat dikonversi ke PKWTT")
        effective = body.effective_date or (latest.valid_to + timedelta(days=1))
        if effective <= latest.valid_from:
            raise ValueError("Tanggal konversi harus setelah versi berjalan dimulai")
        number = (body.new_contract_number or "").strip() or latest.contract_number
        _ensure_number_unique(db, user.tenant_id, number,
                              exclude_contract_id=contract.id)
        version = ed.insert_record(
            db=db,
            tenant_id=user.tenant_id,
            model=ContractInfo,
            identity_field="contract_id",
            identity_value=contract.id,
            valid_from=effective,
            valid_to=None,
            values={"contract_type": "PKWTT", "contract_number": number},
            event="contract_conversion",
            event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="lifecycle",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="insert",
        object_type="contract_info",
        object_id=version.id,
        new_values=snapshot(version, _VERSION_FIELDS),
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    _job_sidecar(db, user, request, contract.employment_id, effective,
                 "contract_conversion", body.event_reason, body.reason)
    db.commit()
    return _out(db, user.tenant_id, contract)


