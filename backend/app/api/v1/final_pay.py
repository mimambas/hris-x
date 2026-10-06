"""API PAY-014: final pay & pesangon per alasan terminasi.

Konfigurasi tabel (bracket masa kerja + faktor alasan) dapat diganti
per tenant; perhitungan mengikuti services/final_pay.py dengan
snapshot penuh tersimpan per employment. Izin memakai objek payroll:
view untuk baca, insert untuk konfigurasi & buat, correct untuk
finalisasi & penanda dibayar.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Employment, FinalPay, Person, User
from app.schemas.schemas import (
    PayFinalCandidateOut,
    PayFinalConfigIn,
    PayFinalConfigOut,
    PayFinalCreateIn,
    PayFinalOut,
    PayFinalPreviewIn,
    PayFinalPreviewOut,
)
from app.services import final_pay as fp
from app.services.audit import write_audit

router = APIRouter(tags=["final-pay"])


def _person_name(db: Session, person_id: uuid.UUID) -> str | None:
    p = db.get(Person, person_id)
    return p.full_name if p else None


def _get_employment(db: Session, user: User, employment_id: uuid.UUID) -> Employment:
    emp = db.scalar(
        select(Employment).where(
            Employment.id == employment_id,
            Employment.tenant_id == user.tenant_id,
        )
    )
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employment tidak ditemukan.")
    return emp


def _get_final_pay(db: Session, user: User, fp_id: uuid.UUID) -> FinalPay:
    row = db.scalar(
        select(FinalPay).where(
            FinalPay.id == fp_id,
            FinalPay.tenant_id == user.tenant_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Final pay tidak ditemukan.")
    return row


def _out(db: Session, row: FinalPay) -> PayFinalOut:
    """PayFinalOut + nama person ter-resolve (snapshot ORM tak memuatnya)."""
    data = PayFinalOut.model_validate(row).model_dump()
    emp = db.get(Employment, row.employment_id)
    data["person_name"] = _person_name(db, emp.person_id) if emp else None
    return PayFinalOut(**data)


def _resolve_input(db: Session, user: User, body: PayFinalPreviewIn):
    """Tentukan employment, alasan & tanggal terminasi efektif."""
    emp = _get_employment(db, user, body.employment_id)
    info = fp.termination_info(db, emp.id)
    reason = body.reason or (info or {}).get("reason")
    tdate = body.termination_date or emp.end_date or (info or {}).get("date")
    if reason is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Alasan terminasi belum diketahui: employment belum memiliki "
            "kejadian terminasi dan alasan tidak diisi.",
        )
    if tdate is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Tanggal terminasi belum diketahui: employment belum memiliki "
            "tanggal berakhir dan tanggal tidak diisi.",
        )
    return emp, reason, tdate


def _audit(request: Request, db: Session, user: User, action: str,
           row: FinalPay) -> None:
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action=action, object_type="final_pay", object_id=row.id,
        new_values={
            "employment_id": str(row.employment_id),
            "reason": row.reason,
            "status": row.status,
            "net_amount": row.net_amount,
        },
        channel="api", ip=client_ip(request),
    )


# ---------------------------------------------------------------- konfigurasi
@router.get(
    "/final-pay/config",
    response_model=PayFinalConfigOut,
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def get_final_pay_config(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cfg = fp.get_config(db, user.tenant_id)
    db.commit()  # seed bawaan (bila baru) perlu disimpan
    return cfg


@router.put(
    "/final-pay/config",
    response_model=PayFinalConfigOut,
    dependencies=[Depends(require_permission("payroll", "insert"))],
)
def put_final_pay_config(
    body: PayFinalConfigIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cfg = fp.replace_config(
        db,
        user.tenant_id,
        brackets=[b.model_dump() for b in body.brackets],
        reason_factors=[f.model_dump() for f in body.reason_factors],
    )
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="update", object_type="final_pay_config", object_id=None,
        new_values={
            "brackets": len(body.brackets),
            "reason_factors": len(body.reason_factors),
        },
        channel="api", ip=client_ip(request),
    )
    db.commit()
    return cfg


# ---------------------------------------------------------------- kandidat
@router.get(
    "/final-pay/candidates",
    response_model=list[PayFinalCandidateOut],
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def list_final_pay_candidates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emps = db.scalars(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.status == "terminated",
        )
    ).all()
    out: list[PayFinalCandidateOut] = []
    for emp in emps:
        info = fp.termination_info(db, emp.id)
        out.append(PayFinalCandidateOut(
            employment_id=emp.id,
            person_id=emp.person_id,
            person_name=_person_name(db, emp.person_id) or "-",
            termination_date=emp.end_date or (info or {}).get("date"),
            reason=(info or {}).get("reason"),
            has_final_pay=fp.active_final_pay(db, emp.id) is not None,
        ))
    out.sort(key=lambda r: r.person_name)
    return out


# ---------------------------------------------------------------- hitung & buat
@router.post(
    "/final-pay/preview",
    response_model=PayFinalPreviewOut,
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def preview_final_pay(
    body: PayFinalPreviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp, reason, tdate = _resolve_input(db, user, body)
    result = fp.compute(
        db, user.tenant_id, emp, reason, tdate,
        adjustments=[a.model_dump() for a in body.adjustments],
    )
    # Ambil nilai SEBELUM rollback: rollback mengedaluwarsakan objek ORM,
    # dan baca-ulang pasca-rollback di Postgres+RLS bisa gagal melihat
    # baris (ObjectDeletedError) karena konteks tenant transaksi baru.
    out = PayFinalPreviewOut(
        employment_id=emp.id,
        person_name=_person_name(db, emp.person_id),
        **result,
    )
    db.rollback()  # preview tidak menyimpan seed config permanen
    return out


@router.post(
    "/final-pay",
    response_model=PayFinalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("payroll", "insert"))],
)
def create_final_pay(
    body: PayFinalCreateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emp, reason, tdate = _resolve_input(db, user, body)
    existing = fp.active_final_pay(db, emp.id)
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Employment ini sudah memiliki final pay "
            f"({existing.status}). Hapus draft yang ada bila ingin "
            "menghitung ulang.",
        )
    result = fp.compute(
        db, user.tenant_id, emp, reason, tdate,
        adjustments=[a.model_dump() for a in body.adjustments],
    )
    row = FinalPay(
        tenant_id=user.tenant_id,
        employment_id=emp.id,
        status="draft",
        notes=body.notes,
        created_by_user_id=user.id,
        **result,
    )
    db.add(row)
    db.flush()
    _audit(request, db, user, "create", row)
    db.commit()
    return _out(db, row)


# ---------------------------------------------------------------- baca
@router.get(
    "/final-pay",
    response_model=list[PayFinalOut],
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def list_final_pays(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.scalars(
        select(FinalPay)
        .where(FinalPay.tenant_id == user.tenant_id)
        .order_by(FinalPay.created_at.desc())
    ).all()
    out: list[PayFinalOut] = []
    emp_cache: dict[uuid.UUID, Employment | None] = {}
    for row in rows:
        emp = emp_cache.get(row.employment_id)
        if emp is None:
            emp = db.get(Employment, row.employment_id)
            emp_cache[row.employment_id] = emp
        name = _person_name(db, emp.person_id) if emp else None
        out.append(_out(db, row))
    return out


@router.get(
    "/final-pay/{fp_id}",
    response_model=PayFinalOut,
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def get_final_pay(
    fp_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_final_pay(db, user, fp_id)
    emp = db.get(Employment, row.employment_id)
    return _out(db, row)


# ---------------------------------------------------------------- transisi
@router.post(
    "/final-pay/{fp_id}/finalize",
    response_model=PayFinalOut,
    dependencies=[Depends(require_permission("payroll", "correct"))],
)
def finalize_final_pay(
    fp_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    row = _get_final_pay(db, user, fp_id)
    if row.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Final pay berstatus {row.status}; hanya draft yang dapat "
            "difinalisasi.",
        )
    row.status = "finalized"
    row.finalized_at = datetime.now(timezone.utc)
    db.flush()
    _audit(request, db, user, "finalize", row)
    db.commit()
    emp = db.get(Employment, row.employment_id)
    return _out(db, row)


@router.post(
    "/final-pay/{fp_id}/pay",
    response_model=PayFinalOut,
    dependencies=[Depends(require_permission("payroll", "correct"))],
)
def pay_final_pay(
    fp_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from datetime import datetime, timezone

    row = _get_final_pay(db, user, fp_id)
    if row.status != "finalized":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Final pay berstatus {row.status}; finalisasi dulu sebelum "
            "ditandai dibayar.",
        )
    row.status = "paid"
    row.paid_at = datetime.now(timezone.utc)
    db.flush()
    _audit(request, db, user, "pay", row)
    db.commit()
    emp = db.get(Employment, row.employment_id)
    return _out(db, row)


@router.delete(
    "/final-pay/{fp_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("payroll", "insert"))],
)
def delete_final_pay(
    fp_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = _get_final_pay(db, user, fp_id)
    if row.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Final pay berstatus {row.status}; hanya draft yang dapat "
            "dihapus.",
        )
    _audit(request, db, user, "delete", row)
    db.delete(row)
    db.commit()
    return None
