"""Cuti/izin: jenis, saldo akrual pro-rata, approval 2 level, cuti bersama
(PRD Bagian 10.5, LEV-001 s/d LEV-007).

Alur status: draft -> submitted -> approved_l1 -> approved | rejected;
cancelled bisa dari submitted/approved_l1/approved (sebelum tanggal mulai).
Setiap transisi tercatat di audit dengan actor + timestamp (dipanggil dari
lapisan API).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Employment,
    Holiday,
    JobInfo,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Person,
    TenantLeavePolicy,
)
from app.services import effective_dating as ed

# (code, name, quota_days, accrual, min_service_months, requires_doc,
#  deducts_balance)
LEAVE_TYPES_SEED: list[tuple] = [
    ("cuti_tahunan", "Cuti Tahunan", 12, "monthly", 0, False, True),
    ("cuti_sakit", "Cuti Sakit", 12, "none", 0, True, True),
    ("cuti_melahirkan", "Cuti Melahirkan", 90, "none", 0, True, True),
    ("cuti_besar", "Cuti Besar", 0, "none", 72, False, True),
    ("izin", "Izin", 0, "none", 0, False, False),
]


def seed_leave_types(db: Session, tenant_id) -> None:
    """Seed 5 jenis cuti Indonesia. Idempoten."""
    for code, name, quota, accrual, min_svc, req_doc, deducts in LEAVE_TYPES_SEED:
        exists = (
            db.execute(
                select(LeaveType.id).where(
                    LeaveType.tenant_id == tenant_id, LeaveType.code == code
                )
            ).first()
        )
        if not exists:
            db.add(
                LeaveType(
                    tenant_id=tenant_id, code=code, name=name,
                    quota_days=quota, accrual=accrual,
                    min_service_months=min_svc, requires_doc=req_doc,
                    deducts_balance=deducts,
                )
            )
    db.flush()


def get_leave_policy(db: Session, tenant_id) -> TenantLeavePolicy:
    policy = (
        db.execute(
            select(TenantLeavePolicy).where(
                TenantLeavePolicy.tenant_id == tenant_id
            )
        )
        .scalars()
        .first()
    )
    if policy is None:
        policy = TenantLeavePolicy(tenant_id=tenant_id)
        db.add(policy)
        db.flush()
    return policy


def get_leave_type(db: Session, tenant_id, leave_type_id) -> LeaveType:
    lt = db.get(LeaveType, leave_type_id)
    if lt is None or lt.tenant_id != tenant_id or not lt.is_active:
        raise KeyError("Jenis cuti tidak ditemukan")
    return lt


def months_of_service(start: date, as_of: date) -> int:
    months = (as_of.year - start.year) * 12 + (as_of.month - start.month)
    if as_of.day < start.day:
        months -= 1
    return max(months, 0)


def chargeable_days(
    db: Session, tenant_id, start: date, end: date
) -> int:
    """Hari cuti yang memotong saldo: Senin-Jumat di luar libur tenant."""
    if end < start:
        raise ValueError("Tanggal selesai tidak boleh sebelum tanggal mulai")
    holidays = {
        h.date
        for h in db.execute(
            select(Holiday).where(
                Holiday.tenant_id == tenant_id,
                Holiday.date >= start, Holiday.date <= end,
            )
        )
        .scalars()
        .all()
    }
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            n += 1
        d += timedelta(days=1)
    return n


def _remaining_months_in_year(start: date, year: int) -> int:
    if start.year > year:
        return 0
    if start.year < year:
        return 12
    return 12 - start.month + 1


def entitled_days(employment: Employment, leave_type: LeaveType, year: int) -> int:
    """Hak cuti setahun; pro-rata untuk join mid-year (accrual=monthly)."""
    if months_of_service(employment.start_date, date(year, 12, 31)) < (
        leave_type.min_service_months
    ):
        return 0
    if leave_type.accrual == "monthly":
        months = _remaining_months_in_year(employment.start_date, year)
        return round(leave_type.quota_days * months / 12)
    return leave_type.quota_days


def ensure_balance(
    db: Session, tenant_id, employment: Employment, leave_type: LeaveType,
    year: int,
) -> LeaveBalance:
    """Buat/refresh saldo tahun berjalan (idempoten per tahun)."""
    bal = (
        db.execute(
            select(LeaveBalance).where(
                LeaveBalance.tenant_id == tenant_id,
                LeaveBalance.employment_id == employment.id,
                LeaveBalance.leave_type_id == leave_type.id,
                LeaveBalance.year == year,
            )
        )
        .scalars()
        .first()
    )
    entitled = entitled_days(employment, leave_type, year)
    if bal is None:
        bal = LeaveBalance(
            tenant_id=tenant_id, employment_id=employment.id,
            leave_type_id=leave_type.id, year=year,
            entitled=entitled, used=0, remaining=entitled,
        )
        db.add(bal)
    else:
        # Refresh hak bila masa kerja berubah (mis. melewati min_service).
        delta = entitled - bal.entitled
        bal.entitled = entitled
        bal.remaining = max(bal.remaining + delta, 0)
    db.flush()
    return bal


def _overlapping_request(
    db: Session, tenant_id, employment_id, start: date, end: date,
    exclude_id=None,
) -> bool:
    stmt = select(LeaveRequest.id).where(
        LeaveRequest.tenant_id == tenant_id,
        LeaveRequest.employment_id == employment_id,
        LeaveRequest.status.in_(("submitted", "approved_l1", "approved")),
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    )
    if exclude_id is not None:
        stmt = stmt.where(LeaveRequest.id != exclude_id)
    return db.execute(stmt.limit(1)).first() is not None


def _check_blackout(policy: TenantLeavePolicy, start: date, end: date) -> None:
    for b in policy.blackout_dates or []:
        try:
            bs = date.fromisoformat(b["start"])
            be = date.fromisoformat(b["end"])
        except (KeyError, ValueError):
            continue
        if start <= be and end >= bs:
            raise ValueError(
                f"Periode blackout: {b.get('name', 'tanpa nama')} "
                f"({bs.isoformat()} s.d. {be.isoformat()})"
            )


def create_request(
    *, db: Session, tenant_id, employment_id, leave_type_id,
    start_date: date, end_date: date, reason: str | None = None,
    created_by=None,
) -> LeaveRequest:
    """Buat draft pengajuan; validasi kebijakan (saldo dicek saat submit)."""
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != tenant_id:
        raise KeyError("Employment tidak ditemukan")
    lt = get_leave_type(db, tenant_id, leave_type_id)
    policy = get_leave_policy(db, tenant_id)
    days = chargeable_days(db, tenant_id, start_date, end_date)
    if days > policy.max_consecutive_days:
        raise ValueError(
            f"Maksimal {policy.max_consecutive_days} hari berturut-turut"
        )
    _check_blackout(policy, start_date, end_date)
    if _overlapping_request(db, tenant_id, employment_id, start_date, end_date):
        raise ValueError("Sudah ada pengajuan cuti yang tumpang tindih")
    if lt.requires_doc and not reason:
        # Dokumen dipersyaratkan; alasan rinci minimal sebagai pengganti
        # sementara (unggah dokumen = pekerjaan lanjutan).
        raise ValueError(
            f"Jenis cuti '{lt.name}' mewajibkan dokumen pendukung/keterangan"
        )
    req = LeaveRequest(
        tenant_id=tenant_id, employment_id=employment_id,
        leave_type_id=leave_type_id, start_date=start_date, end_date=end_date,
        days=days, reason=reason, status="draft",
        created_by_user_id=created_by,
    )
    db.add(req)
    db.flush()
    return req


def submit_request(*, db: Session, tenant_id, request_id) -> LeaveRequest:
    """draft -> submitted. Cek saldo cukup (bila memotong saldo)."""
    req = _get_request(db, tenant_id, request_id)
    if req.status != "draft":
        raise ValueError("Hanya draft yang bisa disubmit")
    _assert_balance_enough(db, tenant_id, req)
    req.status = "submitted"
    req.submitted_at = datetime.now()
    db.flush()
    return req


def _assert_balance_enough(db: Session, tenant_id, req: LeaveRequest) -> None:
    lt = get_leave_type(db, tenant_id, req.leave_type_id)
    if not lt.deducts_balance:
        return
    emp = db.get(Employment, req.employment_id)
    bal = ensure_balance(db, tenant_id, emp, lt, req.start_date.year)
    if bal.remaining < req.days:
        raise ValueError(
            f"Saldo tidak cukup: sisa {bal.remaining} hari, "
            f"pengajuan {req.days} hari"
        )


def _get_request(db: Session, tenant_id, request_id) -> LeaveRequest:
    req = db.get(LeaveRequest, request_id)
    if req is None or req.tenant_id != tenant_id:
        raise KeyError("Pengajuan cuti tidak ditemukan")
    return req


def _manager_employment_id(db: Session, tenant_id, employment_id) -> object | None:
    job = ed.as_of(
        db=db, tenant_id=tenant_id, model=JobInfo,
        identity_field="employment_id", identity_value=employment_id,
        as_of_date=date.today(),
    )
    return job.manager_employment_id if job else None


def is_manager_of(
    db: Session, tenant_id, approver_employment_id, requester_employment_id
) -> bool:
    """True bila approver adalah atasan langsung requester (org chart
    hari ini) ATAU penerima delegasi aktif dari atasan itu (EXP-013:
    selama atasan cuti, kewenangan approval L1 berpindah ke delegate).
    """
    manager_id = _manager_employment_id(db, tenant_id, requester_employment_id)
    if manager_id is None or approver_employment_id is None:
        return False
    if str(manager_id) == str(approver_employment_id):
        return True
    from app.services import delegation as delegation_service
    return delegation_service.is_delegate_of(
        db, tenant_id, approver_employment_id, manager_id)


def approve_l1(
    *, db: Session, tenant_id, request_id, approver_user,
    approver_employment_id,
) -> LeaveRequest:
    """submitted -> approved_l1. Hanya atasan langsung (atau superadmin)."""
    req = _get_request(db, tenant_id, request_id)
    if req.status != "submitted":
        raise ValueError("Hanya pengajuan 'submitted' yang bisa di-approve L1")
    if (approver_employment_id is not None
            and str(approver_employment_id) == str(req.employment_id)):
        raise ValueError("Tidak bisa menyetujui pengajuan sendiri")
    if not (
        is_manager_of(db, tenant_id, approver_employment_id, req.employment_id)
        or approver_user.is_superadmin
    ):
        raise ValueError("Approval L1 hanya oleh atasan langsung")
    req.status = "approved_l1"
    req.l1_approved_by_user_id = approver_user.id
    req.l1_approved_at = datetime.now()
    db.flush()
    return req


def approve_l2(
    *, db: Session, tenant_id, request_id, approver_user,
    approver_employment_id, can_approve: bool,
) -> LeaveRequest:
    """approved_l1 -> approved (final). Hanya HR (izin correct). Saldo dipotong."""
    req = _get_request(db, tenant_id, request_id)
    if req.status != "approved_l1":
        raise ValueError("Hanya pengajuan 'approved_l1' yang bisa di-approve final")
    if (approver_employment_id is not None
            and str(approver_employment_id) == str(req.employment_id)):
        raise ValueError("Tidak bisa menyetujui pengajuan sendiri")
    if not (can_approve or approver_user.is_superadmin):
        raise ValueError("Approval final hanya oleh HR")
    # Cek ulang saldo saat final (bisa berubah sejak submit).
    _assert_balance_enough(db, tenant_id, req)
    lt = get_leave_type(db, tenant_id, req.leave_type_id)
    if lt.deducts_balance:
        emp = db.get(Employment, req.employment_id)
        bal = ensure_balance(db, tenant_id, emp, lt, req.start_date.year)
        bal.used += req.days
        bal.remaining = bal.entitled - bal.used
    req.status = "approved"
    req.l2_approved_by_user_id = approver_user.id
    req.l2_approved_at = datetime.now()
    db.flush()
    return req


def reject_request(
    *, db: Session, tenant_id, request_id, approver_user, reason: str,
) -> LeaveRequest:
    if not reason or not reason.strip():
        raise ValueError("Alasan penolakan wajib diisi")
    req = _get_request(db, tenant_id, request_id)
    if req.status not in ("submitted", "approved_l1"):
        raise ValueError("Hanya pengajuan aktif yang bisa ditolak")
    req.status = "rejected"
    req.rejection_reason = reason.strip()
    db.flush()
    return req


def cancel_request(
    *, db: Session, tenant_id, request_id, cancelled_by_employment_id,
) -> LeaveRequest:
    """Batalkan sebelum tanggal mulai; saldo yang terpotong dikembalikan."""
    req = _get_request(db, tenant_id, request_id)
    if req.status not in ("submitted", "approved_l1", "approved"):
        raise ValueError("Pengajuan tidak dalam status yang bisa dibatalkan")
    if req.start_date <= date.today():
        raise ValueError("Hanya bisa dibatalkan sebelum tanggal mulai")
    if req.status == "approved":
        lt = get_leave_type(db, tenant_id, req.leave_type_id)
        if lt.deducts_balance:
            emp = db.get(Employment, req.employment_id)
            bal = ensure_balance(db, tenant_id, emp, lt, req.start_date.year)
            bal.used = max(bal.used - req.days, 0)
            bal.remaining = bal.entitled - bal.used
    req.status = "cancelled"
    req.cancelled_at = datetime.now()
    db.flush()
    return req


def apply_mass_leave(
    *, db: Session, tenant_id, holiday: Holiday, actor_user_id,
) -> dict:
    """Terapkan cuti bersama: potong 1 hari saldo cuti tahunan semua
    employment aktif (LEV-003). Idempoten per tanggal via Holiday."""
    try:
        annual = (
            db.execute(
                select(LeaveType).where(
                    LeaveType.tenant_id == tenant_id,
                    LeaveType.code == "cuti_tahunan",
                    LeaveType.is_active.is_(True),
                )
            )
            .scalars()
            .first()
        )
    except Exception:
        annual = None
    if annual is None or not holiday.is_cuti_bersama or not holiday.deducts_leave:
        return {"deducted": 0, "skipped": 0}
    if holiday.mass_leave_applied:
        return {"deducted": 0, "skipped": 0, "already_applied": True}
    today = date.today()
    employments = (
        db.execute(
            select(Employment).where(
                Employment.tenant_id == tenant_id,
                Employment.start_date <= holiday.date,
                Employment.status.in_(("active", "probation")),
            )
        )
        .scalars()
        .all()
    )
    deducted = 0
    skipped = 0
    for emp in employments:
        if emp.end_date is not None and emp.end_date < holiday.date:
            continue
        bal = ensure_balance(db, tenant_id, emp, annual, holiday.date.year)
        if bal.remaining > 0:
            bal.used += 1
            bal.remaining = bal.entitled - bal.used
            deducted += 1
        else:
            skipped += 1
    holiday.mass_leave_applied = True
    db.flush()
    return {"deducted": deducted, "skipped": skipped}


def active_employments(db: Session, tenant_id):
    return (
        db.execute(
            select(Employment).where(
                Employment.tenant_id == tenant_id,
                Employment.status.in_(("active", "probation")),
            )
        )
        .scalars()
        .all()
    )
