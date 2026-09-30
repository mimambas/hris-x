"""Lembur: pengajuan pra-persetujuan, approval 2 level, kalkulasi upah
(PRD Bagian 10.4, TIM-030 s/d TIM-032).

Kalkulasi default mengikuti PP 35/2021: upah/jam = gaji_pokok / 173,
jam pertama 1,5x, jam berikutnya 2x. Tabel pengali bertanggal efektif
(OvertimeRate) siap diganti bila regulasi berubah.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    MAX_DATE,
    CompInfo,
    Employment,
    OvertimeRate,
    OvertimeRequest,
)
from app.services import effective_dating as ed


def seed_overtime_rate(db: Session, tenant_id) -> None:
    """Seed tabel pengali default. Idempoten."""
    exists = (
        db.execute(
            select(OvertimeRate.id).where(OvertimeRate.tenant_id == tenant_id)
        ).first()
    )
    if not exists:
        db.add(
            OvertimeRate(
                tenant_id=tenant_id, valid_from=date(2020, 1, 1),
                first_hour_mult=1.5, next_hour_mult=2.0, divisor=173,
            )
        )
    db.flush()


def get_rate(db: Session, tenant_id, day: date) -> OvertimeRate:
    rate = (
        db.execute(
            select(OvertimeRate)
            .where(
                OvertimeRate.tenant_id == tenant_id,
                OvertimeRate.valid_from <= day,
                OvertimeRate.valid_to >= day,
            )
            .order_by(OvertimeRate.valid_from.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if rate is None:
        rate = OvertimeRate(
            tenant_id=tenant_id, valid_from=date(2020, 1, 1),
            first_hour_mult=1.5, next_hour_mult=2.0, divisor=173,
        )
        db.add(rate)
        db.flush()
    return rate


def _parse_hhmm(value: str) -> time:
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        raise ValueError("Format jam harus 'HH:MM'")


def _gaji_pokok(db: Session, tenant_id, employment_id, day: date) -> int:
    comp = ed.as_of(
        db=db, tenant_id=tenant_id, model=CompInfo,
        identity_field="employment_id", identity_value=employment_id,
        as_of_date=day,
    )
    if comp and comp.components:
        return int(comp.components.get("gaji_pokok", 0) or 0)
    return 0


def compute_pay(
    db: Session, tenant_id, employment_id, day: date, hours: float
) -> int:
    """Upah lembur: 1,5x jam pertama + 2x jam berikutnya (PP 35/2021)."""
    rate = get_rate(db, tenant_id, day)
    gaji_pokok = _gaji_pokok(db, tenant_id, employment_id, day)
    hourly = gaji_pokok / float(rate.divisor) if gaji_pokok else 0
    first = min(hours, 1.0) * float(rate.first_hour_mult)
    rest = max(hours - 1.0, 0.0) * float(rate.next_hour_mult)
    return int(round(hourly * (first + rest)))


def _get_request(db: Session, tenant_id, request_id) -> OvertimeRequest:
    req = db.get(OvertimeRequest, request_id)
    if req is None or req.tenant_id != tenant_id:
        raise KeyError("Pengajuan lembur tidak ditemukan")
    return req


def create_request(
    *, db: Session, tenant_id, employment_id, day: date,
    start_time: str, end_time: str, reason: str | None = None,
    created_by=None,
) -> OvertimeRequest:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != tenant_id:
        raise KeyError("Employment tidak ditemukan")
    start_t = _parse_hhmm(start_time)
    end_t = _parse_hhmm(end_time)
    start_dt = datetime.combine(day, start_t)
    end_dt = datetime.combine(day, end_t)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)  # lembur lewat tengah malam
    hours = (end_dt - start_dt).total_seconds() / 3600
    if hours > 4:
        raise ValueError("Batas lembur 4 jam per hari (PP 35/2021)")
    if hours <= 0:
        raise ValueError("Durasi lembur harus positif")
    req = OvertimeRequest(
        tenant_id=tenant_id, employment_id=employment_id, date=day,
        start_time=start_dt, end_time=end_dt,
        hours=round(hours, 2), reason=reason, status="draft",
        created_by_user_id=created_by,
    )
    db.add(req)
    db.flush()
    return req


def submit_request(*, db: Session, tenant_id, request_id) -> OvertimeRequest:
    req = _get_request(db, tenant_id, request_id)
    if req.status != "draft":
        raise ValueError("Hanya draft yang bisa disubmit")
    req.status = "submitted"
    db.flush()
    return req


def approve_l1(
    *, db: Session, tenant_id, request_id, approver_user,
    approver_employment_id, is_manager: bool,
) -> OvertimeRequest:
    req = _get_request(db, tenant_id, request_id)
    if req.status != "submitted":
        raise ValueError("Hanya pengajuan 'submitted' yang bisa di-approve L1")
    if (approver_employment_id is not None
            and str(approver_employment_id) == str(req.employment_id)):
        raise ValueError("Tidak bisa menyetujui pengajuan sendiri")
    if not (is_manager or approver_user.is_superadmin):
        raise ValueError("Approval L1 hanya oleh atasan langsung")
    req.status = "approved_l1"
    req.l1_approved_by_user_id = approver_user.id
    req.l1_approved_at = datetime.now()
    db.flush()
    return req


def approve_l2(
    *, db: Session, tenant_id, request_id, approver_user,
    approver_employment_id, can_approve: bool,
) -> OvertimeRequest:
    """Approval final: hitung upah lembur dan kunci nilainya di pay_amount."""
    req = _get_request(db, tenant_id, request_id)
    if req.status != "approved_l1":
        raise ValueError("Hanya pengajuan 'approved_l1' yang bisa di-approve final")
    if (approver_employment_id is not None
            and str(approver_employment_id) == str(req.employment_id)):
        raise ValueError("Tidak bisa menyetujui pengajuan sendiri")
    if not (can_approve or approver_user.is_superadmin):
        raise ValueError("Approval final hanya oleh HR")
    req.pay_amount = compute_pay(
        db, tenant_id, req.employment_id, req.date, float(req.hours)
    )
    req.status = "approved"
    req.l2_approved_by_user_id = approver_user.id
    req.l2_approved_at = datetime.now()
    db.flush()
    return req


def reject_request(
    *, db: Session, tenant_id, request_id, approver_user, reason: str,
) -> OvertimeRequest:
    if not reason or not reason.strip():
        raise ValueError("Alasan penolakan wajib diisi")
    req = _get_request(db, tenant_id, request_id)
    if req.status not in ("submitted", "approved_l1"):
        raise ValueError("Hanya pengajuan aktif yang bisa ditolak")
    req.status = "rejected"
    req.rejection_reason = reason.strip()
    db.flush()
    return req


def approved_for_period(
    db: Session, tenant_id, start: date, end: date
) -> dict[str, dict]:
    """{employment_id_str: {"hours": float, "pay": int}} lembur approved
    dalam rentang — dipakai payroll run (integrasi ATT-010)."""
    rows = (
        db.execute(
            select(OvertimeRequest).where(
                OvertimeRequest.tenant_id == tenant_id,
                OvertimeRequest.status == "approved",
                OvertimeRequest.date >= start, OvertimeRequest.date <= end,
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, dict] = {}
    for r in rows:
        key = str(r.employment_id)
        slot = out.setdefault(key, {"hours": 0.0, "pay": 0})
        slot["hours"] = round(slot["hours"] + float(r.hours), 2)
        slot["pay"] += r.pay_amount
    return out
