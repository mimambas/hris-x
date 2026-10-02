"""Kompensasi (CMP, PRD 12.4, F3).

- CMP-001: PayGrade (min/mid/max) menempel pada Job; compa-ratio =
  gaji_pokok / band_mid terhitung otomatis per karyawan.
- CMP-002: siklus merit/bonus + anggaran per unit + guideline
  (rating penilaian x compa-ratio) + approval berjenjang: usulan yang
  membuat unit melewati anggaran butuh persetujuan tambahan.
- CMP-003: total rewards statement (JSON + PDF) untuk karyawan.
- CMP-004: analitik kesetaraan upah per grade & gender (izin khusus
  `compensation_analytics`).
- CMP-005: finalisasi siklus merit menulis versi CompInfo bertanggal
  efektif baru dengan event_reason "Merit".

Semua mutasi beraudit; nominal integer rupiah (BigInteger di DB).
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timezone
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Appraisal,
    CompCycle,
    CompCycleBudget,
    CompInfo,
    CompProposal,
    Employment,
    Job,
    JobInfo,
    OrgUnit,
    OrgUnitInfo,
    PayGrade,
    Person,
    ReviewCycle,
    User,
)
from app.schemas.schemas import (
    CompBudgetOut,
    CompBudgetUpsert,
    CompCycleCreate,
    CompCycleDetail,
    CompCycleOut,
    CompEmployeeOut,
    CompProposalCreate,
    CompProposalOut,
    CompProposalUpdate,
    JobGradeAssign,
    JobGradeOut,
    PayGradeCreate,
    PayGradeOut,
    PayGradeUpdate,
    PayEquityGap,
    PayEquityOut,
    PayEquityRow,
    TotalRewardsOut,
)
from app.services import effective_dating as ed
from app.services import pph21 as pph21_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(prefix="/compensation", tags=["compensation"])

COMP_OBJECT = "compensation"
ANALYTICS_OBJECT = "compensation_analytics"

# Guideline bawaan (persen kenaikan gaji pokok) bila siklus tidak
# mendefinisikan sendiri: rating -> rentang persen.
DEFAULT_GUIDELINE = [
    {"min_rating": 4.5, "max_rating": 5.0, "min_pct": 8.0, "max_pct": 12.0},
    {"min_rating": 3.5, "max_rating": 4.49, "min_pct": 5.0, "max_pct": 8.0},
    {"min_rating": 2.5, "max_rating": 3.49, "min_pct": 2.0, "max_pct": 5.0},
    {"min_rating": 0.0, "max_rating": 2.49, "min_pct": 0.0, "max_pct": 2.0},
]


def _audit(request: Request, db: Session, user: User, action: str,
           object_type: str, object_id, new=None) -> None:
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action=action, object_type=object_type, object_id=object_id,
        new_values=new, channel="api", ip=client_ip(request),
    )


def _grade_or_404(db: Session, user: User, grade_id) -> PayGrade:
    g = db.get(PayGrade, grade_id)
    if g is None or g.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pay grade tidak ditemukan")
    return g


def _validate_band(band_min: int, band_mid: int, band_max: int) -> None:
    if not (band_min <= band_mid <= band_max):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Rentang gaji harus memenuhi min <= mid <= max",
        )


def _current_comp(db: Session, user: User, employment_id,
                  on: date | None = None) -> CompInfo | None:
    return ed.as_of(
        db=db, tenant_id=user.tenant_id, model=CompInfo,
        identity_field="employment_id", identity_value=employment_id,
        as_of_date=on or date.today(),
    )


def _current_job_info(db: Session, user: User, employment_id,
                      on: date | None = None) -> JobInfo | None:
    return ed.as_of(
        db=db, tenant_id=user.tenant_id, model=JobInfo,
        identity_field="employment_id", identity_value=employment_id,
        as_of_date=on or date.today(),
    )


def _unit_name(db: Session, user: User, org_unit_id) -> str | None:
    """Nama unit dari versi OrgUnitInfo yang berlaku hari ini."""
    if not org_unit_id:
        return None
    info = ed.as_of(
        db=db, tenant_id=user.tenant_id, model=OrgUnitInfo,
        identity_field="org_unit_id", identity_value=org_unit_id,
        as_of_date=date.today())
    return info.name if info else None


def _gaji_pokok(comp: CompInfo | None) -> int | None:
    if comp is None:
        return None
    value = (comp.components or {}).get("gaji_pokok")
    return int(value) if isinstance(value, int) else None


def _compa_ratio(gaji: int | None, grade: PayGrade | None) -> float | None:
    if gaji is None or grade is None or not grade.band_mid:
        return None
    return round(gaji / grade.band_mid, 4)


def _active_employments(db: Session, user: User) -> list[Employment]:
    return db.execute(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.status == "active",
        )
    ).scalars().all()


def _employee_row(db: Session, user: User, emp: Employment) -> CompEmployeeOut:
    person = db.get(Person, emp.person_id)
    ji = _current_job_info(db, user, emp.id)
    job = db.get(Job, ji.job_id) if ji else None
    grade = db.get(PayGrade, job.pay_grade_id) if job and job.pay_grade_id else None
    gaji = _gaji_pokok(_current_comp(db, user, emp.id))
    return CompEmployeeOut(
        person_id=emp.person_id, employment_id=emp.id,
        person_name=person.full_name if person else None,
        org_unit_id=ji.org_unit_id if ji else None,
        org_unit_name=_unit_name(db, user, ji.org_unit_id if ji else None),
        job_id=job.id if job else None,
        job_title=job.title if job else None,
        grade_id=grade.id if grade else None,
        grade_code=grade.code if grade else None,
        grade_name=grade.name if grade else None,
        gaji_pokok=gaji,
        compa_ratio=_compa_ratio(gaji, grade),
    )


# ---------------------------------------------------------------------------
# CMP-001: pay grade & penugasan grade ke jabatan
# ---------------------------------------------------------------------------


@router.post(
    "/pay-grades", response_model=PayGradeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(COMP_OBJECT, "insert"))],
)
def create_pay_grade(body: PayGradeCreate, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    _validate_band(body.band_min, body.band_mid, body.band_max)
    exists = db.execute(
        select(PayGrade).where(PayGrade.tenant_id == user.tenant_id,
                               PayGrade.code == body.code)
    ).scalars().first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Kode pay grade sudah digunakan")
    grade = PayGrade(tenant_id=user.tenant_id, code=body.code, name=body.name,
                     band_min=body.band_min, band_mid=body.band_mid,
                     band_max=body.band_max, is_active=True)
    db.add(grade)
    db.flush()
    _audit(request, db, user, "insert", COMP_OBJECT, grade.id,
           new={"code": grade.code})
    db.commit()
    return grade


@router.get(
    "/pay-grades", response_model=list[PayGradeOut],
    dependencies=[Depends(require_permission(COMP_OBJECT, "view"))],
)
def list_pay_grades(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return db.execute(
        select(PayGrade).where(PayGrade.tenant_id == user.tenant_id)
        .order_by(PayGrade.code)
    ).scalars().all()


@router.patch(
    "/pay-grades/{grade_id}", response_model=PayGradeOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def update_pay_grade(grade_id: uuid.UUID, body: PayGradeUpdate,
                     request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    grade = _grade_or_404(db, user, grade_id)
    data = body.model_dump(exclude_unset=True)
    merged = {
        "band_min": data.get("band_min", grade.band_min),
        "band_mid": data.get("band_mid", grade.band_mid),
        "band_max": data.get("band_max", grade.band_max),
    }
    _validate_band(**merged)
    for key, value in data.items():
        setattr(grade, key, value)
    _audit(request, db, user, "update", COMP_OBJECT, grade.id, new=data)
    db.commit()
    return grade


@router.get(
    "/jobs", response_model=list[JobGradeOut],
    dependencies=[Depends(require_permission(COMP_OBJECT, "view"))],
)
def list_jobs_with_grades(user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    jobs = db.execute(
        select(Job).where(Job.tenant_id == user.tenant_id).order_by(Job.code)
    ).scalars().all()
    grades = {g.id: g for g in db.execute(
        select(PayGrade).where(PayGrade.tenant_id == user.tenant_id)
    ).scalars().all()}
    return [
        JobGradeOut(
            job_id=j.id, code=j.code, title=j.title,
            pay_grade_id=j.pay_grade_id,
            grade_code=(grades[j.pay_grade_id].code
                        if j.pay_grade_id in grades else None),
            grade_name=(grades[j.pay_grade_id].name
                        if j.pay_grade_id in grades else None),
        )
        for j in jobs
    ]


@router.post(
    "/job-grades", response_model=JobGradeOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def assign_job_grade(body: JobGradeAssign, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    job = db.get(Job, body.job_id)
    if job is None or job.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jabatan tidak ditemukan")
    grade = None
    if body.pay_grade_id:
        grade = _grade_or_404(db, user, body.pay_grade_id)
    job.pay_grade_id = grade.id if grade else None
    _audit(request, db, user, "update", COMP_OBJECT, job.id,
           new={"pay_grade_id": str(grade.id) if grade else None})
    db.commit()
    return JobGradeOut(
        job_id=job.id, code=job.code, title=job.title,
        pay_grade_id=job.pay_grade_id,
        grade_code=grade.code if grade else None,
        grade_name=grade.name if grade else None,
    )


# ---------------------------------------------------------------------------
# CMP-001: daftar karyawan + compa-ratio
# ---------------------------------------------------------------------------


@router.get(
    "/employees", response_model=list[CompEmployeeOut],
    dependencies=[Depends(require_permission(COMP_OBJECT, "view"))],
)
def list_employees_comp(user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    rows = []
    for emp in _active_employments(db, user):
        # Manajer hanya melihat timnya (scope populasi); HR melihat semua.
        if not rbp_service.is_hr(db, user) and not population_service.can_view_person(
                db, user, emp.person_id):
            continue
        rows.append(_employee_row(db, user, emp))
    rows.sort(key=lambda r: (r.person_name or ""))
    return rows


# ---------------------------------------------------------------------------
# CMP-002: siklus merit/bonus, anggaran, guideline, approval berjenjang
# ---------------------------------------------------------------------------


def _cycle_or_404(db: Session, user: User, cycle_id) -> CompCycle:
    c = db.get(CompCycle, cycle_id)
    if c is None or c.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Siklus tidak ditemukan")
    return c


def _proposal_or_404(db: Session, user: User, proposal_id) -> CompProposal:
    p = db.get(CompProposal, proposal_id)
    if p is None or p.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usulan tidak ditemukan")
    return p


def _cycle_out(db: Session, cycle: CompCycle) -> CompCycleOut:
    props = db.execute(
        select(CompProposal).where(CompProposal.cycle_id == cycle.id)
    ).scalars().all()
    return CompCycleOut(
        id=cycle.id, name=cycle.name, kind=cycle.kind,
        period_year=cycle.period_year, effective_date=cycle.effective_date,
        status=cycle.status, guideline=cycle.guideline,
        created_at=cycle.created_at, finalized_at=cycle.finalized_at,
        proposal_total=len(props),
        proposal_approved=sum(1 for p in props if p.status == "approved"),
    )


def _annual_increase(cycle: CompCycle, current: int, proposed: int) -> int:
    # Merit: selisih gaji pokok disetahunkan. Bonus: nominal satu kali.
    if cycle.kind == "bonus":
        return proposed
    return max(proposed - current, 0) * 12


def _proposal_out(db: Session, user: User, cycle: CompCycle,
                  p: CompProposal) -> CompProposalOut:
    person = db.get(Person, p.person_id)
    increase_pct = (
        round((p.proposed_salary - p.current_salary) / p.current_salary * 100, 2)
        if p.current_salary else 0.0
    )
    within = None
    if p.guideline_min_pct is not None and p.guideline_max_pct is not None:
        within = float(p.guideline_min_pct) <= increase_pct <= float(p.guideline_max_pct)
    return CompProposalOut(
        id=p.id, cycle_id=p.cycle_id, employment_id=p.employment_id,
        person_id=p.person_id,
        person_name=person.full_name if person else None,
        org_unit_id=p.org_unit_id,
        org_unit_name=_unit_name(db, user, p.org_unit_id),
        current_salary=p.current_salary, proposed_salary=p.proposed_salary,
        increase_pct=increase_pct,
        annualized_increase=_annual_increase(cycle, p.current_salary,
                                             p.proposed_salary),
        rating=float(p.rating) if p.rating is not None else None,
        guideline_min_pct=(float(p.guideline_min_pct)
                           if p.guideline_min_pct is not None else None),
        guideline_max_pct=(float(p.guideline_max_pct)
                           if p.guideline_max_pct is not None else None),
        within_guideline=within, status=p.status, over_budget=p.over_budget,
        notes=p.notes, created_at=p.created_at, updated_at=p.updated_at,
    )


def _used_by_unit(db: Session, cycle: CompCycle, org_unit_id,
                  exclude_id=None) -> int:
    stmt = select(CompProposal).where(
        CompProposal.cycle_id == cycle.id,
        CompProposal.org_unit_id == org_unit_id,
        CompProposal.status.in_(
            ["submitted", "pending_extra_approval", "approved"]),
    )
    total = 0
    for p in db.execute(stmt).scalars().all():
        if exclude_id and p.id == exclude_id:
            continue
        total += _annual_increase(cycle, p.current_salary, p.proposed_salary)
    return total


def _latest_rating(db: Session, user: User, employment_id) -> float | None:
    row = db.execute(
        select(Appraisal.final_score).where(
            Appraisal.tenant_id == user.tenant_id,
            Appraisal.employment_id == employment_id,
            Appraisal.final_score.is_not(None),
        ).order_by(Appraisal.created_at.desc()).limit(1)
    ).first()
    return float(row[0]) if row else None


def _guideline_for(cycle: CompCycle, rating: float | None,
                   compa_ratio: float | None):
    """Rentang persen guideline: basis rating, digeser posisi compa-ratio."""
    if rating is None:
        return None, None
    bands = cycle.guideline or DEFAULT_GUIDELINE
    base = None
    for band in bands:
        if float(band["min_rating"]) <= rating <= float(band["max_rating"]):
            base = (float(band["min_pct"]), float(band["max_pct"]))
            break
    if base is None:
        return None, None
    shift = 0.0
    if compa_ratio is not None:
        if compa_ratio < 0.8:
            shift = 2.0
        elif compa_ratio > 1.0:
            shift = -2.0
    return (max(base[0] + shift, 0.0), max(base[1] + shift, 0.0))


@router.post(
    "/cycles", response_model=CompCycleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(COMP_OBJECT, "insert"))],
)
def create_cycle(body: CompCycleCreate, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    guideline = ([g.model_dump() for g in body.guideline]
                 if body.guideline else None)
    cycle = CompCycle(
        tenant_id=user.tenant_id, name=body.name, kind=body.kind,
        period_year=body.period_year, effective_date=body.effective_date,
        status="draft", guideline=guideline, created_by_user_id=user.id,
    )
    db.add(cycle)
    db.flush()
    _audit(request, db, user, "insert", COMP_OBJECT, cycle.id,
           new={"name": cycle.name, "kind": cycle.kind})
    db.commit()
    return _cycle_out(db, cycle)


@router.get(
    "/cycles", response_model=list[CompCycleOut],
    dependencies=[Depends(require_permission(COMP_OBJECT, "view"))],
)
def list_cycles(user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    cycles = db.execute(
        select(CompCycle).where(CompCycle.tenant_id == user.tenant_id)
        .order_by(CompCycle.period_year.desc(), CompCycle.created_at.desc())
    ).scalars().all()
    return [_cycle_out(db, c) for c in cycles]


@router.get(
    "/cycles/{cycle_id}", response_model=CompCycleDetail,
    dependencies=[Depends(require_permission(COMP_OBJECT, "view"))],
)
def get_cycle(cycle_id: uuid.UUID, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    cycle = _cycle_or_404(db, user, cycle_id)
    props = db.execute(
        select(CompProposal).where(CompProposal.cycle_id == cycle.id)
        .order_by(CompProposal.created_at)
    ).scalars().all()
    budget_rows = db.execute(
        select(CompCycleBudget).where(CompCycleBudget.cycle_id == cycle.id)
    ).scalars().all()
    unit_ids = {b.org_unit_id for b in budget_rows} | {
        p.org_unit_id for p in props if p.org_unit_id}
    budgets = []
    for unit_id in unit_ids:
        brow = next((b for b in budget_rows if b.org_unit_id == unit_id), None)
        used = _used_by_unit(db, cycle, unit_id)
        budgets.append(CompBudgetOut(
            org_unit_id=unit_id,
            org_unit_name=_unit_name(db, user, unit_id),
            budget_amount=brow.budget_amount if brow else None,
            used_amount=used,
            remaining=(brow.budget_amount - used if brow else None),
        ))
    budgets.sort(key=lambda b: (b.org_unit_name or ""))
    visible = []
    for p in props:
        if not rbp_service.is_hr(db, user) and not population_service.can_view_person(
                db, user, p.person_id):
            continue
        visible.append(_proposal_out(db, user, cycle, p))
    return CompCycleDetail(cycle=_cycle_out(db, cycle), budgets=budgets,
                           proposals=visible)


@router.post(
    "/cycles/{cycle_id}/open", response_model=CompCycleOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def open_cycle(cycle_id: uuid.UUID, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat membuka siklus")
    cycle = _cycle_or_404(db, user, cycle_id)
    if cycle.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Siklus tidak berstatus draft")
    cycle.status = "open"
    _audit(request, db, user, "update", COMP_OBJECT, cycle.id,
           new={"status": "open"})
    db.commit()
    return _cycle_out(db, cycle)


@router.post(
    "/cycles/{cycle_id}/cancel", response_model=CompCycleOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def cancel_cycle(cycle_id: uuid.UUID, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat membatalkan siklus")
    cycle = _cycle_or_404(db, user, cycle_id)
    if cycle.status in ("finalized", "cancelled"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Siklus sudah ditutup")
    cycle.status = "cancelled"
    _audit(request, db, user, "update", COMP_OBJECT, cycle.id,
           new={"status": "cancelled"})
    db.commit()
    return _cycle_out(db, cycle)


@router.put(
    "/cycles/{cycle_id}/budgets/{org_unit_id}", response_model=CompBudgetOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def upsert_budget(cycle_id: uuid.UUID, org_unit_id: uuid.UUID,
                  body: CompBudgetUpsert, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat menetapkan anggaran")
    cycle = _cycle_or_404(db, user, cycle_id)
    if cycle.status in ("finalized", "cancelled"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Siklus sudah ditutup")
    unit = db.get(OrgUnit, org_unit_id)
    if unit is None or unit.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit tidak ditemukan")
    row = db.execute(
        select(CompCycleBudget).where(
            CompCycleBudget.cycle_id == cycle.id,
            CompCycleBudget.org_unit_id == org_unit_id)
    ).scalars().first()
    if row is None:
        row = CompCycleBudget(tenant_id=user.tenant_id, cycle_id=cycle.id,
                              org_unit_id=org_unit_id,
                              budget_amount=body.budget_amount)
        db.add(row)
    else:
        row.budget_amount = body.budget_amount
    db.flush()
    _audit(request, db, user, "update", COMP_OBJECT, cycle.id,
           new={"budget_unit": str(org_unit_id),
                "budget_amount": body.budget_amount})
    db.commit()
    used = _used_by_unit(db, cycle, org_unit_id)
    return CompBudgetOut(
        org_unit_id=org_unit_id,
        org_unit_name=_unit_name(db, user, org_unit_id),
        budget_amount=row.budget_amount, used_amount=used,
        remaining=row.budget_amount - used)


@router.post(
    "/cycles/{cycle_id}/proposals", response_model=CompProposalOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def create_proposal(cycle_id: uuid.UUID, body: CompProposalCreate,
                    request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    cycle = _cycle_or_404(db, user, cycle_id)
    if cycle.status not in ("draft", "open"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Siklus sudah ditutup")
    emp = db.get(Employment, body.employment_id)
    if emp is None or emp.tenant_id != user.tenant_id or emp.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Karyawan aktif tidak ditemukan")
    if not rbp_service.is_hr(db, user) and not population_service.can_view_person(
            db, user, emp.person_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Di luar cakupan tim Anda")
    exists = db.execute(
        select(CompProposal).where(
            CompProposal.cycle_id == cycle.id,
            CompProposal.employment_id == emp.id)
    ).scalars().first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Karyawan sudah memiliki usulan pada siklus ini")
    comp = _current_comp(db, user, emp.id)
    current = _gaji_pokok(comp) if cycle.kind == "merit" else _gaji_pokok(comp)
    if current is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Karyawan belum memiliki data kompensasi (gaji pokok)")
    ji = _current_job_info(db, user, emp.id)
    job = db.get(Job, ji.job_id) if ji else None
    grade = (db.get(PayGrade, job.pay_grade_id)
             if job and job.pay_grade_id else None)
    rating = _latest_rating(db, user, emp.id)
    g_min, g_max = _guideline_for(cycle, rating, _compa_ratio(current, grade))
    prop = CompProposal(
        tenant_id=user.tenant_id, cycle_id=cycle.id, employment_id=emp.id,
        person_id=emp.person_id,
        org_unit_id=ji.org_unit_id if ji else None,
        current_salary=current, proposed_salary=body.proposed_salary,
        rating=rating, guideline_min_pct=g_min, guideline_max_pct=g_max,
        status="draft", notes=body.notes,
    )
    db.add(prop)
    db.flush()
    _audit(request, db, user, "insert", COMP_OBJECT, prop.id,
           new={"cycle_id": str(cycle.id), "employment_id": str(emp.id)})
    db.commit()
    return _proposal_out(db, user, cycle, prop)


@router.patch(
    "/proposals/{proposal_id}", response_model=CompProposalOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def update_proposal(proposal_id: uuid.UUID, body: CompProposalUpdate,
                    request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    prop = _proposal_or_404(db, user, proposal_id)
    if prop.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Usulan hanya dapat diubah saat draft")
    if not rbp_service.is_hr(db, user) and not population_service.can_view_person(
            db, user, prop.person_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Di luar cakupan tim Anda")
    cycle = _cycle_or_404(db, user, prop.cycle_id)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(prop, key, value)
    _audit(request, db, user, "update", COMP_OBJECT, prop.id, new=data)
    db.commit()
    return _proposal_out(db, user, cycle, prop)


@router.post(
    "/proposals/{proposal_id}/submit", response_model=CompProposalOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def submit_proposal(proposal_id: uuid.UUID, request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    prop = _proposal_or_404(db, user, proposal_id)
    if prop.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Usulan tidak berstatus draft")
    if not rbp_service.is_hr(db, user) and not population_service.can_view_person(
            db, user, prop.person_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Di luar cakupan tim Anda")
    cycle = _cycle_or_404(db, user, prop.cycle_id)
    prop.status = "submitted"
    prop.submitted_by_user_id = user.id
    _audit(request, db, user, "update", COMP_OBJECT, prop.id,
           new={"status": "submitted"})
    db.commit()
    return _proposal_out(db, user, cycle, prop)


@router.post(
    "/proposals/{proposal_id}/approve", response_model=CompProposalOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def approve_proposal(proposal_id: uuid.UUID, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Persetujuan usulan hanya oleh HR")
    prop = _proposal_or_404(db, user, proposal_id)
    if prop.status != "submitted":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Usulan tidak menunggu persetujuan")
    cycle = _cycle_or_404(db, user, prop.cycle_id)
    budget = None
    if prop.org_unit_id:
        row = db.execute(
            select(CompCycleBudget).where(
                CompCycleBudget.cycle_id == cycle.id,
                CompCycleBudget.org_unit_id == prop.org_unit_id)
        ).scalars().first()
        budget = row.budget_amount if row else None
    projected = _used_by_unit(db, cycle, prop.org_unit_id,
                              exclude_id=prop.id) + _annual_increase(
        cycle, prop.current_salary, prop.proposed_salary)
    prop.approved_by_user_id = user.id
    if budget is not None and projected > budget:
        # CMP-002: anggaran unit terlampaui -> wajib persetujuan tambahan.
        prop.status = "pending_extra_approval"
        prop.over_budget = True
    else:
        prop.status = "approved"
        prop.over_budget = False
    _audit(request, db, user, "approve", COMP_OBJECT, prop.id,
           new={"status": prop.status, "over_budget": prop.over_budget})
    db.commit()
    return _proposal_out(db, user, cycle, prop)


@router.post(
    "/proposals/{proposal_id}/approve-extra", response_model=CompProposalOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def approve_extra_proposal(proposal_id: uuid.UUID, request: Request,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Persetujuan tambahan hanya oleh HR")
    prop = _proposal_or_404(db, user, proposal_id)
    if prop.status != "pending_extra_approval":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Usulan tidak menunggu persetujuan tambahan")
    if prop.approved_by_user_id == user.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Persetujuan tambahan harus oleh HR yang berbeda")
    cycle = _cycle_or_404(db, user, prop.cycle_id)
    prop.status = "approved"
    prop.extra_approved_by_user_id = user.id
    _audit(request, db, user, "approve", COMP_OBJECT, prop.id,
           new={"status": "approved", "extra": True})
    db.commit()
    return _proposal_out(db, user, cycle, prop)


@router.post(
    "/proposals/{proposal_id}/reject", response_model=CompProposalOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def reject_proposal(proposal_id: uuid.UUID, request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Penolakan usulan hanya oleh HR")
    prop = _proposal_or_404(db, user, proposal_id)
    if prop.status not in ("submitted", "pending_extra_approval"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Usulan tidak menunggu keputusan")
    cycle = _cycle_or_404(db, user, prop.cycle_id)
    prop.status = "rejected"
    _audit(request, db, user, "reject", COMP_OBJECT, prop.id,
           new={"status": "rejected"})
    db.commit()
    return _proposal_out(db, user, cycle, prop)


@router.post(
    "/cycles/{cycle_id}/finalize", response_model=CompCycleOut,
    dependencies=[Depends(require_permission(COMP_OBJECT, "correct"))],
)
def finalize_cycle(cycle_id: uuid.UUID, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """CMP-005: terapkan usulan disetujui sebagai versi CompInfo baru."""
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Finalisasi siklus hanya oleh HR")
    cycle = _cycle_or_404(db, user, cycle_id)
    if cycle.status not in ("draft", "open"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Siklus sudah ditutup")
    props = db.execute(
        select(CompProposal).where(CompProposal.cycle_id == cycle.id)
    ).scalars().all()
    unresolved = [p for p in props
                  if p.status not in ("approved", "rejected")]
    if unresolved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Masih ada {len(unresolved)} usulan belum diputuskan")
    if cycle.kind == "merit":
        for prop in props:
            if prop.status != "approved":
                continue
            current = _current_comp(db, user, prop.employment_id)
            if current is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Data kompensasi karyawan tidak ditemukan saat finalisasi")
            person = db.get(Person, prop.person_id)
            components = dict(current.components or {})
            components["gaji_pokok"] = prop.proposed_salary
            try:
                ed.insert_record(
                    db=db, tenant_id=user.tenant_id, model=CompInfo,
                    identity_field="employment_id",
                    identity_value=prop.employment_id,
                    valid_from=cycle.effective_date,
                    values={
                        "pay_group": current.pay_group,
                        "components": components,
                        "ptkp": person.ptkp if person else current.ptkp,
                    },
                    event="compensation_change", event_reason="Merit",
                    created_by=user.id, event_applies_to="lifecycle",
                )
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    cycle.status = "finalized"
    cycle.finalized_at = datetime.now(timezone.utc)
    _audit(request, db, user, "finalize", COMP_OBJECT, cycle.id,
           new={"status": "finalized", "kind": cycle.kind})
    db.commit()
    return _cycle_out(db, cycle)


# ---------------------------------------------------------------------------
# CMP-003: total rewards statement (JSON + PDF)
# ---------------------------------------------------------------------------


def _rp(n: int) -> str:
    return f"Rp{n:,}".replace(",", ".")


def _total_rewards(db: Session, user: User, emp: Employment) -> TotalRewardsOut:
    comp = _current_comp(db, user, emp.id)
    if comp is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Karyawan belum memiliki data kompensasi")
    components = {k: int(v) for k, v in (comp.components or {}).items()
                  if isinstance(v, int)}
    base = components.get("gaji_pokok", 0) + components.get("tunjangan_tetap", 0)
    bpjs = pph21_service.employer_bpjs(base)
    thr = base
    annual = sum(components.values()) * 12 + sum(bpjs.values()) * 12 + thr
    person = db.get(Person, emp.person_id)
    return TotalRewardsOut(
        person_id=emp.person_id,
        person_name=person.full_name if person else None,
        as_of=date.today(), monthly_components=components,
        monthly_cash=sum(components.values()),
        employer_bpjs_monthly=bpjs,
        employer_bpjs_total_monthly=sum(bpjs.values()),
        thr_estimate=thr, annual_total=annual)


def _my_employment(db: Session, user: User) -> Employment:
    if not user.person_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Akun Anda tidak terikat data karyawan")
    emp = db.execute(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.person_id == user.person_id,
            Employment.status == "active",
        ).order_by(Employment.start_date.desc())
    ).scalars().first()
    if emp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Data kepegawaian aktif tidak ditemukan")
    return emp


@router.get("/total-rewards/me", response_model=TotalRewardsOut)
def my_total_rewards(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return _total_rewards(db, user, _my_employment(db, user))


def _render_rewards_pdf(r: TotalRewardsOut) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="Pernyataan Total Rewards")
    title_style = ParagraphStyle("t", fontSize=16, leading=20,
                                 spaceAfter=4)
    h_style = ParagraphStyle("h", fontSize=11, leading=14, spaceBefore=10,
                             spaceAfter=4, fontName="Helvetica-Bold")
    story = [
        Paragraph("Pernyataan Total Rewards", title_style),
        Paragraph(f"{r.person_name or ''} &middot; per {r.as_of.isoformat()}",
                  ParagraphStyle("s", fontSize=9, leading=12,
                                 textColor=colors.grey)),
        Spacer(1, 4 * mm),
        Paragraph("Komponen bulanan (dibayarkan ke karyawan)", h_style),
    ]
    rows = [[k.replace("_", " ").title(), _rp(v)]
            for k, v in sorted(r.monthly_components.items())]
    rows.append(["Total tunai bulanan", _rp(r.monthly_cash)])
    rows += [
        [k.replace("_", " ").replace("Perusahaan", "(perusahaan)").title(),
         _rp(v)]
        for k, v in sorted(r.employer_bpjs_monthly.items())
    ]
    rows.append(["Total kontribusi perusahaan / bulan",
                 _rp(r.employer_bpjs_total_monthly)])
    rows.append(["Tunjangan Hari Raya (estimasi tahunan)", _rp(r.thr_estimate)])
    rows.append(["TOTAL REWARDS TAHUNAN", _rp(r.annual_total)])
    table = Table(rows, colWidths=[95 * mm, 45 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "Dokumen ini ringkasan nilai total paket kompensasi tahunan "
        "berdasarkan data kompensasi yang berlaku saat ini. Kontribusi "
        "perusahaan mencakup BPJS Kesehatan, JKK, JKM, JHT, dan JP porsi "
        "pemberi kerja.", ParagraphStyle(
            "n", fontSize=8, leading=11, textColor=colors.grey)))
    doc.build(story)
    return buf.getvalue()


@router.get("/total-rewards/me/pdf")
def my_total_rewards_pdf(user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    rewards = _total_rewards(db, user, _my_employment(db, user))
    pdf = _render_rewards_pdf(rewards)
    name = (rewards.person_name or "karyawan").replace(" ", "-").lower()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="total-rewards-{name}.pdf"'})


@router.get(
    "/employees/{employment_id}/total-rewards/pdf",
    dependencies=[Depends(require_permission(COMP_OBJECT, "view"))],
)
def employee_total_rewards_pdf(employment_id: uuid.UUID,
                               user: User = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Karyawan tidak ditemukan")
    if not rbp_service.is_hr(db, user) and not population_service.can_view_person(
            db, user, emp.person_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Di luar cakupan tim Anda")
    rewards = _total_rewards(db, user, emp)
    pdf = _render_rewards_pdf(rewards)
    name = (rewards.person_name or "karyawan").replace(" ", "-").lower()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="total-rewards-{name}.pdf"'})


# ---------------------------------------------------------------------------
# CMP-004: analitik kesetaraan upah (izin khusus)
# ---------------------------------------------------------------------------

_GENDER_LABEL = {"L": "Laki-laki", "P": "Perempuan"}


@router.get(
    "/analytics/pay-equity", response_model=PayEquityOut,
    dependencies=[Depends(require_permission(ANALYTICS_OBJECT, "view"))],
)
def pay_equity(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    groups: dict[tuple, list[int]] = {}
    grade_names: dict[str | None, str | None] = {}
    for emp in _active_employments(db, user):
        row = _employee_row(db, user, emp)
        if row.gaji_pokok is None or row.grade_code is None:
            continue
        person = db.get(Person, emp.person_id)
        gender = _GENDER_LABEL.get(person.gender or "", "Tidak diketahui")
        groups.setdefault((row.grade_code, gender), []).append(row.gaji_pokok)
        grade_names[row.grade_code] = row.grade_name
    rows = []
    for (grade_code, gender), salaries in sorted(groups.items()):
        rows.append(PayEquityRow(
            grade_code=grade_code, grade_name=grade_names.get(grade_code),
            gender=gender, headcount=len(salaries),
            avg_salary=int(round(sum(salaries) / len(salaries))),
            median_salary=int(median(salaries))))
    gaps = []
    for grade_code in sorted({g for g, _ in groups}):
        laki = groups.get((grade_code, "Laki-laki"))
        per = groups.get((grade_code, "Perempuan"))
        if laki and per:
            avg_l = sum(laki) / len(laki)
            avg_p = sum(per) / len(per)
            gaps.append(PayEquityGap(
                grade_code=grade_code,
                grade_name=grade_names.get(grade_code),
                avg_laki=int(round(avg_l)), avg_perempuan=int(round(avg_p)),
                gap_pct=round((avg_l - avg_p) / avg_l * 100, 2)
                if avg_l else None))
    return PayEquityOut(rows=rows, gaps=gaps)
