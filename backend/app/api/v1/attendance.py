"""Absensi & shift: check-in/out, koreksi berversi, rekap, kalender libur
(PRD Bagian 10, TIM/LEV). Tanpa geofence di sprint ini (ADR-0008)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, resolve_employment, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    MAX_DATE,
    AttendanceRecord,
    Employment,
    Holiday,
    Shift,
    ShiftAssignment,
    User,
)
from app.schemas.schemas import (
    AttendanceCorrectRequest,
    AttendanceRecordOut,
    AttendancePolicyOut,
    AttendancePolicyUpdate,
    CheckInOutRequest,
    HolidayCreate,
    HolidayOut,
    ShiftAssignOut,
    ShiftAssignRequest,
    ShiftCreate,
    ShiftOut,
)
from app.services import attendance as att
from app.services import leave as leave_service
from app.services.audit import write_audit

router = APIRouter(tags=["attendance"])

_SHIFT_FIELDS = ["id", "code", "name", "is_overnight", "grace_minutes",
                 "is_active"]


def _parse_hhmm(value: str) -> datetime:
    try:
        h, m = value.split(":")
        return datetime(2000, 1, 1, int(h), int(m))
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Format jam harus 'HH:MM'")


# ------------------------------------------------------------------ Shift
@router.post("/shifts",
             dependencies=[Depends(require_permission("shift", "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_shift(
    body: ShiftCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    start_dt, end_dt = _parse_hhmm(body.start_time), _parse_hhmm(body.end_time)
    if start_dt.time() == end_dt.time():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Jam mulai dan selesai tidak boleh sama")
    exists = db.execute(
        select(Shift.id).where(Shift.tenant_id == user.tenant_id,
                               Shift.code == body.code.strip())
    ).first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Kode shift '{body.code}' sudah dipakai")
    shift = Shift(
        tenant_id=user.tenant_id, code=body.code.strip(), name=body.name.strip(),
        start_time=start_dt, end_time=end_dt,
        is_overnight=body.is_overnight, grace_minutes=body.grace_minutes,
    )
    db.add(shift)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="shift", object_id=shift.id,
                new_values=snapshot(shift, _SHIFT_FIELDS),
                reason="Shift baru", channel="api", ip=client_ip(request))
    db.commit()
    return ShiftOut.model_validate(shift)


@router.get("/shifts",
            dependencies=[Depends(require_permission("shift", "view"))])
def list_shifts(user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    rows = (db.execute(
        select(Shift).where(Shift.tenant_id == user.tenant_id,
                            Shift.is_active.is_(True))
        .order_by(Shift.code))
        .scalars().all())
    return [ShiftOut.model_validate(r) for r in rows]


@router.post("/shift-assignments",
             dependencies=[Depends(require_permission("shift", "insert"))],
             status_code=status.HTTP_201_CREATED)
def assign_shift(
    body: ShiftAssignRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, "shift", "insert")
    try:
        assignment = att.assign_shift(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            shift_id=body.shift_id, valid_from=body.valid_from,
            valid_to=body.valid_to,
        )
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="shift_assignment",
                object_id=assignment.id,
                new_values={"employment_id": str(emp.id),
                            "shift_id": str(body.shift_id),
                            "valid_from": body.valid_from.isoformat(),
                            "valid_to": assignment.valid_to.isoformat()},
                reason=body.reason, channel="api", ip=client_ip(request))
    db.commit()
    return ShiftAssignOut.model_validate(assignment)


# ------------------------------------------------------------------ Check-in/out
def _record_out(r: AttendanceRecord) -> AttendanceRecordOut:
    return AttendanceRecordOut.model_validate(r)


@router.post("/attendance/check-in",
             dependencies=[Depends(require_permission("attendance",
                                                       "insert"))],
             status_code=status.HTTP_201_CREATED)
def check_in(
    body: CheckInOutRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, "attendance",
                             "insert")
    try:
        record = att.check_in(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            at=body.at, source=body.source, created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="attendance_record",
                object_id=record.id,
                new_values={"employment_id": str(emp.id),
                            "date": record.date.isoformat(),
                            "check_in": record.check_in.isoformat()
                            if record.check_in else None,
                            "status": record.status,
                            "late_minutes": record.late_minutes,
                            "source": body.source},
                reason=body.reason or "Check-in",
                channel="mobile" if body.source == "mobile" else "api",
                ip=client_ip(request))
    db.commit()
    return _record_out(record)


@router.post("/attendance/check-out",
             dependencies=[Depends(require_permission("attendance",
                                                       "insert"))])
def check_out(
    body: CheckInOutRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    emp = resolve_employment(db, user, body.employment_id, "attendance",
                             "insert")
    try:
        record = att.check_out(
            db=db, tenant_id=user.tenant_id, employment_id=emp.id,
            at=body.at, created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="attendance_record",
                object_id=record.id,
                new_values={"check_out": record.check_out.isoformat()
                            if record.check_out else None,
                            "work_minutes": record.work_minutes,
                            "early_leave_minutes": record.early_leave_minutes},
                reason=body.reason or "Check-out",
                channel="mobile" if body.source == "mobile" else "api",
                ip=client_ip(request))
    db.commit()
    return _record_out(record)


@router.post("/attendance/{record_id}/correct",
             dependencies=[Depends(require_permission("attendance",
                                                       "correct"))])
def correct_attendance(
    record_id: uuid.UUID, body: AttendanceCorrectRequest, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    old = db.get(AttendanceRecord, record_id)
    if old is None or old.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Record absensi tidak ditemukan")
    resolve_employment(db, user, old.employment_id, "attendance", "correct")
    try:
        new = att.correct_record(
            db=db, tenant_id=user.tenant_id, record_id=record_id,
            check_in=body.check_in, check_out=body.check_out,
            reason=body.reason, created_by=user.id,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="correct", object_type="attendance_record",
                object_id=new.id,
                old_values={"version": old.version,
                            "check_in": old.check_in.isoformat()
                            if old.check_in else None,
                            "check_out": old.check_out.isoformat()
                            if old.check_out else None},
                new_values={"version": new.version,
                            "check_in": new.check_in.isoformat()
                            if new.check_in else None,
                            "check_out": new.check_out.isoformat()
                            if new.check_out else None},
                reason=body.reason, channel="attendance_correction",
                ip=client_ip(request))
    db.commit()
    return _record_out(new)


@router.get("/attendance/records",
            dependencies=[Depends(require_permission("attendance", "view"))])
def list_records(
    employment_id: uuid.UUID,
    date_from: date = Query(...), date_to: date = Query(...),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    resolve_employment(db, user, employment_id, "attendance", "view")
    rows = (db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == user.tenant_id,
            AttendanceRecord.employment_id == employment_id,
            AttendanceRecord.date >= date_from,
            AttendanceRecord.date <= date_to,
            AttendanceRecord.is_current.is_(True),
        ).order_by(AttendanceRecord.date))
        .scalars().all())
    return [_record_out(r) for r in rows]


@router.get("/attendance/summary",
            dependencies=[Depends(require_permission("attendance", "view"))])
def summary(
    employment_id: uuid.UUID, period: str = Query(..., min_length=7,
                                                  max_length=7),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    resolve_employment(db, user, employment_id, "attendance", "view")
    try:
        return att.month_summary(db, user.tenant_id, employment_id, period)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


# ------------------------------------------------------------------ Kalender libur
@router.post("/holidays",
             dependencies=[Depends(require_permission("holiday", "insert"))],
             status_code=status.HTTP_201_CREATED)
def create_holiday(
    body: HolidayCreate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    exists = db.execute(
        select(Holiday.id).where(Holiday.tenant_id == user.tenant_id,
                                 Holiday.date == body.date)
    ).first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tanggal tersebut sudah terdaftar sebagai libur")
    holiday = Holiday(
        tenant_id=user.tenant_id, date=body.date, name=body.name.strip(),
        is_cuti_bersama=body.is_cuti_bersama,
        deducts_leave=body.deducts_leave,
    )
    db.add(holiday)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="holiday", object_id=holiday.id,
                new_values={"date": body.date.isoformat(), "name": body.name,
                            "is_cuti_bersama": body.is_cuti_bersama},
                reason="Libur baru", channel="api", ip=client_ip(request))
    db.commit()
    return HolidayOut.model_validate(holiday)


@router.get("/holidays",
            dependencies=[Depends(require_permission("holiday", "view"))])
def list_holidays(
    year: int = Query(...), user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (db.execute(
        select(Holiday).where(
            Holiday.tenant_id == user.tenant_id,
            Holiday.date >= date(year, 1, 1),
            Holiday.date <= date(year, 12, 31),
        ).order_by(Holiday.date))
        .scalars().all())
    return [HolidayOut.model_validate(r) for r in rows]


@router.post("/holidays/{holiday_id}/apply-mass-leave",
             dependencies=[Depends(require_permission("holiday",
                                                       "correct"))])
def apply_mass_leave(
    holiday_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    holiday = db.get(Holiday, holiday_id)
    if holiday is None or holiday.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Libur tidak ditemukan")
    result = leave_service.apply_mass_leave(
        db=db, tenant_id=user.tenant_id, holiday=holiday,
        actor_user_id=user.id,
    )
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="holiday", object_id=holiday.id,
                new_values={"mass_leave_applied": result,
                            "date": holiday.date.isoformat()},
                reason=f"Terapkan cuti bersama {holiday.name}",
                channel="api", ip=client_ip(request))
    db.commit()
    return {"holiday": HolidayOut.model_validate(holiday), **result}


# ------------------------------------------------------------------ Kebijakan
@router.get("/attendance/policy",
            dependencies=[Depends(require_permission("attendance", "view"))])
def get_policy(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    return AttendancePolicyOut.model_validate(
        att.get_attendance_policy(db, user.tenant_id))


@router.put("/attendance/policy",
            dependencies=[Depends(require_permission("attendance",
                                                      "correct"))])
def update_policy(
    body: AttendancePolicyUpdate, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    policy = att.get_attendance_policy(db, user.tenant_id)
    old = {"grace_minutes": policy.grace_minutes,
           "deduct_absent": policy.deduct_absent}
    if body.grace_minutes is not None:
        policy.grace_minutes = body.grace_minutes
    if body.deduct_absent is not None:
        policy.deduct_absent = body.deduct_absent
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="tenant_attendance_policy",
                object_id=policy.id, old_values=old,
                new_values={"grace_minutes": policy.grace_minutes,
                            "deduct_absent": policy.deduct_absent},
                reason=body.reason, channel="api", ip=client_ip(request))
    db.commit()
    return AttendancePolicyOut.model_validate(policy)
