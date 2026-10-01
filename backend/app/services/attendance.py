"""Absensi: shift, check-in/out, koreksi berversi, rekap (PRD Bagian 10).

Penyederhanaan jujur vs PRD (dirinci ADR-0008):
- Tanpa geofence/GPS, face matching, deteksi fake GPS, mode offline
  (kolom `source` disiapkan untuk itu, implementasi = pekerjaan lanjutan).
- Waktu dianggap sudah dalam zona waktu lokasi kerja (PRD TIM-016 penuh
  butuh pemetaan lokasi -> tz per record; disederhanakan).
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    MAX_DATE,
    AttendanceRecord,
    Employment,
    Holiday,
    LeaveRequest,
    Shift,
    ShiftAssignment,
    TenantAttendancePolicy,
)

SHIFT_SEED: list[tuple] = [
    # (code, name, start, end, is_overnight)
    ("pagi", "Pagi", time(8, 0), time(17, 0), False),
    ("siang", "Siang", time(13, 0), time(22, 0), False),
    ("malam", "Malam", time(22, 0), time(7, 0), True),
]

_DUMMY_DATE = date(2000, 1, 1)


def _to_dt(t: time) -> datetime:
    return datetime.combine(_DUMMY_DATE, t)


def seed_shifts(db: Session, tenant_id) -> None:
    """Seed 3 shift standar. Idempoten."""
    for code, name, start, end, overnight in SHIFT_SEED:
        exists = (
            db.execute(
                select(Shift.id).where(
                    Shift.tenant_id == tenant_id, Shift.code == code
                )
            ).first()
        )
        if not exists:
            db.add(
                Shift(
                    tenant_id=tenant_id, code=code, name=name,
                    start_time=_to_dt(start), end_time=_to_dt(end),
                    is_overnight=overnight,
                )
            )
    db.flush()


def get_attendance_policy(db: Session, tenant_id) -> TenantAttendancePolicy:
    policy = (
        db.execute(
            select(TenantAttendancePolicy).where(
                TenantAttendancePolicy.tenant_id == tenant_id
            )
        )
        .scalars()
        .first()
    )
    if policy is None:
        policy = TenantAttendancePolicy(tenant_id=tenant_id)
        db.add(policy)
        db.flush()
    return policy


def _employment_or_404(db: Session, tenant_id, employment_id) -> Employment:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != tenant_id:
        raise KeyError("Employment tidak ditemukan")
    return emp


def assign_shift(
    *, db: Session, tenant_id, employment_id, shift_id,
    valid_from: date, valid_to: date | None = None,
) -> ShiftAssignment:
    """Tugaskan shift; tolak bila rentang tumpang tindih dengan penugasan lain."""
    _employment_or_404(db, tenant_id, employment_id)
    shift = db.get(Shift, shift_id)
    if shift is None or shift.tenant_id != tenant_id or not shift.is_active:
        raise KeyError("Shift tidak ditemukan")
    valid_to = valid_to or MAX_DATE
    if valid_to < valid_from:
        raise ValueError("valid_to tidak boleh sebelum valid_from")
    overlap = (
        db.execute(
            select(ShiftAssignment.id).where(
                ShiftAssignment.tenant_id == tenant_id,
                ShiftAssignment.employment_id == employment_id,
                ShiftAssignment.valid_from <= valid_to,
                ShiftAssignment.valid_to >= valid_from,
            )
        ).first()
    )
    if overlap:
        raise ValueError("Rentang shift tumpang tindih dengan penugasan lain")
    assignment = ShiftAssignment(
        tenant_id=tenant_id, employment_id=employment_id, shift_id=shift_id,
        valid_from=valid_from, valid_to=valid_to,
    )
    db.add(assignment)
    db.flush()
    return assignment


def get_shift_for(
    db: Session, tenant_id, employment_id, day: date
) -> tuple[Shift, datetime, datetime] | tuple[None, None, None]:
    """Kembalikan (shift, start_dt, end_dt) yang berlaku pada tanggal."""
    assignment = (
        db.execute(
            select(ShiftAssignment)
            .where(
                ShiftAssignment.tenant_id == tenant_id,
                ShiftAssignment.employment_id == employment_id,
                ShiftAssignment.valid_from <= day,
                ShiftAssignment.valid_to >= day,
            )
            .order_by(ShiftAssignment.valid_from.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if assignment is None:
        return None, None, None
    shift = db.get(Shift, assignment.shift_id)
    if shift is None:
        return None, None, None
    start_dt = datetime.combine(day, shift.start_time.time())
    if shift.is_overnight:
        end_dt = datetime.combine(day + timedelta(days=1), shift.end_time.time())
    else:
        end_dt = datetime.combine(day, shift.end_time.time())
    return shift, start_dt, end_dt


def _naive(at: datetime) -> datetime:
    """Samakan ke waktu lokal-naif (penyederhanaan zona waktu, ADR-0008)."""
    if at.tzinfo is not None:
        at = at.replace(tzinfo=None)
    return at


def _naive_or_none(at: datetime | None) -> datetime | None:
    """Varian `_naive` yang aman untuk nilai None."""
    return _naive(at) if at is not None else None


def _current_record(
    db: Session, tenant_id, employment_id, day: date
) -> AttendanceRecord | None:
    return (
        db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employment_id == employment_id,
                AttendanceRecord.date == day,
                AttendanceRecord.is_current.is_(True),
            )
        )
        .scalars()
        .first()
    )


def check_in(
    *, db: Session, tenant_id, employment_id, at: datetime | None = None,
    source: str = "web", created_by=None,
) -> AttendanceRecord:
    """Clock-in; deteksi telat vs shift+grace. Satu check-in per hari."""
    _employment_or_404(db, tenant_id, employment_id)
    at = _naive(at or datetime.now())
    day = at.date()
    if _current_record(db, tenant_id, employment_id, day) is not None:
        raise ValueError("Sudah check-in pada tanggal ini")
    shift, start_dt, _end_dt = get_shift_for(db, tenant_id, employment_id, day)
    grace = get_attendance_policy(db, tenant_id).grace_minutes
    if shift is not None:
        grace = shift.grace_minutes
    late_minutes = 0
    status = "present"
    if shift is not None:
        deadline = start_dt + timedelta(minutes=grace)
        if at > deadline:
            late_minutes = int((at - deadline).total_seconds() // 60)
            status = "late"
    record = AttendanceRecord(
        tenant_id=tenant_id, employment_id=employment_id, date=day,
        check_in=at, source=source, status=status,
        late_minutes=late_minutes, created_by_user_id=created_by,
    )
    db.add(record)
    db.flush()
    return record


def check_out(
    *, db: Session, tenant_id, employment_id, at: datetime | None = None,
    created_by=None,
) -> AttendanceRecord:
    """Clock-out; deteksi pulang cepat vs shift."""
    _employment_or_404(db, tenant_id, employment_id)
    at = _naive(at or datetime.now())
    day = at.date()
    record = _current_record(db, tenant_id, employment_id, day)
    if record is None or record.check_in is None:
        # Shift malam: check-out dini hari tercatat di tanggal check-in.
        prev = _current_record(db, tenant_id, employment_id, day - timedelta(days=1))
        if prev is not None and prev.check_in is not None and prev.check_out is None:
            record, day = prev, prev.date
        else:
            raise ValueError("Belum check-in; tidak bisa check-out")
    if record.check_out is not None:
        raise ValueError("Sudah check-out pada tanggal ini")
    if at < _naive(record.check_in):
        raise ValueError("Waktu check-out tidak boleh sebelum check-in")
    record.check_out = at
    _shift, _start_dt, end_dt = get_shift_for(db, tenant_id, employment_id, day)
    if end_dt is not None and at < end_dt:
        record.early_leave_minutes = int((end_dt - at).total_seconds() // 60)
    record.work_minutes = int((at - _naive(record.check_in)).total_seconds() // 60)
    db.flush()
    return record


def correct_record(
    *, db: Session, tenant_id, record_id, check_in: datetime | None = None,
    check_out: datetime | None = None, reason: str, created_by=None,
) -> AttendanceRecord:
    """Koreksi absensi (TIM-021): alasan WAJIB; versi baru, data asli tetap ada."""
    if not reason or not reason.strip():
        raise ValueError("Alasan koreksi wajib diisi")
    old = db.get(AttendanceRecord, record_id)
    if old is None or old.tenant_id != tenant_id:
        raise KeyError("Record absensi tidak ditemukan")
    if not old.is_current:
        raise ValueError("Hanya versi terkini yang bisa dikoreksi")
    # Di Postgres, `old.check_in`/`old.check_out` terbaca sebagai datetime
    # aware (kolom timestamptz), sedangkan jam shift adalah naive (waktu
    # lokal). Samakan ke naive agar perbandingan tidak TypeError (500)
    # saat koreksi hanya mengubah salah satunya.
    new_check_in = _naive(check_in) if check_in else _naive_or_none(old.check_in)
    new_check_out = _naive(check_out) if check_out else _naive_or_none(old.check_out)
    # Hitung ulang keterlambatan/pulang-cepat dari jam yang dikoreksi
    # memakai shift yang berlaku pada tanggal record.
    shift, start_dt, end_dt = get_shift_for(
        db, tenant_id, old.employment_id, old.date)
    grace = get_attendance_policy(db, tenant_id).grace_minutes
    if shift is not None:
        grace = shift.grace_minutes
    status, late_minutes = old.status, old.late_minutes
    if new_check_in is not None and start_dt is not None:
        deadline = start_dt + timedelta(minutes=grace)
        late_minutes = (
            int((new_check_in - deadline).total_seconds() // 60)
            if new_check_in > deadline else 0
        )
        status = "late" if late_minutes > 0 else "present"
    early_leave_minutes = old.early_leave_minutes
    if new_check_out is not None and end_dt is not None:
        early_leave_minutes = (
            int((end_dt - new_check_out).total_seconds() // 60)
            if new_check_out < end_dt else 0
        )
    new = AttendanceRecord(
        tenant_id=tenant_id, employment_id=old.employment_id, date=old.date,
        version=old.version + 1, check_in=new_check_in, check_out=new_check_out,
        source=old.source, status=status,
        late_minutes=late_minutes,
        early_leave_minutes=early_leave_minutes,
        work_minutes=old.work_minutes,
        correction_reason=reason.strip(), created_by_user_id=created_by,
    )
    if new_check_in and new_check_out:
        new.work_minutes = int(
            (new_check_out - new_check_in).total_seconds() // 60
        )
    old.is_current = False
    db.add(new)
    db.flush()
    return new


def holidays_in_range(
    db: Session, tenant_id, start: date, end: date
) -> dict[date, Holiday]:
    rows = (
        db.execute(
            select(Holiday).where(
                Holiday.tenant_id == tenant_id,
                Holiday.date >= start, Holiday.date <= end,
            )
        )
        .scalars()
        .all()
    )
    return {h.date: h for h in rows}


def approved_leave_days(
    db: Session, tenant_id, employment_id, start: date, end: date
) -> set[date]:
    """Tanggal cuti yang sudah approved final dalam rentang."""
    reqs = (
        db.execute(
            select(LeaveRequest).where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.employment_id == employment_id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= end,
                LeaveRequest.end_date >= start,
            )
        )
        .scalars()
        .all()
    )
    days: set[date] = set()
    for r in reqs:
        d = max(r.start_date, start)
        last = min(r.end_date, end)
        while d <= last:
            days.add(d)
            d += timedelta(days=1)
    return days


def month_summary(
    db: Session, tenant_id, employment_id, period: str
) -> dict:
    """Rekap absensi satu employment untuk periode 'YYYY-MM'."""
    try:
        y, m = int(period[0:4]), int(period[5:7])
        assert len(period) == 7 and period[4] == "-" and 1 <= m <= 12
    except (ValueError, AssertionError):
        raise ValueError("period harus format 'YYYY-MM'")
    _employment_or_404(db, tenant_id, employment_id)
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    holidays = holidays_in_range(db, tenant_id, start, end)
    leave_days = approved_leave_days(db, tenant_id, employment_id, start, end)
    records = {
        r.date: r
        for r in db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employment_id == employment_id,
                AttendanceRecord.date >= start, AttendanceRecord.date <= end,
                AttendanceRecord.is_current.is_(True),
            )
        )
        .scalars()
        .all()
    }
    counts = {"present": 0, "late": 0, "absent": 0, "leave": 0, "holiday": 0}
    total_work_minutes = 0
    total_late_minutes = 0
    d = start
    while d <= end:
        if d in holidays:
            counts["holiday"] += 1
        elif d in leave_days:
            counts["leave"] += 1
        elif d in records:
            r = records[d]
            counts[r.status if r.status in counts else "present"] += 1
            total_work_minutes += r.work_minutes
            total_late_minutes += r.late_minutes
        elif d.weekday() < 5:
            counts["absent"] += 1
        d += timedelta(days=1)
    return {
        "period": period,
        "employment_id": str(employment_id),
        **counts,
        "total_work_minutes": total_work_minutes,
        "total_late_minutes": total_late_minutes,
    }


def present_and_absent_days(
    db: Session, tenant_id, employment_id, start: date, end: date
) -> tuple[int, int]:
    """(hari_hadir, hari_mangkir) untuk integrasi payroll.

    hari_hadir = record current berstatus present/late.
    hari_mangkir = hari kerja (Senin-Jumat) tanpa record, cuti, atau libur.
    """
    summary_days = month_summary_day_detail(db, tenant_id, employment_id, start, end)
    present = sum(1 for s in summary_days.values() if s in ("present", "late"))
    absent = sum(1 for s in summary_days.values() if s == "absent")
    return present, absent


def month_summary_day_detail(
    db: Session, tenant_id, employment_id, start: date, end: date
) -> dict[date, str]:
    holidays = holidays_in_range(db, tenant_id, start, end)
    leave_days = approved_leave_days(db, tenant_id, employment_id, start, end)
    records = {
        r.date: r.status
        for r in db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employment_id == employment_id,
                AttendanceRecord.date >= start, AttendanceRecord.date <= end,
                AttendanceRecord.is_current.is_(True),
            )
        )
        .scalars()
        .all()
    }
    out: dict[date, str] = {}
    d = start
    while d <= end:
        if d in holidays:
            out[d] = "holiday"
        elif d in leave_days:
            out[d] = "leave"
        elif d in records:
            out[d] = records[d]
        elif d.weekday() < 5:
            out[d] = "absent"
        else:
            out[d] = "weekend"
        d += timedelta(days=1)
    return out


def has_any_record(
    db: Session, tenant_id, employment_id, start: date, end: date
) -> bool:
    return (
        db.execute(
            select(func.count()).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employment_id == employment_id,
                AttendanceRecord.date >= start, AttendanceRecord.date <= end,
                AttendanceRecord.is_current.is_(True),
            )
        ).scalar()
        or 0
    ) > 0
