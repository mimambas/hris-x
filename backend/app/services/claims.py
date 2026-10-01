"""Klaim reimbursement karyawan (Sprint 8, PRD Bagian 11.5 BEN-001).

Alur: draft -> submitted -> approved_l1 (atasan) -> approved (HR/Finance)
       -> paid. Reimbursement yang dibayar via payroll masuk payroll run
       sebagai earning NON-PAJAK (lihat services/payroll.py).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.models import Claim, ClaimType, Employment
from app.services import leave as leave_service

CLAIM_TYPES_SEED = [
    {
        "code": "klaim_kesehatan",
        "name": "Klaim Kesehatan (Rawat Jalan)",
        "limit_per_year": 10_000_000,
        "limit_per_claim": 2_000_000,
        "requires_receipt": True,
    },
    {
        "code": "klaim_kacamata",
        "name": "Klaim Kacamata",
        "limit_per_year": 2_500_000,
        "limit_per_claim": 2_500_000,
        "requires_receipt": True,
    },
    {
        "code": "klaim_melahirkan",
        "name": "Klaim Melahirkan",
        "limit_per_year": 15_000_000,
        "limit_per_claim": 15_000_000,
        "requires_receipt": True,
    },
    {
        "code": "klaim_transport",
        "name": "Klaim Transport",
        "limit_per_year": 6_000_000,
        "limit_per_claim": 1_000_000,
        "requires_receipt": False,
    },
    {
        "code": "klaim_pulsa",
        "name": "Klaim Pulsa/Internet",
        "limit_per_year": 3_600_000,
        "limit_per_claim": 300_000,
        "requires_receipt": False,
    },
]

# Status yang menghabiskan plafon tahunan (draft/rejected/cancelled tidak).
CONSUMING_STATUSES = ("submitted", "approved_l1", "approved", "paid")


def seed_claim_types(db: Session, tenant_id) -> None:
    """Seed jenis klaim bawaan Indonesia; idempoten per kode."""
    existing = {
        r[0]
        for r in db.execute(
            select(ClaimType.code).where(ClaimType.tenant_id == tenant_id)
        ).all()
    }
    for spec in CLAIM_TYPES_SEED:
        if spec["code"] in existing:
            continue
        db.add(ClaimType(tenant_id=tenant_id, **spec))
    db.flush()


def get_claim_type(db: Session, tenant_id, claim_type_id) -> ClaimType:
    ct = db.get(ClaimType, claim_type_id)
    if ct is None or ct.tenant_id != tenant_id:
        raise KeyError("Jenis klaim tidak ditemukan")
    return ct


def get_claim(db: Session, tenant_id, claim_id) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.tenant_id != tenant_id:
        raise KeyError("Klaim tidak ditemukan")
    return claim


def _yearly_used(db: Session, tenant_id, employment_id, claim_type_id,
                 year: int, exclude_id=None) -> int:
    q = (
        select(func.coalesce(func.sum(Claim.amount), 0))
        .where(
            Claim.tenant_id == tenant_id,
            Claim.employment_id == employment_id,
            Claim.claim_type_id == claim_type_id,
            Claim.status.in_(CONSUMING_STATUSES),
            # STAGING-FIX (2026-10-01): func.strftime hanya ada di SQLite;
            # extract() portabel SQLite <-> Postgres.
            extract("year", Claim.claim_date) == year,
        )
    )
    if exclude_id is not None:
        q = q.where(Claim.id != exclude_id)
    return int(db.execute(q).scalar() or 0)


def _check_limits(db: Session, tenant_id, claim: Claim) -> None:
    ct = get_claim_type(db, tenant_id, claim.claim_type_id)
    if not ct.active:
        raise ValueError(f"Jenis klaim '{ct.name}' sedang nonaktif")
    if ct.limit_per_claim is not None and claim.amount > ct.limit_per_claim:
        raise ValueError(
            f"Nominal Rp{claim.amount:,} melebihi plafon per pengajuan "
            f"Rp{ct.limit_per_claim:,} ({ct.name})"
        )
    if ct.limit_per_year is not None:
        used = _yearly_used(
            db, tenant_id, claim.employment_id, claim.claim_type_id,
            claim.claim_date.year, exclude_id=claim.id,
        )
        if used + claim.amount > ct.limit_per_year:
            raise ValueError(
                f"Plafon tahunan {ct.name} terlampaui: terpakai "
                f"Rp{used:,}, pengajuan Rp{claim.amount:,}, "
                f"batas Rp{ct.limit_per_year:,}"
            )


def create_claim(*, db: Session, tenant_id, employment_id, claim_type_id,
                 amount: int, claim_date: date, description: str | None,
                 receipt_document_id, paid_via: str = "payroll",
                 created_by) -> Claim:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != tenant_id:
        raise KeyError("Employment tidak ditemukan")
    ct = get_claim_type(db, tenant_id, claim_type_id)
    if not ct.active:
        raise ValueError(f"Jenis klaim '{ct.name}' sedang nonaktif")
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Nominal klaim harus lebih dari 0")
    if paid_via not in ("payroll", "transfer"):
        raise ValueError("paid_via harus 'payroll' atau 'transfer'")
    if claim_date > date.today():
        raise ValueError("Tanggal klaim tidak boleh di masa depan")
    claim = Claim(
        tenant_id=tenant_id, employment_id=employment_id,
        claim_type_id=claim_type_id, amount=amount, claim_date=claim_date,
        description=description,
        receipt_document_id=receipt_document_id,
        paid_via=paid_via, created_by_user_id=created_by,
    )
    db.add(claim)
    db.flush()
    _check_limits(db, tenant_id, claim)
    return claim


def submit_claim(*, db: Session, tenant_id, claim_id) -> Claim:
    claim = get_claim(db, tenant_id, claim_id)
    if claim.status != "draft":
        raise ValueError("Hanya klaim 'draft' yang bisa disubmit")
    ct = get_claim_type(db, tenant_id, claim.claim_type_id)
    if ct.requires_receipt and not claim.receipt_document_id:
        raise ValueError(
            f"Jenis klaim '{ct.name}' wajib melampirkan struk/nota"
        )
    _check_limits(db, tenant_id, claim)
    claim.status = "submitted"
    claim.submitted_at = datetime.now()
    db.flush()
    return claim


def approve_l1(*, db: Session, tenant_id, claim_id, approver_user,
               approver_employment_id) -> Claim:
    """submitted -> approved_l1. Hanya atasan langsung (atau superadmin)."""
    claim = get_claim(db, tenant_id, claim_id)
    if claim.status != "submitted":
        raise ValueError("Hanya klaim 'submitted' yang bisa di-approve L1")
    if (approver_employment_id is not None
            and str(approver_employment_id) == str(claim.employment_id)):
        raise ValueError("Tidak bisa menyetujui klaim sendiri")
    if not (
        leave_service.is_manager_of(
            db, tenant_id, approver_employment_id, claim.employment_id)
        or approver_user.is_superadmin
    ):
        raise ValueError("Approval L1 hanya oleh atasan langsung")
    claim.status = "approved_l1"
    claim.l1_approved_by_user_id = approver_user.id
    claim.l1_approved_at = datetime.now()
    db.flush()
    return claim


def approve_final(*, db: Session, tenant_id, claim_id, approver_user,
                  approver_employment_id, can_approve: bool) -> Claim:
    """approved_l1 -> approved. Hanya HR/Finance (izin correct)."""
    claim = get_claim(db, tenant_id, claim_id)
    if claim.status != "approved_l1":
        raise ValueError("Hanya klaim 'approved_l1' yang bisa di-approve final")
    if (approver_employment_id is not None
            and str(approver_employment_id) == str(claim.employment_id)):
        raise ValueError("Tidak bisa menyetujui klaim sendiri")
    if not (can_approve or approver_user.is_superadmin):
        raise ValueError("Approval final hanya oleh HR/Finance")
    # Cek ulang plafon saat final (bisa berubah sejak submit).
    _check_limits(db, tenant_id, claim)
    claim.status = "approved"
    claim.approved_by_user_id = approver_user.id
    claim.approved_at = datetime.now()
    db.flush()
    return claim


def reject_claim(*, db: Session, tenant_id, claim_id, approver_user,
                 reason: str) -> Claim:
    if not reason or not reason.strip():
        raise ValueError("Alasan penolakan wajib diisi")
    claim = get_claim(db, tenant_id, claim_id)
    if claim.status not in ("submitted", "approved_l1"):
        raise ValueError("Hanya klaim aktif yang bisa ditolak")
    claim.status = "rejected"
    claim.rejection_reason = reason.strip()
    db.flush()
    return claim


def cancel_claim(*, db: Session, tenant_id, claim_id) -> Claim:
    claim = get_claim(db, tenant_id, claim_id)
    if claim.status not in ("draft", "submitted"):
        raise ValueError("Klaim tidak dalam status yang bisa dibatalkan")
    claim.status = "cancelled"
    claim.cancelled_at = datetime.now()
    db.flush()
    return claim


def mark_paid(*, db: Session, tenant_id, claim_id, paid_by_user_id,
              payment_ref: str | None = None) -> Claim:
    """approved -> paid. Dicatat oleh HR/Finance setelah dana dibayar."""
    claim = get_claim(db, tenant_id, claim_id)
    if claim.status != "approved":
        raise ValueError("Hanya klaim 'approved' yang bisa ditandai dibayar")
    claim.status = "paid"
    claim.paid_by_user_id = paid_by_user_id
    claim.paid_at = datetime.now()
    claim.payment_ref = payment_ref
    db.flush()
    return claim


def claim_summary(db: Session, tenant_id, employment_id,
                  year: int) -> list[dict]:
    """Sisa plafon per jenis klaim untuk satu karyawan dalam satu tahun."""
    types = (
        db.execute(
            select(ClaimType)
            .where(ClaimType.tenant_id == tenant_id, ClaimType.active.is_(True))
            .order_by(ClaimType.code)
        )
        .scalars()
        .all()
    )
    out = []
    for ct in types:
        used = _yearly_used(db, tenant_id, employment_id, ct.id, year)
        out.append({
            "claim_type_id": str(ct.id),
            "claim_type_code": ct.code,
            "claim_type_name": ct.name,
            "limit_per_year": ct.limit_per_year,
            "used": used,
            "remaining": (ct.limit_per_year - used)
            if ct.limit_per_year is not None else None,
        })
    return out


def payable_for_period(db: Session, tenant_id, period_start: date,
                       period_end: date, employment_ids) -> dict[str, dict]:
    """Klaim approved/paid via payroll yang belum masuk run mana pun.

    Kembalikan {employment_id_str: {"amount": int, "claim_ids": [str]}}.
    Dipakai payroll run (integrasi BEN-001).
    """
    emp_set = {str(e) for e in employment_ids}
    rows = (
        db.execute(
            select(Claim).where(
                Claim.tenant_id == tenant_id,
                Claim.status.in_(("approved", "paid")),
                Claim.paid_via == "payroll",
                Claim.payroll_run_id.is_(None),
                Claim.claim_date <= period_end,
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, dict] = {}
    for r in rows:
        key = str(r.employment_id)
        if key not in emp_set:
            continue
        slot = out.setdefault(key, {"amount": 0, "claim_ids": []})
        slot["amount"] += r.amount
        slot["claim_ids"].append(str(r.id))
    return out


def attach_to_run(db: Session, claim_ids: list[str], run_id) -> None:
    """Tandai klaim sudah dibawa oleh satu payroll run."""
    import uuid as _uuid

    if not claim_ids:
        return
    ids = [_uuid.UUID(x) if isinstance(x, str) else x for x in claim_ids]
    rows = (
        db.execute(select(Claim).where(Claim.id.in_(ids)))
        .scalars()
        .all()
    )
    for r in rows:
        r.payroll_run_id = run_id
    db.flush()
