"""Pinjaman/kasbon karyawan dengan cicilan otomatis dari payroll
(Sprint 8, PRD Bagian 11.5 BEN-003).

Alur: draft -> submitted -> active (approve) -> completed.
Cicilan dibuat per periode payroll (lazy) dan dipotong sebagai deduction
"cicilan_pinjaman"; angsuran ditandai paid saat payroll run dikunci.
Pelunasan dipercepat: payoff -> angsuran "payoff" di periode terbuka
berikutnya.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CompInfo, Employment, Loan, LoanInstallment
from app.models import TenantLoanPolicy
from app.services import effective_dating as ed

# Status pinjaman yang dihitung sebagai "masih aktif" (1 per karyawan).
ACTIVE_STATUSES = ("submitted", "approved", "active")


def get_loan_policy(db: Session, tenant_id) -> TenantLoanPolicy:
    policy = (
        db.execute(
            select(TenantLoanPolicy).where(
                TenantLoanPolicy.tenant_id == tenant_id)
        )
        .scalars()
        .first()
    )
    if policy is None:
        policy = TenantLoanPolicy(tenant_id=tenant_id)
        db.add(policy)
        db.flush()
    return policy


def update_loan_policy(db: Session, tenant_id, **fields) -> TenantLoanPolicy:
    policy = get_loan_policy(db, tenant_id)
    allowed = ("max_amount_multiplier", "max_tenor_months",
               "default_interest_rate", "allow_multiple_active")
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Field kebijakan '{key}' tidak dikenal")
        setattr(policy, key, value)
    if float(policy.max_amount_multiplier) <= 0:
        raise ValueError("max_amount_multiplier harus > 0")
    if int(policy.max_tenor_months) <= 0:
        raise ValueError("max_tenor_months harus > 0")
    if float(policy.default_interest_rate) < 0:
        raise ValueError("default_interest_rate tidak boleh negatif")
    db.flush()
    return policy


def _monthly_salary(db: Session, tenant_id, employment_id) -> int:
    """Gaji bulanan = gaji_pokok + tunjangan_tetap (CompInfo kini)."""
    comp = ed.as_of(
        db=db, tenant_id=tenant_id, model=CompInfo,
        identity_field="employment_id", identity_value=employment_id,
        as_of_date=date.today(),
    )
    if comp is None or not comp.components:
        return 0
    return int(comp.components.get("gaji_pokok", 0) or 0) + int(
        comp.components.get("tunjangan_tetap", 0) or 0)


def _flat_total(principal: int, annual_rate: float, tenor: int) -> int:
    """Total bayar = pokok + bunga flat (rate tahunan x tenor/12)."""
    interest = round(principal * float(annual_rate) * tenor / 12)
    return int(principal + interest)


def get_loan(db: Session, tenant_id, loan_id) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None or loan.tenant_id != tenant_id:
        raise KeyError("Pinjaman tidak ditemukan")
    return loan


def active_loan(db: Session, tenant_id, employment_id,
               exclude_id=None) -> Loan | None:
    q = select(Loan).where(
        Loan.tenant_id == tenant_id,
        Loan.employment_id == employment_id,
        Loan.status.in_(ACTIVE_STATUSES),
    )
    if exclude_id is not None:
        q = q.where(Loan.id != exclude_id)
    return db.execute(q).scalars().first()


def create_loan(*, db: Session, tenant_id, employment_id, amount: int,
                tenor_months: int, purpose: str | None,
                interest_rate: float | None, created_by) -> Loan:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != tenant_id:
        raise KeyError("Employment tidak ditemukan")
    amount = int(amount)
    tenor_months = int(tenor_months)
    if amount <= 0:
        raise ValueError("Nominal pinjaman harus lebih dari 0")
    if tenor_months <= 0:
        raise ValueError("Tenor harus lebih dari 0 bulan")
    policy = get_loan_policy(db, tenant_id)
    rate = (float(interest_rate) if interest_rate is not None
            else float(policy.default_interest_rate))
    if rate < 0:
        raise ValueError("Bunga tidak boleh negatif")
    loan = Loan(
        tenant_id=tenant_id, employment_id=employment_id,
        principal_amount=amount, interest_rate=rate,
        tenor_months=tenor_months, purpose=purpose,
        created_by_user_id=created_by,
    )
    db.add(loan)
    db.flush()
    return loan


def submit_loan(*, db: Session, tenant_id, loan_id) -> Loan:
    loan = get_loan(db, tenant_id, loan_id)
    if loan.status != "draft":
        raise ValueError("Hanya pinjaman 'draft' yang bisa disubmit")
    loan.status = "submitted"
    loan.submitted_at = datetime.now()
    db.flush()
    return loan


def approve_loan(*, db: Session, tenant_id, loan_id, approver_user,
                 can_approve: bool) -> Loan:
    """submitted -> active. Hanya HR/Finance (izin correct)."""
    loan = get_loan(db, tenant_id, loan_id)
    if loan.status != "submitted":
        raise ValueError("Hanya pinjaman 'submitted' yang bisa disetujui")
    if not (can_approve or approver_user.is_superadmin):
        raise ValueError("Persetujuan pinjaman hanya oleh HR/Finance")
    policy = get_loan_policy(db, tenant_id)
    if not policy.allow_multiple_active and active_loan(
            db, tenant_id, loan.employment_id, exclude_id=loan.id):
        raise ValueError(
            "Karyawan masih punya pinjaman aktif; "
            "lunasi dulu sebelum mengajukan baru"
        )
    if loan.tenor_months > policy.max_tenor_months:
        raise ValueError(
            f"Tenor {loan.tenor_months} bulan melebihi maksimal "
            f"{policy.max_tenor_months} bulan"
        )
    salary = _monthly_salary(db, tenant_id, loan.employment_id)
    max_amount = int(salary * float(policy.max_amount_multiplier))
    if salary <= 0:
        raise ValueError(
            "Data gaji karyawan belum diisi; pinjaman tidak bisa disetujui"
        )
    if loan.principal_amount > max_amount:
        raise ValueError(
            f"Nominal Rp{loan.principal_amount:,} melebihi batas "
            f"Rp{max_amount:,} "
            f"({float(policy.max_amount_multiplier):g}x gaji bulanan)"
        )
    total = _flat_total(loan.principal_amount, float(loan.interest_rate),
                        loan.tenor_months)
    loan.total_payable = total
    loan.monthly_installment = total // loan.tenor_months
    loan.remaining_total = total
    loan.status = "active"
    loan.approved_by_user_id = approver_user.id
    loan.approved_at = datetime.now()
    db.flush()
    return loan


def reject_loan(*, db: Session, tenant_id, loan_id, approver_user,
                reason: str) -> Loan:
    if not reason or not reason.strip():
        raise ValueError("Alasan penolakan wajib diisi")
    loan = get_loan(db, tenant_id, loan_id)
    if loan.status != "submitted":
        raise ValueError("Hanya pinjaman 'submitted' yang bisa ditolak")
    loan.status = "rejected"
    loan.rejection_reason = reason.strip()
    db.flush()
    return loan


def cancel_loan(*, db: Session, tenant_id, loan_id) -> Loan:
    loan = get_loan(db, tenant_id, loan_id)
    if loan.status not in ("draft", "submitted"):
        raise ValueError("Pinjaman tidak dalam status yang bisa dibatalkan")
    loan.status = "cancelled"
    loan.cancelled_at = datetime.now()
    db.flush()
    return loan


def _next_open_period(db: Session, tenant_id) -> str:
    """Periode payroll berikutnya yang belum punya run (untuk payoff)."""
    from app.models import PayrollRun  # impor lokal: hindari siklus
    latest = db.execute(
        select(func.max(PayrollRun.period)).where(
            PayrollRun.tenant_id == tenant_id)
    ).scalar()
    if latest:
        y, m = int(latest[:4]), int(latest[5:7])
        m += 1
        if m > 12:
            y, m = y + 1, 1
        return f"{y:04d}-{m:02d}"
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def payoff_loan(*, db: Session, tenant_id, loan_id) -> LoanInstallment:
    """Pelunasan dipercepat: sisa total menjadi angsuran 'payoff' di
    periode terbuka berikutnya (dipotong di payroll run berikutnya)."""
    loan = get_loan(db, tenant_id, loan_id)
    if loan.status != "active":
        raise ValueError("Hanya pinjaman 'active' yang bisa dilunasi")
    if loan.remaining_total <= 0:
        raise ValueError("Pinjaman sudah lunas")
    existing = db.execute(
        select(LoanInstallment).where(
            LoanInstallment.tenant_id == tenant_id,
            LoanInstallment.loan_id == loan.id,
            LoanInstallment.kind == "payoff",
            LoanInstallment.status == "pending",
        )
    ).scalars().first()
    if existing:
        raise ValueError("Pelunasan sudah dijadwalkan "
                         f"untuk periode {existing.period}")
    period = _next_open_period(db, tenant_id)
    inst = LoanInstallment(
        tenant_id=tenant_id, loan_id=loan.id, period=period,
        amount=loan.remaining_total, kind="payoff", status="pending",
    )
    db.add(inst)
    db.flush()
    return inst


def installments_for_period(db: Session, tenant_id, period: str,
                            employment_ids) -> dict[str, dict]:
    """Angsuran (regular/payoff) untuk satu periode payroll.

    Baris angsuran dibuat lazy di sini (idempoten per loan+period).
    Kembalikan {employment_id_str: {"amount": int, "installment_ids": [...]}}.
    """
    emp_set = {str(e) for e in employment_ids}
    loans = (
        db.execute(
            select(Loan).where(
                Loan.tenant_id == tenant_id,
                Loan.status == "active",
                Loan.remaining_total > 0,
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, dict] = {}
    for loan in loans:
        key = str(loan.employment_id)
        if key not in emp_set:
            continue
        payoff = db.execute(
            select(LoanInstallment).where(
                LoanInstallment.tenant_id == tenant_id,
                LoanInstallment.loan_id == loan.id,
                LoanInstallment.kind == "payoff",
                LoanInstallment.status == "pending",
            )
        ).scalars().first()
        if payoff is not None:
            if payoff.period != period:
                continue  # payoff dijadwalkan periode lain
            inst = payoff
        else:
            inst = db.execute(
                select(LoanInstallment).where(
                    LoanInstallment.loan_id == loan.id,
                    LoanInstallment.period == period,
                )
            ).scalars().first()
            if inst is None:
                amount = min(loan.monthly_installment, loan.remaining_total)
                if amount <= 0:
                    continue
                inst = LoanInstallment(
                    tenant_id=tenant_id, loan_id=loan.id, period=period,
                    amount=amount, kind="regular", status="pending",
                )
                db.add(inst)
                db.flush()
        slot = out.setdefault(key, {"amount": 0, "installment_ids": []})
        slot["amount"] += inst.amount
        slot["installment_ids"].append(str(inst.id))
    return out


def attach_to_run(db: Session, installment_ids: list[str], run_id) -> None:
    import uuid as _uuid

    if not installment_ids:
        return
    ids = [_uuid.UUID(x) if isinstance(x, str) else x
           for x in installment_ids]
    rows = (
        db.execute(
            select(LoanInstallment).where(
                LoanInstallment.id.in_(ids))
        )
        .scalars()
        .all()
    )
    for r in rows:
        r.payroll_run_id = run_id
    db.flush()


def settle_run_installments(db: Session, tenant_id, run_id) -> dict:
    """Tandai angsuran pada run yang dikunci sebagai paid; kurangi sisa
    pinjaman; selesaikan pinjaman yang lunas. Dipanggil dari lock_run."""
    rows = (
        db.execute(
            select(LoanInstallment).where(
                LoanInstallment.tenant_id == tenant_id,
                LoanInstallment.payroll_run_id == run_id,
                LoanInstallment.status == "pending",
            )
        )
        .scalars()
        .all()
    )
    settled = 0
    completed = 0
    for inst in rows:
        inst.status = "paid"
        inst.paid_at = datetime.now()
        loan = db.get(Loan, inst.loan_id)
        loan.remaining_total = max(loan.remaining_total - inst.amount, 0)
        settled += 1
        if loan.remaining_total <= 0 and loan.status == "active":
            loan.status = "completed"
            loan.paid_off_at = datetime.now()
            completed += 1
    db.flush()
    return {"settled": settled, "completed": completed}


def loan_installments(db: Session, tenant_id, loan_id) -> list[LoanInstallment]:
    loan = get_loan(db, tenant_id, loan_id)
    return (
        db.execute(
            select(LoanInstallment)
            .where(LoanInstallment.loan_id == loan.id)
            .order_by(LoanInstallment.period)
        )
        .scalars()
        .all()
    )
