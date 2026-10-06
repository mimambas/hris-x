"""Dasbor tim untuk atasan langsung (EXP-011, PRD 13.2).

Satu endpoint agregat: status tim hari ini (hadir, telat, cuti,
tidak hadir, belum absen), lembur berjalan hari ini, cuti yang
sedang berjalan & 7 hari ke depan, dan jumlah persetujuan yang
menunggu atasan. Tim = employment aktif yang JobInfo berlakunya
menunjuk pemanggil sebagai manager_employment_id (org chart hari
ini, sejalan dengan services.leave.is_manager_of).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import (
    AttendanceRecord,
    Employment,
    JobInfo,
    LeaveRequest,
    LeaveType,
    OvertimeRequest,
    Person,
    User,
)
from app.schemas.schemas import (
    TeamDashboardOut,
    TeamLeaveItemOut,
    TeamMemberStatusOut,
)
from app.services import effective_dating as ed
from app.services import population as population_service

router = APIRouter(tags=["team"])


def _team_members(db: Session, user: User, own_id) -> list[Employment]:
    rows = db.execute(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.status == "active",
            Employment.id != own_id)
    ).scalars().all()
    team: list[Employment] = []
    for emp in rows:
        job = ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                       identity_field="employment_id",
                       identity_value=emp.id, as_of_date=date.today())
        if job is not None and job.manager_employment_id is not None \
                and str(job.manager_employment_id) == str(own_id):
            team.append(emp)
    return team


@router.get("/team/dashboard", response_model=TeamDashboardOut)
def team_dashboard(user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    own = population_service.get_user_employment(db, user)
    if own is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Dasbor tim hanya untuk pengguna yang terikat employment")
    team = _team_members(db, user, own.id)
    if not team:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Anda belum memiliki anggota tim langsung. Dasbor tim "
            "tersedia untuk atasan dengan bawahan langsung.")
    today = date.today()
    team_ids = [e.id for e in team]
    names = {}
    for emp in team:
        person = db.get(Person, emp.person_id)
        names[emp.id] = person.full_name if person else "(tanpa nama)"

    # Cuti disetujui yang mencakup hari ini & 7 hari ke depan.
    leave_rows = db.execute(
        select(LeaveRequest).where(
            LeaveRequest.tenant_id == user.tenant_id,
            LeaveRequest.employment_id.in_(team_ids),
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= today,
            LeaveRequest.start_date <= today + timedelta(days=7))
    ).scalars().all() if team_ids else []
    type_names = {t.id: t.name for t in db.execute(
        select(LeaveType).where(LeaveType.tenant_id == user.tenant_id)
    ).scalars().all()}

    leave_by_emp: dict = {}
    on_leave_today: list[TeamLeaveItemOut] = []
    upcoming: list[TeamLeaveItemOut] = []
    for lr in leave_rows:
        item = TeamLeaveItemOut(
            employment_id=lr.employment_id,
            person_name=names.get(lr.employment_id, ""),
            leave_type_name=type_names.get(lr.leave_type_id, "Cuti"),
            start_date=lr.start_date, end_date=lr.end_date)
        if lr.start_date <= today <= lr.end_date:
            leave_by_emp[lr.employment_id] = item
            on_leave_today.append(item)
        elif lr.start_date > today:
            upcoming.append(item)
    upcoming.sort(key=lambda i: i.start_date)

    # Absensi hari ini (record versi berlaku).
    attendance = {}
    if team_ids:
        for rec in db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == user.tenant_id,
                AttendanceRecord.employment_id.in_(team_ids),
                AttendanceRecord.date == today,
                AttendanceRecord.is_current.is_(True))
        ).scalars().all():
            attendance[rec.employment_id] = rec

    # Lembur disetujui hari ini + persetujuan menunggu atasan.
    overtime_today = {}
    if team_ids:
        for ov in db.execute(
            select(OvertimeRequest).where(
                OvertimeRequest.tenant_id == user.tenant_id,
                OvertimeRequest.employment_id.in_(team_ids),
                OvertimeRequest.date == today,
                OvertimeRequest.status == "approved")
        ).scalars().all():
            overtime_today[ov.employment_id] = \
                overtime_today.get(ov.employment_id, 0.0) + float(ov.hours)
    pending = 0
    if team_ids:
        for model in (LeaveRequest, OvertimeRequest):
            pending += len(db.execute(
                select(model).where(
                    model.tenant_id == user.tenant_id,
                    model.employment_id.in_(team_ids),
                    model.status == "submitted")
            ).scalars().all())

    members: list[TeamMemberStatusOut] = []
    counts = {"hadir": 0, "telat": 0, "cuti": 0, "tidak_hadir": 0,
              "belum_absen": 0}
    for emp in team:
        rec = attendance.get(emp.id)
        leave = leave_by_emp.get(emp.id)
        if leave is not None:
            st = "cuti"
        elif rec is not None:
            if rec.status == "present":
                st = "telat" if (rec.late_minutes or 0) > 0 else "hadir"
            elif rec.status == "absent":
                st = "tidak_hadir"
            else:
                st = rec.status
                counts.setdefault(st, 0)
        else:
            st = "belum_absen"
        counts[st] = counts.get(st, 0) + 1
        members.append(TeamMemberStatusOut(
            employment_id=emp.id, person_name=names[emp.id], status=st,
            check_in=rec.check_in if rec is not None else None,
            late_minutes=rec.late_minutes if rec is not None else 0,
            leave_type_name=leave.leave_type_name if leave else None,
            overtime_hours_today=overtime_today.get(emp.id, 0.0)))
    members.sort(key=lambda m: m.person_name)

    return TeamDashboardOut(
        date=today, team_size=len(team),
        present=counts.get("hadir", 0), late=counts.get("telat", 0),
        on_leave=counts.get("cuti", 0), absent=counts.get("tidak_hadir", 0),
        not_checked_in=counts.get("belum_absen", 0),
        overtime_today_count=len(overtime_today),
        overtime_hours_today=round(sum(overtime_today.values()), 2),
        pending_approvals=pending, members=members,
        on_leave_today=on_leave_today, upcoming_leave=upcoming)
