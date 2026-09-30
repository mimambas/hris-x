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
from datetime import datetime, timezone

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
    Employment,
    PerformanceGoal,
    Person,
    ReviewCycle,
    TenantPerformancePolicy,
    TrainingCourse,
    TrainingEnrollment,
    User,
)
from app.schemas.schemas import (
    AppraisalCreate,
    AppraisalOut,
    CalibrateCreate,
    CourseCreate,
    CourseOut,
    CycleCreate,
    CycleOut,
    CycleTransition,
    EnrollmentComplete,
    EnrollmentCreate,
    EnrollmentDecision,
    EnrollmentOut,
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
from app.services import performance as perf_service
from app.services import population as population_service
from app.services import rbp as rbp_service
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
    # Total bobot APPROVED (termasuk goal ini) harus tepat 100%.
    total = (perf_service.approved_weight_total(db, user.tenant_id, emp.id,
                                               cycle.id) + goal.weight)
    if total != 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Total bobot goal yang disetujui = {total}%, "
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
        duration_hours=body.duration_hours, cost=body.cost)
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
                            status="registered")
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
def list_enrollments(employment_id: uuid.UUID = Query(...),
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    emp = resolve_employment(db, user, employment_id, "training_enrollment",
                             "view")
    return db.execute(
        select(TrainingEnrollment).where(
            TrainingEnrollment.tenant_id == user.tenant_id,
            TrainingEnrollment.employment_id == emp.id)
    ).scalars().all()


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
    enr.status = "completed"
    enr.completed_at = _now()
    if body.certificate_document_id is not None:
        enr.certificate_document_id = body.certificate_document_id
    db.flush()
    _audit(db, user, request, "complete", "training_enrollment", enr,
           {"status": "registered"}, {"status": "completed"},
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
