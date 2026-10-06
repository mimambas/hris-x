"""Dasbor tim atasan langsung (EXP-011, PRD 13.2).

Tim diturunkan dari org chart hari ini (JobInfo.manager_employment_id).
Endpoint agregat menampilkan status anggota hari ini, lembur
berjalan, cuti berjalan & mendatang, dan persetujuan menunggu.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.models import (
    AttendanceRecord,
    JobInfo,
    LeaveRequest,
    LeaveType,
    OvertimeRequest,
)

from .conftest import login_headers

TODAY = date.today()


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def _make_staff_report_to_mgr(ctx):
    db = ctx["db"]
    info = db.execute(
        select(JobInfo).where(
            JobInfo.employment_id == ctx["e_staff"].id)).scalars().first()
    assert info is not None
    info.manager_employment_id = ctx["e_mgr"].id
    db.commit()


def _attendance(ctx, status="present", late=0):
    db = ctx["db"]
    db.add(AttendanceRecord(
        tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
        date=TODAY, version=1, is_current=True,
        check_in=datetime.combine(TODAY, time(8, late and 20 or 0),
                                  tzinfo=timezone.utc),
        source="web", status=status, late_minutes=late))
    db.commit()


def test_dashboard_present_overtime_and_pending(client, ctx):
    _make_staff_report_to_mgr(ctx)
    _attendance(ctx)
    db = ctx["db"]
    db.add(OvertimeRequest(
        tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
        date=TODAY,
        start_time=datetime.combine(TODAY, time(17)),
        end_time=datetime.combine(TODAY, time(19)),
        hours=2, reason="Deploy", status="approved"))
    lt = LeaveType(tenant_id=ctx["ta"].id, code="CT", name="Cuti Tahunan")
    db.add(lt)
    db.flush()
    db.add(LeaveRequest(
        tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
        leave_type_id=lt.id, start_date=TODAY + timedelta(days=10),
        end_date=TODAY + timedelta(days=11), days=2, reason="Libur",
        status="submitted"))
    db.commit()

    r = client.get("/api/v1/team/dashboard", headers=mh(client))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["team_size"] == 1, d
    assert d["present"] == 1 and d["late"] == 0, d
    assert d["overtime_today_count"] == 1
    assert d["overtime_hours_today"] == 2
    assert d["pending_approvals"] == 1, d
    member = d["members"][0]
    assert member["status"] == "hadir"
    assert member["overtime_hours_today"] == 2


def test_dashboard_member_on_leave_today(client, ctx):
    _make_staff_report_to_mgr(ctx)
    db = ctx["db"]
    lt = LeaveType(tenant_id=ctx["ta"].id, code="CT2", name="Cuti Tahunan")
    db.add(lt)
    db.flush()
    db.add(LeaveRequest(
        tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
        leave_type_id=lt.id, start_date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=1), days=3, reason="Mudik",
        status="approved"))
    db.commit()

    r = client.get("/api/v1/team/dashboard", headers=mh(client))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["on_leave"] == 1, d
    assert d["members"][0]["status"] == "cuti"
    assert d["members"][0]["leave_type_name"] == "Cuti Tahunan"
    assert len(d["on_leave_today"]) == 1


def test_dashboard_forbidden_without_team(client, ctx):
    r = client.get("/api/v1/team/dashboard", headers=sh(client))
    assert r.status_code == 403, r.text
