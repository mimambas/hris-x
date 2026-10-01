"""Dasbor & laporan agregat (Sprint 9, PRD ANL-001/ANL-003/ANL-004).

Semua angka dihitung dari data live (effective-dated, filter "per tanggal"),
tanpa cache — sesuai kriteria penerimaan ANL-001.

Definisi metrik baku (ANL-004):
- Turnover rate = karyawan keluar dalam periode / rata-rata headcount
  periode x 100% (rata-rata = (headcount awal + headcount akhir) / 2).
- "Keluar" = employment berstatus terminated dengan end_date di periode.
- "Aktif" = status active/probation, start_date <= tanggal,
  end_date kosong atau >= tanggal (konsisten dengan payroll & cuti);
  karyawan yang terminasi SETELAH tanggal tetap dihitung aktif per
  tanggal tersebut (headcount historis yang benar).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from io import BytesIO

from sqlalchemy import and_, extract, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRecord,
    Contract,
    ContractInfo,
    Employment,
    Job,
    JobInfo,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    OrgUnitInfo,
    PayrollLine,
    PayrollRun,
    Person,
)
from app.services import effective_dating as ed

ACTIVE_STATUSES = ("active", "probation")
TANPA_UNIT = "Tanpa unit"
TANPA_KONTRAK = "Tanpa kontrak"


# ---------------------------------------------------------------------------
# Fondasi
# ---------------------------------------------------------------------------
def parse_period(period: str) -> tuple[date, date]:
    """'YYYY-MM' -> (tanggal pertama, tanggal terakhir)."""
    year, month = (int(x) for x in period.split("-", 1))
    first = date(year, month, 1)
    return first, date(year, month, monthrange(year, month)[1])


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    m = month + delta
    y = year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return y, m


def _active_filter(as_of: date):
    """Karyawan dihitung aktif per tanggal: status active/probation, atau
    terminated tetapi end_date-nya masih di/lewat tanggal tersebut."""
    return and_(
        Employment.start_date <= as_of,
        or_(Employment.end_date.is_(None), Employment.end_date >= as_of),
        or_(
            Employment.status.in_(ACTIVE_STATUSES),
            and_(Employment.status == "terminated",
                 Employment.end_date >= as_of),
        ),
    )


def employments_active_as_of(
    db: Session, tenant_id, as_of: date, person_ids: set | None = None
) -> list[Employment]:
    stmt = select(Employment).where(
        Employment.tenant_id == tenant_id,
        _active_filter(as_of),
    )
    if person_ids is not None:
        stmt = stmt.where(Employment.person_id.in_(person_ids))
    return db.execute(stmt.order_by(Employment.start_date)).scalars().all()


def headcount_total(db: Session, tenant_id, as_of: date,
                    person_ids: set | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(Employment)
        .where(
            Employment.tenant_id == tenant_id,
            _active_filter(as_of),
        )
    )
    if person_ids is not None:
        stmt = stmt.where(Employment.person_id.in_(person_ids))
    return db.execute(stmt).scalar() or 0


def org_unit_name(db: Session, tenant_id, employment_id, as_of: date) -> str:
    job = ed.as_of(db=db, tenant_id=tenant_id, model=JobInfo,
                   identity_field="employment_id",
                   identity_value=employment_id, as_of_date=as_of)
    if job is None or job.org_unit_id is None:
        return TANPA_UNIT
    info = ed.as_of(db=db, tenant_id=tenant_id, model=OrgUnitInfo,
                    identity_field="org_unit_id",
                    identity_value=job.org_unit_id, as_of_date=as_of)
    return info.name if info is not None else TANPA_UNIT


def job_title(db: Session, tenant_id, employment_id, as_of: date) -> str:
    job = ed.as_of(db=db, tenant_id=tenant_id, model=JobInfo,
                   identity_field="employment_id",
                   identity_value=employment_id, as_of_date=as_of)
    if job is None or job.job_id is None:
        return "-"
    j = db.get(Job, job.job_id)
    return j.title if j is not None else "-"


def contract_type(db: Session, tenant_id, employment_id, as_of: date) -> str:
    contract = (
        db.execute(
            select(Contract)
            .where(Contract.tenant_id == tenant_id,
                   Contract.employment_id == employment_id)
            .order_by(Contract.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if contract is None:
        return TANPA_KONTRAK
    info = ed.as_of(db=db, tenant_id=tenant_id, model=ContractInfo,
                    identity_field="contract_id",
                    identity_value=contract.id, as_of_date=as_of)
    return info.contract_type if info is not None else TANPA_KONTRAK


def _person_map(db: Session, tenant_id, employments: list[Employment]
                ) -> dict:
    pids = {e.person_id for e in employments}
    if not pids:
        return {}
    persons = (
        db.execute(
            select(Person).where(Person.tenant_id == tenant_id,
                                 Person.id.in_(pids))
        )
        .scalars()
        .all()
    )
    return {p.id: p for p in persons}


# ---------------------------------------------------------------------------
# 1. Headcount
# ---------------------------------------------------------------------------
def headcount(db: Session, tenant_id, as_of: date,
              person_ids: set | None = None) -> dict:
    emps = employments_active_as_of(db, tenant_id, as_of, person_ids)
    persons = _person_map(db, tenant_id, emps)
    by_unit: dict[str, int] = {}
    by_contract: dict[str, int] = {}
    by_gender: dict[str, int] = {}
    by_status: dict[str, int] = {}
    new_this_month = 0
    for e in emps:
        unit = org_unit_name(db, tenant_id, e.id, as_of)
        by_unit[unit] = by_unit.get(unit, 0) + 1
        ct = contract_type(db, tenant_id, e.id, as_of)
        by_contract[ct] = by_contract.get(ct, 0) + 1
        p = persons.get(e.person_id)
        g = (p.gender if p is not None and p.gender else "Tidak diisi")
        by_gender[g] = by_gender.get(g, 0) + 1
        by_status[e.status] = by_status.get(e.status, 0) + 1
        if e.start_date.year == as_of.year and e.start_date.month == as_of.month:
            new_this_month += 1
    left = (
        db.execute(
            select(func.count())
            .select_from(Employment)
            .where(
                Employment.tenant_id == tenant_id,
                Employment.status == "terminated",
                # STAGING-FIX (2026-10-01): func.strftime hanya ada di
                # SQLite; extract() portabel SQLite <-> Postgres.
                extract("year", Employment.end_date) == as_of.year,
                extract("month", Employment.end_date) == as_of.month,
            )
        ).scalar()
        or 0
    )
    if person_ids is not None:
        left = (
            db.execute(
                select(func.count())
                .select_from(Employment)
                .where(
                    Employment.tenant_id == tenant_id,
                    Employment.status == "terminated",
                    Employment.person_id.in_(person_ids),
                    extract("year", Employment.end_date) == as_of.year,
                    extract("month", Employment.end_date) == as_of.month,
                )
            ).scalar()
            or 0
        )
    return {
        "as_of": as_of.isoformat(),
        "total": len(emps),
        "by_org_unit": by_unit,
        "by_contract_type": by_contract,
        "by_gender": by_gender,
        "by_status": by_status,
        "new_this_month": new_this_month,
        "left_this_month": left,
    }


# ---------------------------------------------------------------------------
# 2. Turnover (ANL-004)
# ---------------------------------------------------------------------------
def _terminated_in(db: Session, tenant_id, first: date, last: date,
                   person_ids: set | None = None) -> list[Employment]:
    stmt = select(Employment).where(
        Employment.tenant_id == tenant_id,
        Employment.status == "terminated",
        Employment.end_date.is_not(None),
        Employment.end_date >= first,
        Employment.end_date <= last,
    )
    if person_ids is not None:
        stmt = stmt.where(Employment.person_id.in_(person_ids))
    return db.execute(stmt).scalars().all()


def turnover_rate_for_month(db: Session, tenant_id, year: int, month: int,
                            person_ids: set | None = None) -> dict:
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    term = _terminated_in(db, tenant_id, first, last, person_ids)
    hc = (headcount_total(db, tenant_id, first, person_ids)
          + headcount_total(db, tenant_id, last, person_ids)) / 2
    rate = round(len(term) / hc * 100, 2) if hc else 0.0
    return {
        "period": f"{year:04d}-{month:02d}",
        "terminated": len(term),
        "avg_headcount": hc,
        "rate_pct": rate,
    }


def turnover(db: Session, tenant_id, period: str,
             person_ids: set | None = None) -> dict:
    year, month = (int(x) for x in period.split("-", 1))
    first, last = parse_period(period)
    term = _terminated_in(db, tenant_id, first, last, person_ids)
    hc_start = headcount_total(db, tenant_id, first, person_ids)
    hc_end = headcount_total(db, tenant_id, last, person_ids)
    avg = (hc_start + hc_end) / 2
    by_unit: dict[str, int] = {}
    for e in term:
        unit = org_unit_name(db, tenant_id, e.id, min(e.end_date, last))
        by_unit[unit] = by_unit.get(unit, 0) + 1
    trend = []
    for i in range(11, -1, -1):
        y, m = shift_month(year, month, -i)
        trend.append(turnover_rate_for_month(db, tenant_id, y, m, person_ids))
    return {
        "period": period,
        "terminated": len(term),
        "headcount_start": hc_start,
        "headcount_end": hc_end,
        "avg_headcount": avg,
        "rate_pct": round(len(term) / avg * 100, 2) if avg else 0.0,
        "by_org_unit": by_unit,
        "trend_12_months": trend,
    }


# ---------------------------------------------------------------------------
# 3a. Absensi
# ---------------------------------------------------------------------------
def attendance_dashboard(db: Session, tenant_id, period: str,
                         person_ids: set | None = None) -> dict:
    first, last = parse_period(period)
    emp_stmt = select(Employment.id).where(
        Employment.tenant_id == tenant_id,
        _active_filter(last),
    )
    if person_ids is not None:
        emp_stmt = emp_stmt.where(Employment.person_id.in_(person_ids))
    emp_ids = set(db.execute(emp_stmt).scalars().all())
    recs = (
        db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.is_current.is_(True),
                AttendanceRecord.date >= first,
                AttendanceRecord.date <= last,
                AttendanceRecord.employment_id.in_(emp_ids) if emp_ids else False,
            )
        )
        .scalars()
        .all()
    )
    check_ins = sum(1 for r in recs if r.check_in is not None)
    late = sum(1 for r in recs if r.late_minutes and r.late_minutes > 0)
    absent_days = sum(1 for r in recs if r.status == "absent")
    employees_with_records = len({r.employment_id for r in recs})
    total_work_minutes = sum(r.work_minutes or 0 for r in recs)
    by_unit: dict[str, dict] = {}
    for r in recs:
        unit = org_unit_name(db, tenant_id, r.employment_id, last)
        b = by_unit.setdefault(unit, {"check_ins": 0, "late": 0,
                                      "absent_days": 0, "employees": set()})
        b["employees"].add(str(r.employment_id))
        if r.check_in is not None:
            b["check_ins"] += 1
        if r.late_minutes and r.late_minutes > 0:
            b["late"] += 1
        if r.status == "absent":
            b["absent_days"] += 1
    by_unit_out = {}
    for unit, b in by_unit.items():
        by_unit_out[unit] = {
            "employees": len(b["employees"]),
            "check_ins": b["check_ins"],
            "late": b["late"],
            "late_pct": round(b["late"] / b["check_ins"] * 100, 2)
            if b["check_ins"] else 0.0,
            "absent_days": b["absent_days"],
        }
    return {
        "period": period,
        "employees": len(emp_ids),
        "employees_with_records": employees_with_records,
        "check_ins": check_ins,
        "late_count": late,
        "late_pct": round(late / check_ins * 100, 2) if check_ins else 0.0,
        "absent_days": absent_days,
        "avg_work_hours": round(total_work_minutes / 60 / employees_with_records, 2)
        if employees_with_records else 0.0,
        "by_org_unit": by_unit_out,
        "note": ("Persentase dihitung dari record absensi yang tercatat, "
                 "bukan dari hari kerja terjadwal."),
    }


# ---------------------------------------------------------------------------
# 3b. Cuti
# ---------------------------------------------------------------------------
def leave_dashboard(db: Session, tenant_id, year: int,
                    person_ids: set | None = None) -> dict:
    jan1 = date(year, 1, 1)
    dec31 = date(year, 12, 31)
    stmt = select(LeaveRequest).where(
        LeaveRequest.tenant_id == tenant_id,
        LeaveRequest.status == "approved",
        LeaveRequest.start_date <= dec31,
        LeaveRequest.end_date >= jan1,
    )
    if person_ids is not None:
        stmt = stmt.join(
            Employment, Employment.id == LeaveRequest.employment_id
        ).where(Employment.person_id.in_(person_ids))
    reqs = db.execute(stmt).scalars().all()
    total_days = sum(r.days or 0 for r in reqs)
    by_unit: dict[str, int] = {}
    for r in reqs:
        unit = org_unit_name(db, tenant_id, r.employment_id, r.start_date)
        by_unit[unit] = by_unit.get(unit, 0) + (r.days or 0)
    top_units = sorted(by_unit.items(), key=lambda kv: kv[1],
                       reverse=True)[:5]
    bal_stmt = (
        select(LeaveType.name, func.sum(LeaveBalance.entitled),
               func.sum(LeaveBalance.used), func.sum(LeaveBalance.remaining))
        .join(LeaveBalance, LeaveBalance.leave_type_id == LeaveType.id)
        .where(LeaveBalance.tenant_id == tenant_id,
               LeaveBalance.year == year)
        .group_by(LeaveType.name)
    )
    if person_ids is not None:
        bal_stmt = bal_stmt.join(
            Employment, Employment.id == LeaveBalance.employment_id
        ).where(Employment.person_id.in_(person_ids))
    balances = [
        {"leave_type": name, "entitled": int(ent or 0),
         "used": int(used or 0), "remaining": int(rem or 0)}
        for name, ent, used, rem in db.execute(bal_stmt).all()
    ]
    return {
        "year": year,
        "approved_requests": len(reqs),
        "total_leave_days": total_days,
        "top_units_by_leave_days": [
            {"org_unit": u, "days": d} for u, d in top_units
        ],
        "balances_by_type": balances,
    }


# ---------------------------------------------------------------------------
# 3c. Payroll
# ---------------------------------------------------------------------------
def payroll_dashboard(db: Session, tenant_id, period: str,
                      person_ids: set | None = None) -> dict | None:
    run = (
        db.execute(
            select(PayrollRun).where(PayrollRun.tenant_id == tenant_id,
                                    PayrollRun.period == period)
        )
        .scalars()
        .first()
    )
    if run is None:
        return None
    _, last = parse_period(period)
    line_stmt = select(PayrollLine).where(
        PayrollLine.tenant_id == tenant_id,
        PayrollLine.payroll_run_id == run.id,
    )
    if person_ids is not None:
        line_stmt = line_stmt.join(
            Employment, Employment.id == PayrollLine.employment_id
        ).where(Employment.person_id.in_(person_ids))
    lines = db.execute(line_stmt).scalars().all()
    totals = {"gross": 0, "deductions": 0, "pph21": 0, "reimbursement": 0,
              "overtime": 0, "take_home": 0, "lines": len(lines)}
    by_unit: dict[str, dict] = {}
    for ln in lines:
        unit = org_unit_name(db, tenant_id, ln.employment_id, last)
        b = by_unit.setdefault(unit, {"gross": 0, "pph21": 0,
                                      "take_home": 0, "lines": 0})
        overtime = 0
        if isinstance(ln.breakdown, dict):
            overtime = int(ln.breakdown.get("lembur", 0) or 0)
        totals["gross"] += ln.gross or 0
        totals["deductions"] += ln.total_deductions or 0
        totals["pph21"] += ln.pph21 or 0
        totals["reimbursement"] += ln.reimbursement_amount or 0
        totals["overtime"] += overtime
        totals["take_home"] += ln.take_home_pay or 0
        b["gross"] += ln.gross or 0
        b["pph21"] += ln.pph21 or 0
        b["take_home"] += ln.take_home_pay or 0
        b["lines"] += 1
    return {
        "period": period,
        "run_status": run.status,
        "totals": totals,
        "by_org_unit": by_unit,
    }


# ---------------------------------------------------------------------------
# 3d. Demografi
# ---------------------------------------------------------------------------
def _age_bucket(birth: date | None, as_of: date) -> str:
    if birth is None:
        return "Tidak diketahui"
    age = as_of.year - birth.year - (
        (as_of.month, as_of.day) < (birth.month, birth.day))
    if age < 20:
        return "<20"
    if age < 30:
        return "20-29"
    if age < 40:
        return "30-39"
    if age < 50:
        return "40-49"
    if age < 60:
        return "50-59"
    return "60+"


def _tenure_bucket(start: date, as_of: date) -> str:
    years = (as_of - start).days / 365.25
    if years < 1:
        return "<1 tahun"
    if years < 3:
        return "1-3 tahun"
    if years < 5:
        return "3-5 tahun"
    return ">5 tahun"


def demographics(db: Session, tenant_id, as_of: date,
                 person_ids: set | None = None) -> dict:
    emps = employments_active_as_of(db, tenant_id, as_of, person_ids)
    persons = _person_map(db, tenant_id, emps)
    by_age: dict[str, int] = {}
    by_tenure: dict[str, int] = {}
    by_gender: dict[str, int] = {}
    for e in emps:
        p = persons.get(e.person_id)
        by_age[_age_bucket(p.birth_date if p else None, as_of)] = \
            by_age.get(_age_bucket(p.birth_date if p else None, as_of), 0) + 1
        t = _tenure_bucket(e.start_date, as_of)
        by_tenure[t] = by_tenure.get(t, 0) + 1
        g = (p.gender if p is not None and p.gender else "Tidak diisi")
        by_gender[g] = by_gender.get(g, 0) + 1
    return {
        "as_of": as_of.isoformat(),
        "total": len(emps),
        "by_age": by_age,
        "by_tenure": by_tenure,
        "by_gender": by_gender,
    }


# ---------------------------------------------------------------------------
# 4. Laporan XLSX (openpyxl)
# ---------------------------------------------------------------------------
def build_employees_xlsx(db: Session, tenant_id, as_of: date,
                         person_ids: set | None = None) -> bytes:
    from openpyxl import Workbook

    emps = employments_active_as_of(db, tenant_id, as_of, person_ids)
    persons = _person_map(db, tenant_id, emps)
    wb = Workbook()
    ws = wb.active
    ws.title = "Karyawan"
    ws.append(["NIK", "Nama", "Unit", "Jabatan", "Tgl Masuk", "Status",
               "Kontrak", "Jenis Kelamin"])
    for e in emps:
        p = persons.get(e.person_id)
        ws.append([
            p.nik if p else "-",
            p.full_name if p else "-",
            org_unit_name(db, tenant_id, e.id, as_of),
            job_title(db, tenant_id, e.id, as_of),
            e.start_date.isoformat(),
            e.status,
            contract_type(db, tenant_id, e.id, as_of),
            p.gender if p and p.gender else "-",
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_payroll_summary_xlsx(db: Session, tenant_id, period: str,
                               person_ids: set | None = None) -> bytes | None:
    from openpyxl import Workbook

    _, last = parse_period(period)
    run = (
        db.execute(
            select(PayrollRun).where(PayrollRun.tenant_id == tenant_id,
                                    PayrollRun.period == period)
        )
        .scalars()
        .first()
    )
    if run is None:
        return None
    line_stmt = select(PayrollLine).where(
        PayrollLine.tenant_id == tenant_id,
        PayrollLine.payroll_run_id == run.id,
    )
    if person_ids is not None:
        line_stmt = line_stmt.join(
            Employment, Employment.id == PayrollLine.employment_id
        ).where(Employment.person_id.in_(person_ids))
    lines = db.execute(line_stmt.order_by(PayrollLine.person_name)).scalars().all()
    wb = Workbook()
    ws = wb.active
    ws.title = f"Payroll {period}"
    ws.append(["NIK", "Nama", "Unit", "Bruto", "Potongan", "PPh 21",
               "Reimbursement", "Take-Home", "Bank", "Rekening"])
    for ln in lines:
        ws.append([
            ln.nik, ln.person_name,
            org_unit_name(db, tenant_id, ln.employment_id, last),
            ln.gross or 0, ln.total_deductions or 0, ln.pph21 or 0,
            ln.reimbursement_amount or 0, ln.take_home_pay or 0,
            ln.bank_name or "-", ln.bank_account_no or "-",
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
