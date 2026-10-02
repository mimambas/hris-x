"""Penilaian kinerja & pelatihan (Sprint 7, PRD 24.2 S7).

- Siklus: draft → goal_setting → mid_year → year_end → calibration →
  closed (maju satu langkah; closed = immutable).
- Goal: karyawan buat untuk dirinya → submit → atasan/HR approve/reject.
  Total bobot APPROVED harus == 100 saat approve maupun self-assessment.
- Appraisal: self-assessment → manager score → kalibrasi (potential) →
  final_score. Matriks 9-box hanya untuk HR (lihat ADR-0010).
- Pelatihan: katalog kursus + enrollment; rekomendasi rule-based
  (bukan AI) dari kotak 9-box.

Otorisasi: require_permission(object, action) + scope employment
(resolve_employment / population). Baca data milik orang lain oleh
karyawan biasa → 404 (jangan bocorkan keberadaan); mutasi tak berizin →
403. Setiap mutasi beraudit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, resolve_employment, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Appraisal,
    Document,
    Employment,
    JobInfo,
    PerformanceGoal,
    Person,
    ReviewCycle,
    TenantPerformancePolicy,
    TrainingAssignment,
    TrainingCourse,
    TrainingEnrollment,
    User,
)
from app.schemas.schemas import (
    AppraisalCreate,
    AppraisalOut,
    TrainingAssignmentCreate,
    TrainingAssignmentOut,
    CalibrateCreate,
    CertExpiringOut,
    CourseCreate,
    CourseOut,
    CycleCreate,
    CycleOut,
    CycleTransition,
    EnrollmentComplete,
    EnrollmentCreate,
    EnrollmentDecision,
    EnrollmentOut,
    EnrollmentProgress,
    GoalCreate,
    GoalDecision,
    GoalOut,
    ManagerScoreCreate,
    NineBoxEntry,
    NineBoxOut,
    PerformancePolicyOut,
    PerformancePolicyUpdate,
    SelfAssessmentCreate,
    TrainingRecommendationOut,
)
from app.services import effective_dating as ed
from app.services import performance as perf_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services import storage as storage_service
from app.services.audit import write_audit

router = APIRouter(tags=["performance"])

_SELF_PHASES = ("goal_setting", "mid_year", "year_end")


# ------------------------------------------------------------------ Helper
def _tenant_row(db: Session, user: User, model, row_id: uuid.UUID,
                label: str):
    row = db.get(model, row_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{label} tidak ditemukan")
    return row


def _get_cycle(db: Session, user: User, cycle_id: uuid.UUID) -> ReviewCycle:
    return _tenant_row(db, user, ReviewCycle, cycle_id, "Siklus penilaian")


def _get_goal(db: Session, user: User, goal_id: uuid.UUID) -> PerformanceGoal:
    return _tenant_row(db, user, PerformanceGoal, goal_id, "Goal")


def _get_appraisal(db: Session, user: User,
                   appraisal_id: uuid.UUID) -> Appraisal:
    return _tenant_row(db, user, Appraisal, appraisal_id, "Appraisal")


def _employment(db: Session, user: User,
                employment_id: uuid.UUID) -> Employment:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Employment tidak ditemukan")
    return emp


def _person_name(db: Session, employment: Employment) -> str:
    person = db.get(Person, employment.person_id)
    return person.full_name if person is not None else "?"


def _view_scope(db: Session, user: User, employment: Employment,
                object_name: str) -> None:
    """Baca data milik employment lain: 404 bila tak berhak (jangan
    bocorkan keberadaan record)."""
    if user.is_superadmin:
        return
    own = population_service.get_user_employment(db, user)
    if own is not None and str(own.id) == str(employment.id):
        return
    if (rbp_service.has_permission(db, user, object_name, "view")
            and population_service.can_view_person(
                db, user, employment.person_id)):
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Data tidak ditemukan")


def _mutate_scope(db: Session, user: User, employment: Employment,
                  object_name: str) -> None:
    """Mutasi atas data employment lain: 403 bila tak berhak."""
    if user.is_superadmin:
        return
    own = population_service.get_user_employment(db, user)
    if own is not None and str(own.id) == str(employment.id):
        return
    if (rbp_service.has_permission(db, user, object_name, "correct")
            and population_service.can_view_person(
                db, user, employment.person_id)):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")


def _manager_scope(db: Session, user: User, employment: Employment,
                   object_name: str, verb: str) -> None:
    """Aksi atasan/HR atas data bawahan: bukan diri sendiri + izin
    correct + masuk target population (tim)."""
    if user.is_superadmin:
        return
    own = population_service.get_user_employment(db, user)
    if own is not None and str(own.id) == str(employment.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Tidak bisa {verb} untuk diri sendiri")
    if (rbp_service.has_permission(db, user, object_name, "correct")
            and population_service.can_view_person(
                db, user, employment.person_id)):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")


def _require_hr_scope(db: Session, user: User) -> None:
    """Matriks 9-box & kalibrasi agregat hanya untuk HR: superadmin atau
    pemegang izin appraisal/view dengan target population 'all'
    (didokumentasikan di ADR-0010)."""
    if user.is_superadmin:
        return
    if not rbp_service.has_permission(db, user, "appraisal", "view"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang boleh melihat matriks 9-box")
    types = population_service._user_population_types(db, user, "appraisal")
    if "all" not in types:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang boleh melihat matriks 9-box")


def _audit(db: Session, user: User, request: Request, action: str,
           object_type: str, obj, old: dict | None, new: dict | None,
           reason: str | None = None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type=object_type,
                object_id=getattr(obj, "id", None),
                old_values=old, new_values=new, reason=reason,
                channel="api", ip=client_ip(request))


def _now():
    return datetime.now(timezone.utc)


# ================================================================ Siklus
@router.post("/performance/cycles",
             response_model=CycleOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("review_cycle",
                                                       "insert"))])
def create_cycle(body: CycleCreate, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "end_date harus >= start_date")
    cycle = ReviewCycle(tenant_id=user.tenant_id, name=body.name.strip(),
                        year=body.year, status="draft",
                        start_date=body.start_date, end_date=body.end_date)
    db.add(cycle)
    db.flush()
    _audit(db, user, request, "create", "review_cycle", cycle, None,
           snapshot(cycle, ["id", "name", "year", "status"]),
           reason="Siklus penilaian baru")
    db.commit()
    return cycle


@router.get("/performance/cycles",
            response_model=list[CycleOut],
            dependencies=[Depends(require_permission("review_cycle",
                                                       "view"))])
def list_cycles(year: int | None = Query(default=None),
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    stmt = select(ReviewCycle).where(
        ReviewCycle.tenant_id == user.tenant_id)
    if year is not None:
        stmt = stmt.where(ReviewCycle.year == year)
    return db.execute(stmt.order_by(ReviewCycle.year.desc())).scalars().all()


@router.get("/performance/cycles/{cycle_id}",
            response_model=CycleOut,
            dependencies=[Depends(require_permission("review_cycle",
                                                       "view"))])
def get_cycle(cycle_id: uuid.UUID,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return _get_cycle(db, user, cycle_id)


@router.post("/performance/cycles/{cycle_id}/transition",
             response_model=CycleOut,
             dependencies=[Depends(require_permission("review_cycle",
                                                       "correct"))])
def transition_cycle(cycle_id: uuid.UUID, body: CycleTransition,
                     request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    cycle = _get_cycle(db, user, cycle_id)
    old = cycle.status
    perf_service.check_transition(old, body.to_status)
    cycle.status = body.to_status
    db.flush()
    _audit(db, user, request, "transition", "review_cycle", cycle,
           {"status": old}, {"status": cycle.status},
           reason=f"Transisi fase {old} → {cycle.status}")
    db.commit()
    return cycle


# ================================================================ Goal
@router.post("/performance/cycles/{cycle_id}/goals",
             response_model=GoalOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("goal", "insert"))])
def create_goal(cycle_id: uuid.UUID, body: GoalCreate, request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    cycle = _get_cycle(db, user, cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    emp = resolve_employment(db, user, body.employment_id, "goal", "insert")
    goal = PerformanceGoal(
        tenant_id=user.tenant_id, employment_id=emp.id, cycle_id=cycle.id,
        title=body.title.strip(), description=(body.description or "").strip() or None,
        weight=body.weight,
        target_text=(body.target_text or "").strip() or None,
        status="draft")
    db.add(goal)
    db.flush()
    _audit(db, user, request, "create", "performance_goal", goal, None,
           snapshot(goal, ["id", "employment_id", "cycle_id", "title",
                           "weight", "status"]),
           reason="Goal kinerja baru")
    db.commit()
    return goal


@router.get("/performance/cycles/{cycle_id}/goals",
            response_model=list[GoalOut],
            dependencies=[Depends(require_permission("goal", "view"))])
def list_goals(cycle_id: uuid.UUID,
               employment_id: uuid.UUID = Query(...),
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    cycle = _get_cycle(db, user, cycle_id)
    emp = resolve_employment(db, user, employment_id, "goal", "view")
    rows = db.execute(
        select(PerformanceGoal).where(
            PerformanceGoal.tenant_id == user.tenant_id,
            PerformanceGoal.cycle_id == cycle.id,
            PerformanceGoal.employment_id == emp.id)
    ).scalars().all()
    return rows


@router.get("/performance/goals/{goal_id}",
            response_model=GoalOut,
            dependencies=[Depends(require_permission("goal", "view"))])
def get_goal(goal_id: uuid.UUID,
             user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    goal = _get_goal(db, user, goal_id)
    emp = _employment(db, user, goal.employment_id)
    _view_scope(db, user, emp, "goal")
    return goal


@router.post("/performance/goals/{goal_id}/submit",
             response_model=GoalOut,
             dependencies=[Depends(require_permission("goal", "correct"))])
def submit_goal(goal_id: uuid.UUID, request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    goal = _get_goal(db, user, goal_id)
    cycle = _get_cycle(db, user, goal.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    if goal.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Goal berstatus '{goal.status}', hanya draft "
                            "yang bisa di-submit")
    emp = _employment(db, user, goal.employment_id)
    _mutate_scope(db, user, emp, "goal")
    goal.status = "submitted"
    db.flush()
    _audit(db, user, request, "submit", "performance_goal", goal,
           {"status": "draft"}, {"status": "submitted"},
           reason="Goal di-submit untuk persetujuan")
    db.commit()
    return goal


@router.post("/performance/goals/{goal_id}/approve",
             response_model=GoalOut,
             dependencies=[Depends(require_permission("goal", "correct"))])
def approve_goal(goal_id: uuid.UUID, body: GoalDecision, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    goal = _get_goal(db, user, goal_id)
    cycle = _get_cycle(db, user, goal.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    if goal.status != "submitted":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Goal berstatus '{goal.status}', hanya submitted "
                            "yang bisa di-approve")
    emp = _employment(db, user, goal.employment_id)
    _manager_scope(db, user, emp, "goal", "menyetujui goal")
    # Syarat approval: total bobot goal AKTIF (submitted + approved) milik
    # karyawan harus tepat 100% — manajer menyetujui paket sasaran yang
    # lengkap, satu per satu. Invarian "total approved == 100" ditegakkan
    # saat self-assessment/appraisal dibuat via ensure_weight_100.
    active_total = sum(
        g.weight for g in db.execute(
            select(PerformanceGoal).where(
                PerformanceGoal.tenant_id == user.tenant_id,
                PerformanceGoal.cycle_id == cycle.id,
                PerformanceGoal.employment_id == emp.id,
                PerformanceGoal.status.in_(["submitted", "approved"]))
        ).scalars().all()
    )
    if active_total != 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Total bobot goal yang diajukan = {active_total}%, "
                            "harus tepat 100%")
    goal.status = "approved"
    if (body.note or "").strip():
        goal.manager_comment = body.note.strip()
    db.flush()
    _audit(db, user, request, "approve", "performance_goal", goal,
           {"status": "submitted"}, {"status": "approved"},
           reason=(body.note or "Goal disetujui")[:500])
    db.commit()
    return goal


@router.post("/performance/goals/{goal_id}/reject",
             response_model=GoalOut,
             dependencies=[Depends(require_permission("goal", "correct"))])
def reject_goal(goal_id: uuid.UUID, body: GoalDecision, request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    goal = _get_goal(db, user, goal_id)
    cycle = _get_cycle(db, user, goal.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    if goal.status != "submitted":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Goal berstatus '{goal.status}', hanya submitted "
                            "yang bisa di-reject")
    emp = _employment(db, user, goal.employment_id)
    _manager_scope(db, user, emp, "goal", "menolak goal")
    goal.status = "rejected"
    goal.manager_comment = (body.note or "").strip() or None
    db.flush()
    _audit(db, user, request, "reject", "performance_goal", goal,
           {"status": "submitted"}, {"status": "rejected"},
           reason=(body.note or "Goal ditolak")[:500])
    db.commit()
    return goal


# ================================================================ Appraisal
@router.post("/performance/appraisals",
             response_model=AppraisalOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("appraisal",
                                                       "insert"))])
def create_appraisal(body: AppraisalCreate, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    cycle = _get_cycle(db, user, body.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    emp = resolve_employment(db, user, body.employment_id, "appraisal",
                             "insert")
    exists = db.execute(
        select(Appraisal).where(
            Appraisal.tenant_id == user.tenant_id,
            Appraisal.employment_id == emp.id,
            Appraisal.cycle_id == cycle.id)
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Appraisal untuk employment & siklus ini sudah ada")
    appr = Appraisal(tenant_id=user.tenant_id, employment_id=emp.id,
                     cycle_id=cycle.id)
    db.add(appr)
    db.flush()
    _audit(db, user, request, "create", "appraisal", appr, None,
           snapshot(appr, ["id", "employment_id", "cycle_id"]),
           reason="Appraisal baru")
    db.commit()
    return appr


@router.get("/performance/appraisals/{appraisal_id}",
            response_model=AppraisalOut,
            dependencies=[Depends(require_permission("appraisal",
                                                       "view"))])
def get_appraisal(appraisal_id: uuid.UUID,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    appr = _get_appraisal(db, user, appraisal_id)
    emp = _employment(db, user, appr.employment_id)
    _view_scope(db, user, emp, "appraisal")
    return appr


@router.get("/performance/appraisals",
            response_model=list[AppraisalOut],
            dependencies=[Depends(require_permission("appraisal",
                                                       "view"))])
def list_appraisals(employment_id: uuid.UUID = Query(...),
                    cycle_id: uuid.UUID | None = Query(default=None),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Daftar appraisal milik satu employment (opsional filter siklus).

    Endpoint aditif untuk mendukung UI tab Penilaian (frontend butuh
    memuat ulang appraisal yang sudah dibuat tanpa menyimpan id).
    """
    emp = resolve_employment(db, user, employment_id, "appraisal", "view")
    _view_scope(db, user, emp, "appraisal")
    stmt = select(Appraisal).where(
        Appraisal.tenant_id == user.tenant_id,
        Appraisal.employment_id == emp.id)
    if cycle_id is not None:
        stmt = stmt.where(Appraisal.cycle_id == cycle_id)
    return db.execute(stmt.order_by(Appraisal.id)).scalars().all()


def _check_score_coverage(db: Session, user: User, appr: Appraisal,
                          scores: list, label: str) -> list[PerformanceGoal]:
    """Skor harus mencakup tepat seluruh goal APPROVED (tanpa duplikat)."""
    goals = perf_service.approved_goals(db, user.tenant_id,
                                        appr.employment_id, appr.cycle_id)
    want = {str(g.id) for g in goals}
    got = [str(s.goal_id) for s in scores]
    if len(got) != len(set(got)) or set(got) != want:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{label} harus mencakup tepat seluruh "
                            f"{len(want)} goal yang disetujui")
    return goals


@router.post("/performance/appraisals/{appraisal_id}/self-assessment",
             response_model=AppraisalOut,
             dependencies=[Depends(require_permission("appraisal",
                                                       "correct"))])
def self_assessment(appraisal_id: uuid.UUID, body: SelfAssessmentCreate,
                    request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    appr = _get_appraisal(db, user, appraisal_id)
    cycle = _get_cycle(db, user, appr.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    if cycle.status not in _SELF_PHASES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Self-assessment hanya dibuka pada fase "
                            f"{', '.join(_SELF_PHASES)}")
    emp = _employment(db, user, appr.employment_id)
    # Self-assessment: milik sendiri, atau HR (population all).
    if user.is_superadmin:
        pass
    else:
        own = population_service.get_user_employment(db, user)
        is_own = own is not None and str(own.id) == str(emp.id)
        hr_like = (rbp_service.has_permission(db, user, "appraisal",
                                              "correct")
                   and "all" in population_service._user_population_types(
                       db, user, "appraisal"))
        if not (is_own or hr_like):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")
    # Total bobot goal yang disetujui harus tepat 100%.
    perf_service.ensure_weight_100(db, user.tenant_id, emp.id, cycle.id)
    _check_score_coverage(db, user, appr, body.scores, "Self-assessment")
    appr.self_scores = [{"goal_id": str(s.goal_id), "score": s.score,
                         "comment": (s.comment or "").strip() or None}
                        for s in body.scores]
    appr.self_submitted_at = _now()
    db.flush()
    _audit(db, user, request, "self_assessment", "appraisal", appr, None,
           {"self_submitted_at": appr.self_submitted_at.isoformat(),
            "n_scores": len(body.scores)},
           reason="Self-assessment di-submit")
    db.commit()
    return appr


@router.post("/performance/appraisals/{appraisal_id}/manager-score",
             response_model=AppraisalOut,
             dependencies=[Depends(require_permission("appraisal",
                                                       "correct"))])
def manager_score(appraisal_id: uuid.UUID, body: ManagerScoreCreate,
                  request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    appr = _get_appraisal(db, user, appraisal_id)
    cycle = _get_cycle(db, user, appr.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    if cycle.status != "year_end":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Manager score hanya dibuka pada fase year_end")
    if appr.self_submitted_at is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Self-assessment karyawan belum di-submit")
    emp = _employment(db, user, appr.employment_id)
    _manager_scope(db, user, emp, "appraisal", "menilai")
    _check_score_coverage(db, user, appr, body.scores, "Manager score")
    appr.manager_scores = [{"goal_id": str(s.goal_id), "score": s.score}
                           for s in body.scores]
    appr.manager_submitted_at = _now()
    db.flush()
    _audit(db, user, request, "manager_score", "appraisal", appr, None,
           {"manager_submitted_at": appr.manager_submitted_at.isoformat(),
            "n_scores": len(body.scores)},
           reason="Manager score di-submit")
    db.commit()
    return appr


@router.post("/performance/appraisals/{appraisal_id}/calibrate",
             response_model=AppraisalOut,
             dependencies=[Depends(require_permission("appraisal",
                                                       "correct"))])
def calibrate(appraisal_id: uuid.UUID, body: CalibrateCreate,
              request: Request,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    appr = _get_appraisal(db, user, appraisal_id)
    cycle = _get_cycle(db, user, appr.cycle_id)
    perf_service.ensure_cycle_mutable(cycle)
    if cycle.status != "calibration":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Kalibrasi potensial hanya pada fase calibration")
    if not appr.manager_scores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Manager score belum diisi")
    emp = _employment(db, user, appr.employment_id)
    _manager_scope(db, user, emp, "appraisal", "mengkalibrasi")
    goals = perf_service.approved_goals(db, user.tenant_id, emp.id,
                                        cycle.id)
    weight_by_goal = {str(g.id): g.weight for g in goals}
    old = {"potential_score": appr.potential_score,
           "final_score": (str(appr.final_score)
                           if appr.final_score is not None else None)}
    appr.potential_score = body.potential_score
    appr.final_score = perf_service.compute_final_score(
        appr.manager_scores, weight_by_goal)
    db.flush()
    _audit(db, user, request, "calibrate", "appraisal", appr, old,
           {"potential_score": appr.potential_score,
            "final_score": str(appr.final_score)},
           reason="Kalibrasi potensial + final score")
    db.commit()
    return appr


# ================================================================ 9-box
@router.get("/performance/cycles/{cycle_id}/nine-box",
            response_model=NineBoxOut,
            dependencies=[Depends(require_permission("appraisal",
                                                       "view"))])
def nine_box_matrix(cycle_id: uuid.UUID,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    cycle = _get_cycle(db, user, cycle_id)
    _require_hr_scope(db, user)
    if cycle.status not in ("calibration", "closed"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Matriks 9-box hanya tersedia pada fase "
                            "calibration/closed")
    policy = perf_service.get_policy(db, user.tenant_id)
    apprs = db.execute(
        select(Appraisal).where(
            Appraisal.tenant_id == user.tenant_id,
            Appraisal.cycle_id == cycle.id,
            Appraisal.final_score.is_not(None),
            Appraisal.potential_score.is_not(None))
    ).scalars().all()
    boxes: dict[str, list[NineBoxEntry]] = {
        key: [] for key in perf_service.TRAINING_RECOMMENDATIONS}
    for appr in apprs:
        emp = db.get(Employment, appr.employment_id)
        if emp is None:
            continue
        box = perf_service.nine_box(appr.final_score,
                                    appr.potential_score, policy)
        boxes[box["box_key"]].append(NineBoxEntry(
            employment_id=emp.id, person_name=_person_name(db, emp),
            final_score=float(appr.final_score),
            potential_score=appr.potential_score,
            perf_category=box["perf_category"],
            pot_category=box["pot_category"], box_key=box["box_key"],
            label_id=box["label_id"], label_en=box["label_en"]))
    for entries in boxes.values():
        entries.sort(key=lambda e: e.person_name)
    return NineBoxOut(cycle_id=cycle.id, cycle_name=cycle.name, boxes=boxes)


@router.get("/performance/cycles/{cycle_id}/training-recommendations",
            response_model=TrainingRecommendationOut,
            dependencies=[Depends(require_permission("appraisal",
                                                       "view"))])
def training_recommendations(
        cycle_id: uuid.UUID,
        employment_id: uuid.UUID = Query(...),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    cycle = _get_cycle(db, user, cycle_id)
    emp = resolve_employment(db, user, employment_id, "appraisal", "view")
    # Karyawan biasa yang mengintip milik orang lain → 404.
    _view_scope(db, user, emp, "appraisal")
    appr = db.execute(
        select(Appraisal).where(
            Appraisal.tenant_id == user.tenant_id,
            Appraisal.employment_id == emp.id,
            Appraisal.cycle_id == cycle.id)
    ).scalar_one_or_none()
    if appr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Appraisal tidak ditemukan")
    box = perf_service.appraisal_box(db, appr)
    if box is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Appraisal belum dikalibrasi")
    courses = db.execute(
        select(TrainingCourse).where(
            TrainingCourse.tenant_id == user.tenant_id)
    ).scalars().all()
    return TrainingRecommendationOut(
        employment_id=emp.id, person_name=_person_name(db, emp),
        box_key=box["box_key"], label_id=box["label_id"],
        label_en=box["label_en"], final_score=float(appr.final_score),
        potential_score=appr.potential_score,
        recommended_categories=perf_service.training_recommendations(
            box["box_key"]),
        courses=[CourseOut.model_validate(c) for c in courses])


# ================================================================ Kebijakan
@router.get("/performance/policy",
            response_model=PerformancePolicyOut,
            dependencies=[Depends(require_permission("review_cycle",
                                                       "view"))])
def get_policy(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    p = perf_service.get_policy(db, user.tenant_id)
    return PerformancePolicyOut(**p)


@router.put("/performance/policy",
            response_model=PerformancePolicyOut,
            dependencies=[Depends(require_permission("review_cycle",
                                                       "correct"))])
def update_policy(body: PerformancePolicyUpdate, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    row = db.execute(
        select(TenantPerformancePolicy).where(
            TenantPerformancePolicy.tenant_id == user.tenant_id)
    ).scalar_one_or_none()
    if row is None:
        row = TenantPerformancePolicy(tenant_id=user.tenant_id)
        db.add(row)
        db.flush()
    old = snapshot(row, ["perf_low_max", "perf_med_max", "pot_low_max",
                         "pot_med_max"])
    row.perf_low_max = body.perf_low_max
    row.perf_med_max = body.perf_med_max
    row.pot_low_max = body.pot_low_max
    row.pot_med_max = body.pot_med_max
    db.flush()
    _audit(db, user, request, "correct", "tenant_performance_policy", row,
           old, snapshot(row, ["perf_low_max", "perf_med_max", "pot_low_max",
                               "pot_med_max"]),
           reason="Ubah ambang 9-box")
    db.commit()
    return PerformancePolicyOut(
        perf_low_max=float(row.perf_low_max),
        perf_med_max=float(row.perf_med_max),
        pot_low_max=float(row.pot_low_max),
        pot_med_max=float(row.pot_med_max))


# ================================================================ Pelatihan
@router.post("/performance/courses",
             response_model=CourseOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("training_course",
                                                       "insert"))])
def create_course(body: CourseCreate, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    dup = db.execute(
        select(TrainingCourse).where(
            TrainingCourse.tenant_id == user.tenant_id,
            TrainingCourse.code == body.code.strip())
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Kode kursus '{body.code}' sudah dipakai")
    course = TrainingCourse(
        tenant_id=user.tenant_id, code=body.code.strip(),
        name=body.name.strip(),
        provider=(body.provider or "").strip() or None,
        duration_hours=body.duration_hours, cost=body.cost,
        content_type=body.content_type,
        content_url=(body.content_url or "").strip() or None,
        passing_score=body.passing_score,
        cert_validity_months=body.cert_validity_months)
    db.add(course)
    db.flush()
    _audit(db, user, request, "create", "training_course", course, None,
           snapshot(course, ["id", "code", "name", "cost"]),
           reason="Kursus baru")
    db.commit()
    return course


@router.get("/performance/courses",
            response_model=list[CourseOut],
            dependencies=[Depends(require_permission("training_course",
                                                       "view"))])
def list_courses(user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return db.execute(
        select(TrainingCourse).where(
            TrainingCourse.tenant_id == user.tenant_id)
        .order_by(TrainingCourse.code)
    ).scalars().all()


def _get_enrollment(db: Session, user: User,
                    enrollment_id: uuid.UUID) -> TrainingEnrollment:
    return _tenant_row(db, user, TrainingEnrollment, enrollment_id,
                       "Enrollment")


@router.post("/performance/enrollments",
             response_model=EnrollmentOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("training_enrollment",
                                                       "insert"))])
def create_enrollment(body: EnrollmentCreate, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    emp = resolve_employment(db, user, body.employment_id,
                             "training_enrollment", "insert")
    course = _tenant_row(db, user, TrainingCourse, body.course_id, "Kursus")
    cycle = None
    if body.cycle_id is not None:
        cycle = _get_cycle(db, user, body.cycle_id)
        perf_service.ensure_cycle_mutable(cycle)
    enr = TrainingEnrollment(tenant_id=user.tenant_id, employment_id=emp.id,
                            course_id=course.id,
                            cycle_id=cycle.id if cycle else None,
                            status="registered",
                            due_date=body.due_date,
                            is_mandatory=body.is_mandatory)
    db.add(enr)
    db.flush()
    _audit(db, user, request, "create", "training_enrollment", enr, None,
           snapshot(enr, ["id", "employment_id", "course_id", "cycle_id",
                           "status"]),
           reason="Pendaftaran pelatihan")
    db.commit()
    return enr


@router.get("/performance/enrollments",
            response_model=list[EnrollmentOut],
            dependencies=[Depends(require_permission("training_enrollment",
                                                       "view"))])
def list_enrollments(employment_id: uuid.UUID | None = Query(default=None),
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    # employment_id opsional: bila diisi, filter ke satu employment (dengan
    # cek RBP); bila kosong, kembalikan seluruh enrollment tenant — dipakai
    # halaman Pelatihan (tabel pendaftaran tenant-wide).
    q = select(TrainingEnrollment).where(
        TrainingEnrollment.tenant_id == user.tenant_id)
    if employment_id is not None:
        emp = resolve_employment(db, user, employment_id,
                                 "training_enrollment", "view")
        q = q.where(TrainingEnrollment.employment_id == emp.id)
    return db.execute(q.order_by(TrainingEnrollment.id)).scalars().all()


@router.get("/performance/enrollments/{enrollment_id}",
            response_model=EnrollmentOut,
            dependencies=[Depends(require_permission("training_enrollment",
                                                       "view"))])
def get_enrollment(enrollment_id: uuid.UUID,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    enr = _get_enrollment(db, user, enrollment_id)
    emp = _employment(db, user, enr.employment_id)
    _view_scope(db, user, emp, "training_enrollment")
    return enr


@router.post("/performance/enrollments/{enrollment_id}/complete",
             response_model=EnrollmentOut,
             dependencies=[Depends(require_permission("training_enrollment",
                                                       "correct"))])
def complete_enrollment(enrollment_id: uuid.UUID, body: EnrollmentComplete,
                        request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    enr = _get_enrollment(db, user, enrollment_id)
    emp = _employment(db, user, enr.employment_id)
    _mutate_scope(db, user, emp, "training_enrollment")
    if enr.cycle_id is not None:
        perf_service.ensure_cycle_mutable(
            _get_cycle(db, user, enr.cycle_id))
    if enr.status == "completed":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Enrollment sudah completed")
    if enr.status == "cancelled":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Enrollment sudah cancelled")
    # LRN-003: gerbang nilai lulus — post-test wajib mencapai ambang kursus.
    course = _tenant_row(db, user, TrainingCourse, enr.course_id, "Kursus")
    post_score = body.post_score if body.post_score is not None \
        else enr.post_score
    if course.passing_score is not None:
        if post_score is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Kursus ini mensyaratkan skor post-test untuk selesai")
        if post_score < course.passing_score:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Skor post-test {post_score} belum mencapai nilai lulus "
                f"{course.passing_score}")
    enr.status = "completed"
    enr.completed_at = _now()
    enr.progress_percent = 100
    if post_score is not None:
        enr.post_score = post_score
    if course.cert_validity_months:
        enr.cert_expires_at = _add_months(
            enr.completed_at.date(), course.cert_validity_months)
    # LRN-003: sertifikat terbit otomatis (dokumen PDF) kecuali sertifikat
    # eksternal dilampirkan manual lewat body.certificate_document_id.
    if body.certificate_document_id is not None:
        enr.certificate_document_id = body.certificate_document_id
    elif enr.certificate_document_id is None:
        doc = _issue_certificate(db, user, emp, course, enr)
        enr.certificate_document_id = doc.id
    db.flush()
    _audit(db, user, request, "complete", "training_enrollment", enr,
           {"status": "registered"},
           {"status": "completed", "post_score": enr.post_score,
            "certificate_document_id": str(enr.certificate_document_id)
            if enr.certificate_document_id else None},
           reason="Pelatihan selesai")
    db.commit()
    return enr


@router.post("/performance/enrollments/{enrollment_id}/cancel",
             response_model=EnrollmentOut,
             dependencies=[Depends(require_permission("training_enrollment",
                                                       "correct"))])
def cancel_enrollment(enrollment_id: uuid.UUID, body: EnrollmentDecision,
                      request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    enr = _get_enrollment(db, user, enrollment_id)
    emp = _employment(db, user, enr.employment_id)
    _mutate_scope(db, user, emp, "training_enrollment")
    if enr.cycle_id is not None:
        perf_service.ensure_cycle_mutable(
            _get_cycle(db, user, enr.cycle_id))
    if enr.status in ("completed", "cancelled"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Enrollment sudah '{enr.status}'")
    enr.status = "cancelled"
    db.flush()
    _audit(db, user, request, "cancel", "training_enrollment", enr,
           {"status": "registered"}, {"status": "cancelled"},
           reason=(body.reason or "Enrollment dibatalkan")[:500])
    db.commit()
    return enr


# ---------------------------------------------------------------------------
# Learning lanjutan (LRN, PRD 12.5) — progres, penugasan wajib, sertifikat.
# Catatan penyederhanaan jujur: "pengingat" sertifikasi kedaluwarsa berupa
# daftar endpoint + panel UI (belum ada kanal email/push di sistem).
# ---------------------------------------------------------------------------
def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def _issue_certificate(db: Session, user: User, emp: Employment,
                       course: TrainingCourse,
                       enr: TrainingEnrollment) -> Document:
    """LRN-003: terbitkan sertifikat PDF otomatis sebagai dokumen resmi."""
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    person = db.get(Person, emp.person_id)
    nama = person.full_name if person else "-"
    selesai = enr.completed_at.date().isoformat() if enr.completed_at else "-"
    baris = [
        ("Nama Karyawan", nama),
        ("Kursus", f"{course.name} ({course.code})"),
    ]
    if enr.post_score is not None:
        baris.append(("Nilai Post-Test", str(enr.post_score)))
    baris.append(("Tanggal Selesai", selesai))
    if enr.cert_expires_at is not None:
        baris.append(("Berlaku Hingga", enr.cert_expires_at.isoformat()))

    import io
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    doc_tpl = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=20 * mm, rightMargin=20 * mm,
                                topMargin=20 * mm, bottomMargin=20 * mm)
    story = [Paragraph("SERTIFIKAT KELULUSAN PELATIHAN",
                       styles["Title"]), Spacer(1, 10 * mm)]
    for label, value in baris:
        story.append(Paragraph(
            f"<b>{escape(label)}:</b> {escape(str(value))}",
            styles["Normal"]))
        story.append(Spacer(1, 3 * mm))
    doc_tpl.build(story)
    data = buf.getvalue()

    filename = f"Sertifikat-{course.code}-{enr.id}.pdf"
    key = storage_service.get_storage().save(
        str(user.tenant_id), filename, data, "application/pdf")
    doc = Document(
        tenant_id=user.tenant_id, person_id=emp.person_id,
        employment_id=emp.id, doc_type="sertifikat", file_name=filename,
        mime_type="application/pdf", size_bytes=len(data), file_path=key,
        version=1, is_current=True,
        notes=f"Sertifikat otomatis kursus {course.code}",
        uploaded_by_user_id=user.id)
    db.add(doc)
    db.flush()
    return doc


@router.post("/performance/enrollments/{enrollment_id}/progress",
             response_model=EnrollmentOut,
             dependencies=[Depends(require_permission("training_enrollment",
                                                      "correct"))])
def update_progress(enrollment_id: uuid.UUID, body: EnrollmentProgress,
                    request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """LRN-001: progres belajar terlacak per karyawan (+ skor pre/post)."""
    enr = _get_enrollment(db, user, enrollment_id)
    emp = _employment(db, user, enr.employment_id)
    _mutate_scope(db, user, emp, "training_enrollment")
    if enr.cycle_id is not None:
        perf_service.ensure_cycle_mutable(
            _get_cycle(db, user, enr.cycle_id))
    if enr.status in ("completed", "cancelled"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Enrollment sudah '{enr.status}', progres tidak bisa diubah")
    enr.progress_percent = body.progress_percent
    if body.pre_score is not None:
        enr.pre_score = body.pre_score
    if body.post_score is not None:
        enr.post_score = body.post_score
    if enr.status == "registered" and body.progress_percent > 0:
        enr.status = "in_progress"
    db.flush()
    _audit(db, user, request, "update", "training_enrollment", enr, None,
           {"progress_percent": enr.progress_percent,
            "pre_score": enr.pre_score, "post_score": enr.post_score,
            "status": enr.status},
           reason="Progres belajar diperbarui")
    db.commit()
    return enr


@router.post("/performance/assignments",
             response_model=TrainingAssignmentOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("training_course",
                                                      "insert"))])
def create_assignment(body: TrainingAssignmentCreate, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """LRN-002: tugaskan kursus wajib ke populasi; materialkan enrollment."""
    course = _tenant_row(db, user, TrainingCourse, body.course_id, "Kursus")
    if body.target_type == "org_unit" and body.org_unit_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "org_unit_id wajib untuk target org_unit")
    if body.target_type == "job" and body.job_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "job_id wajib untuk target job")
    today = date.today()
    due = today + timedelta(days=body.due_days)
    targets: list[Employment] = []
    employments = db.execute(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.status == "active")
    ).scalars().all()
    for emp in employments:
        if body.target_type == "all":
            targets.append(emp)
            continue
        info = ed.as_of(
            db=db, tenant_id=user.tenant_id, model=JobInfo,
            identity_field="employment_id", identity_value=emp.id,
            as_of_date=today)
        if info is None:
            continue
        if body.target_type == "org_unit" \
                and str(info.org_unit_id) == str(body.org_unit_id):
            targets.append(emp)
        elif body.target_type == "job" \
                and str(info.job_id) == str(body.job_id):
            targets.append(emp)
    created = 0
    for emp in targets:
        existing = db.execute(
            select(TrainingEnrollment).where(
                TrainingEnrollment.tenant_id == user.tenant_id,
                TrainingEnrollment.employment_id == emp.id,
                TrainingEnrollment.course_id == course.id,
                TrainingEnrollment.status.in_(
                    ["registered", "in_progress"]))
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(TrainingEnrollment(
            tenant_id=user.tenant_id, employment_id=emp.id,
            course_id=course.id, status="registered",
            due_date=due, is_mandatory=True))
        created += 1
    asg = TrainingAssignment(
        tenant_id=user.tenant_id, course_id=course.id,
        target_type=body.target_type, org_unit_id=body.org_unit_id,
        job_id=body.job_id, due_days=body.due_days,
        enrollments_created=created, created_by_user_id=user.id)
    db.add(asg)
    db.flush()
    _audit(db, user, request, "create", "training_assignment", asg, None,
           snapshot(asg, ["id", "course_id", "target_type", "due_days",
                          "enrollments_created"]),
           reason="Penugasan pelatihan wajib")
    db.commit()
    return asg


@router.get("/performance/assignments", response_model=list[TrainingAssignmentOut],
            dependencies=[Depends(require_permission("training_enrollment",
                                                     "view"))])
def list_assignments(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return db.execute(
        select(TrainingAssignment).where(
            TrainingAssignment.tenant_id == user.tenant_id)
        .order_by(TrainingAssignment.created_at.desc())
    ).scalars().all()


def _population_filter(db: Session, user: User,
                       rows: list[TrainingEnrollment]
                       ) -> list[TrainingEnrollment]:
    """Batasi daftar ke populasi yang boleh dilihat user (None = semua)."""
    visible = population_service.get_visible_person_ids(db, user)
    if visible is None:
        return rows
    emp_ids = {str(e.id) for e in db.execute(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.person_id.in_(visible))
    ).scalars().all()}
    return [r for r in rows if str(r.employment_id) in emp_ids]


@router.get("/performance/learning/overdue", response_model=list[EnrollmentOut],
            dependencies=[Depends(require_permission("training_enrollment",
                                                     "view"))])
def list_overdue(user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """LRN-002: pelatihan (wajib bertenggat) yang terlambat — untuk atasan/HR."""
    rows = db.execute(
        select(TrainingEnrollment).where(
            TrainingEnrollment.tenant_id == user.tenant_id,
            TrainingEnrollment.due_date.is_not(None),
            TrainingEnrollment.due_date < date.today(),
            TrainingEnrollment.status.in_(["registered", "in_progress"]))
        .order_by(TrainingEnrollment.due_date)
    ).scalars().all()
    return _population_filter(db, user, rows)


@router.get("/performance/learning/certifications/expiring",
            response_model=list[CertExpiringOut],
            dependencies=[Depends(require_permission("training_enrollment",
                                                     "view"))])
def list_expiring_certifications(
        within_days: int = Query(default=30, ge=0, le=365),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    """LRN-003: sertifikasi yang kedaluwarsa dalam ``within_days`` hari."""
    today = date.today()
    batas = today + timedelta(days=within_days)
    rows = db.execute(
        select(TrainingEnrollment).where(
            TrainingEnrollment.tenant_id == user.tenant_id,
            TrainingEnrollment.status == "completed",
            TrainingEnrollment.cert_expires_at.is_not(None),
            TrainingEnrollment.cert_expires_at <= batas)
        .order_by(TrainingEnrollment.cert_expires_at)
    ).scalars().all()
    rows = _population_filter(db, user, rows)
    out: list[CertExpiringOut] = []
    for enr in rows:
        emp = db.get(Employment, enr.employment_id)
        person = db.get(Person, emp.person_id) if emp else None
        course = db.get(TrainingCourse, enr.course_id)
        out.append(CertExpiringOut(
            enrollment_id=enr.id, employment_id=enr.employment_id,
            person_name=person.full_name if person else "-",
            course_code=course.code if course else "-",
            course_name=course.name if course else "-",
            completed_at=enr.completed_at,
            cert_expires_at=enr.cert_expires_at,
            days_remaining=(enr.cert_expires_at - today).days))
    return out
