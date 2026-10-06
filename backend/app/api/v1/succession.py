"""Suksesi & karier (SUC, PRD 12.6 F3).

- SUC-001 Profil talent: skill + pengalaman (JobInfo) + sertifikasi
  (Learning) + preferensi mobilitas/aspirasi, diagregasi per employment.
- SUC-002 Posisi kunci (positions.is_key) + nominasi suksesor dengan
  tingkat kesiapan; posisi kunci tanpa suksesor "siap sekarang" ditandai
  lewat /talent/key-positions (has_ready_successor=false) & /gaps.
- SUC-003 Talent pool: snapshot materialisasi matriks 9-box satu siklus.
- SUC-004 Jalur karier antarjabatan + IDP yang itemnya terhubung ke
  kursus Learning.
- SUC-005 Marketplace peluang internal; privasi lamaran ditegakkan di
  lapis query: atasan pelamar hanya melihat status >= "seleksi".
- SUC-006 Ontologi skill dengan governance: skill baru berstatus
  "usulan", wajib disetujui HR sebelum terhitung resmi di profil/pool.
  Tanpa inferensi AI (ditunda, pola yang sama seperti LRN-004).

Otorisasi: izin objek "talent" (view/insert/correct/delete) +
scope employment ala performance.py — baca data orang lain oleh yang
tak berhak -> 404; mutasi tak berizin -> 403. Perencanaan suksesi &
talent pool khusus HR. Setiap mutasi beraudit.
"""

from __future__ import annotations

import uuid
from datetime import date

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

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Appraisal,
    CareerPath,
    Employment,
    Idp,
    IdpItem,
    InternalApplication,
    InternalOpportunity,
    Job,
    JobInfo,
    OrgUnitInfo,
    Person,
    PersonSkill,
    Position,
    ReviewCycle,
    Skill,
    SuccessionNomination,
    TalentPool,
    TalentPoolMember,
    TalentProfile,
    TrainingCourse,
    TrainingEnrollment,
    User,
)
from app.schemas.schemas import (
    CareerPathCreate,
    CareerPathOut,
    IdpCreate,
    IdpItemCreate,
    IdpItemOut,
    IdpItemUpdate,
    IdpOut,
    InternalApplicationCreate,
    InternalApplicationDecision,
    InternalApplicationOut,
    InternalOpportunityCreate,
    InternalOpportunityOut,
    KeyPositionFlagUpdate,
    KeyPositionOut,
    PersonSkillCreate,
    PersonSkillOut,
    SuccessionNominationCreate,
    SuccessionNominationOut,
    TalentCandidateOut,
    TalentCertificationOut,
    TalentPoolCreate,
    TalentPoolMemberOut,
    TalentPoolOut,
    TalentProfileOut,
    TalentProfileUpdate,
    TalentSkillCreate,
    TalentSkillDecision,
    TalentSkillOut,
)
from app.services import effective_dating as ed
from app.services import performance as perf_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["succession"])

_OBJECT = "talent"
_BOX_KEYS = set(perf_service.TRAINING_RECOMMENDATIONS.keys())
_VISIBLE_TO_MANAGER = ("seleksi", "diterima", "ditolak")


# ------------------------------------------------------------------ Helper
def _tenant_row(db: Session, user: User, model, row_id: uuid.UUID,
                label: str):
    row = db.get(model, row_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{label} tidak ditemukan")
    return row


def _employment(db: Session, user: User,
                employment_id: uuid.UUID) -> Employment:
    return _tenant_row(db, user, Employment, employment_id, "Employment")


def _person_name(db: Session, employment: Employment) -> str:
    person = db.get(Person, employment.person_id)
    return person.full_name if person is not None else "?"


def _audit(db: Session, user: User, request: Request, action: str,
           object_type: str, obj, new: dict | None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type=object_type,
                object_id=getattr(obj, "id", None),
                old_values=None, new_values=new, reason=None,
                channel="api", ip=client_ip(request))


def _require_hr(db: Session, user: User) -> None:
    if user.is_superadmin or rbp_service.is_hr(db, user):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        "Khusus HR (perencanaan suksesi & talent)")


def _view_scope(db: Session, user: User, employment: Employment) -> None:
    """Baca data employment lain: 404 bila tak berhak."""
    if user.is_superadmin:
        return
    own = population_service.get_user_employment(db, user)
    if own is not None and str(own.id) == str(employment.id):
        return
    if (rbp_service.has_permission(db, user, _OBJECT, "view")
            and population_service.can_view_person(
                db, user, employment.person_id)):
        return
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Data tidak ditemukan")


def _mutate_scope(db: Session, user: User, employment: Employment) -> None:
    """Mutasi data employment: diri sendiri bebas; orang lain butuh
    izin correct + masuk target population; selain itu 403."""
    if user.is_superadmin:
        return
    own = population_service.get_user_employment(db, user)
    if own is not None and str(own.id) == str(employment.id):
        return
    if (rbp_service.has_permission(db, user, _OBJECT, "correct")
            and population_service.can_view_person(
                db, user, employment.person_id)):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")


def _job_title(db: Session, job_id) -> str | None:
    if job_id is None:
        return None
    job = db.get(Job, job_id)
    return job.title if job is not None else None


def _current_job_info(db: Session, user: User,
                      employment_id: uuid.UUID) -> JobInfo | None:
    return ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                    identity_field="employment_id",
                    identity_value=employment_id, as_of_date=date.today())


def _org_unit_name(db: Session, user: User, org_unit_id) -> str | None:
    if org_unit_id is None:
        return None
    info = ed.as_of(db=db, tenant_id=user.tenant_id, model=OrgUnitInfo,
                    identity_field="org_unit_id", identity_value=org_unit_id,
                    as_of_date=date.today())
    return info.name if info is not None else None


# ---------------------------------------------------------------- Kandidat
@router.get("/talent/candidates", response_model=list[TalentCandidateOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_candidates(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Employment aktif dengan nama ter-resolve di server.

    Halaman Suksesi sebelumnya mengambil nama dari /persons, yang
    untuk non-HR dibatasi RBAC sehingga dropdown profil kosong.
    Pola yang sama dengan /kudos/candidates: hanya nama, dibatasi
    populasi yang boleh dilihat pemanggil.
    """
    visible = population_service.get_visible_person_ids(db, user)
    stmt = select(Employment).where(
        Employment.tenant_id == user.tenant_id,
        Employment.status == "active")
    if visible is not None:
        stmt = stmt.where(Employment.person_id.in_(visible))
    out = [TalentCandidateOut(employment_id=e.id, person_id=e.person_id,
                              person_name=_person_name(db, e))
           for e in db.execute(stmt).scalars().all()]
    out.sort(key=lambda c: c.person_name)
    return out


# ------------------------------------------------------------------- Skill
@router.get("/talent/skills", response_model=list[TalentSkillOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_skills(status_filter: str | None = Query(default=None,
                                                  alias="status"),
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    stmt = select(Skill).where(Skill.tenant_id == user.tenant_id)
    if status_filter:
        stmt = stmt.where(Skill.status == status_filter)
    return db.execute(stmt.order_by(Skill.name)).scalars().all()


@router.post("/talent/skills", response_model=TalentSkillOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def propose_skill(body: TalentSkillCreate, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    existing = db.execute(
        select(Skill).where(Skill.tenant_id == user.tenant_id,
                            Skill.name == body.name)).scalars().first()
    if existing is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Skill '{body.name}' sudah ada di katalog")
    # Governance SUC-006: usulan karyawan menunggu persetujuan HR;
    # skill yang dibuat HR langsung disetujui.
    is_hr = user.is_superadmin or rbp_service.is_hr(db, user)
    skill = Skill(tenant_id=user.tenant_id, name=body.name,
                  category=body.category,
                  status="disetujui" if is_hr else "usulan",
                  proposed_by_user_id=user.id,
                  decided_by_user_id=user.id if is_hr else None)
    db.add(skill)
    db.flush()
    _audit(db, user, request, "create", "skill", skill,
           {"name": skill.name, "status": skill.status})
    db.commit()
    return skill


@router.post("/talent/skills/{skill_id}/decision",
             response_model=TalentSkillOut,
             dependencies=[Depends(require_permission(_OBJECT, "correct"))])
def decide_skill(skill_id: uuid.UUID, body: TalentSkillDecision,
                 request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _require_hr(db, user)
    skill = _tenant_row(db, user, Skill, skill_id, "Skill")
    if skill.status != "usulan":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Skill ini sudah diputuskan")
    skill.status = "disetujui" if body.decision == "setujui" else "ditolak"
    skill.decided_by_user_id = user.id
    db.flush()
    _audit(db, user, request, "update", "skill", skill,
           {"status": skill.status})
    db.commit()
    return skill


@router.post("/talent/employments/{employment_id}/skills",
             response_model=PersonSkillOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def add_person_skill(employment_id: uuid.UUID, body: PersonSkillCreate,
                     request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    emp = _employment(db, user, employment_id)
    _mutate_scope(db, user, emp)
    if (body.skill_id is None) == (body.skill_name is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Isi tepat satu: skill_id atau skill_name")
    if body.skill_id is not None:
        skill = _tenant_row(db, user, Skill, body.skill_id, "Skill")
    else:
        skill = db.execute(
            select(Skill).where(Skill.tenant_id == user.tenant_id,
                                Skill.name == body.skill_name)
        ).scalars().first()
        if skill is None:
            is_hr = user.is_superadmin or rbp_service.is_hr(db, user)
            skill = Skill(tenant_id=user.tenant_id, name=body.skill_name,
                          status="disetujui" if is_hr else "usulan",
                          proposed_by_user_id=user.id,
                          decided_by_user_id=user.id if is_hr else None)
            db.add(skill)
            db.flush()
    row = db.execute(
        select(PersonSkill).where(
            PersonSkill.tenant_id == user.tenant_id,
            PersonSkill.employment_id == emp.id,
            PersonSkill.skill_id == skill.id)).scalars().first()
    if row is None:
        row = PersonSkill(tenant_id=user.tenant_id, employment_id=emp.id,
                          skill_id=skill.id,
                          proficiency=body.proficiency)
        db.add(row)
    else:
        row.proficiency = body.proficiency
    db.flush()
    _audit(db, user, request, "create", "person_skill", row,
           {"skill": skill.name, "proficiency": row.proficiency})
    db.commit()
    return PersonSkillOut(skill_id=skill.id, skill_name=skill.name,
                          category=skill.category,
                          proficiency=row.proficiency,
                          skill_status=skill.status)


# ------------------------------------------------------------------ Profil
@router.get("/talent/employments/{employment_id}/profile",
            response_model=TalentProfileOut,
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def get_talent_profile(employment_id: uuid.UUID,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    emp = _employment(db, user, employment_id)
    _view_scope(db, user, emp)
    return _profile_out(db, user, emp)


def _profile_out(db: Session, user: User, emp: Employment) -> TalentProfileOut:
    profile = db.execute(
        select(TalentProfile).where(
            TalentProfile.tenant_id == user.tenant_id,
            TalentProfile.employment_id == emp.id)).scalars().first()
    skills: list[PersonSkillOut] = []
    pending: list[PersonSkillOut] = []
    rows = db.execute(
        select(PersonSkill, Skill)
        .join(Skill, Skill.id == PersonSkill.skill_id)
        .where(PersonSkill.tenant_id == user.tenant_id,
               PersonSkill.employment_id == emp.id)
        .order_by(Skill.name)).all()
    for ps, skill in rows:
        out = PersonSkillOut(skill_id=skill.id, skill_name=skill.name,
                             category=skill.category,
                             proficiency=ps.proficiency,
                             skill_status=skill.status)
        (skills if skill.status == "disetujui" else pending).append(out)
    certs: list[TalentCertificationOut] = []
    enrollments = db.execute(
        select(TrainingEnrollment)
        .where(TrainingEnrollment.tenant_id == user.tenant_id,
               TrainingEnrollment.employment_id == emp.id,
               TrainingEnrollment.status == "completed")
        .order_by(TrainingEnrollment.completed_at.desc())).scalars().all()
    for enr in enrollments:
        course = db.get(TrainingCourse, enr.course_id)
        certs.append(TalentCertificationOut(
            course_name=course.name if course else "?",
            completed_at=enr.completed_at,
            cert_expires_at=enr.cert_expires_at,
            certificate_document_id=enr.certificate_document_id))
    latest_box_key = latest_box_label = None
    appraisal = db.execute(
        select(Appraisal)
        .where(Appraisal.tenant_id == user.tenant_id,
               Appraisal.employment_id == emp.id,
               Appraisal.final_score.is_not(None),
               Appraisal.potential_score.is_not(None))
        .order_by(Appraisal.created_at.desc())).scalars().first()
    if appraisal is not None:
        box = perf_service.appraisal_box(db, appraisal)
        if box is not None:
            latest_box_key = box["box_key"]
            latest_box_label = box["label_id"]
    info = _current_job_info(db, user, emp.id)
    return TalentProfileOut(
        employment_id=emp.id, person_name=_person_name(db, emp),
        job_title=_job_title(db, info.job_id) if info else None,
        org_unit_name=_org_unit_name(db, user, info.org_unit_id)
        if info else None,
        mobility_preference=(profile.mobility_preference if profile
                             else "tidak_terbuka"),
        career_aspiration=profile.career_aspiration if profile else None,
        skills=skills, pending_skills=pending, certifications=certs,
        latest_box_key=latest_box_key, latest_box_label=latest_box_label)


@router.put("/talent/employments/{employment_id}/profile",
            response_model=TalentProfileOut,
            dependencies=[Depends(require_permission(_OBJECT, "correct"))])
def update_talent_profile(employment_id: uuid.UUID,
                          body: TalentProfileUpdate, request: Request,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    emp = _employment(db, user, employment_id)
    _mutate_scope(db, user, emp)
    profile = db.execute(
        select(TalentProfile).where(
            TalentProfile.tenant_id == user.tenant_id,
            TalentProfile.employment_id == emp.id)).scalars().first()
    if profile is None:
        profile = TalentProfile(tenant_id=user.tenant_id,
                                employment_id=emp.id)
        db.add(profile)
    profile.mobility_preference = body.mobility_preference
    profile.career_aspiration = body.career_aspiration
    db.flush()
    out = _profile_out(db, user, emp)
    _audit(db, user, request, "update", "talent_profile", profile,
           {"mobility_preference": profile.mobility_preference})
    db.commit()
    return out


# ------------------------------------------------------- Posisi kunci (SUC-002)
def _key_position_out(db: Session, user: User,
                      position: Position) -> KeyPositionOut:
    job = db.get(Job, position.job_id)
    nominations: list[SuccessionNominationOut] = []
    rows = db.execute(
        select(SuccessionNomination).where(
            SuccessionNomination.tenant_id == user.tenant_id,
            SuccessionNomination.position_id == position.id)
        .order_by(SuccessionNomination.created_at)).scalars().all()
    for nom in rows:
        emp = db.get(Employment, nom.employment_id)
        nominations.append(SuccessionNominationOut(
            id=nom.id, employment_id=nom.employment_id,
            person_name=_person_name(db, emp) if emp else "?",
            readiness=nom.readiness, notes=nom.notes,
            created_at=nom.created_at))
    return KeyPositionOut(
        position_id=position.id, position_name=position.name,
        job_title=job.title if job else None,
        org_unit_name=_org_unit_name(db, user, position.org_unit_id),
        nominations=nominations,
        has_ready_successor=any(n.readiness == "siap_sekarang"
                                for n in rows))


@router.get("/talent/key-positions", response_model=list[KeyPositionOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_key_positions(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _require_hr(db, user)
    positions = db.execute(
        select(Position).where(Position.tenant_id == user.tenant_id,
                               Position.is_key.is_(True))
        .order_by(Position.name)).scalars().all()
    return [_key_position_out(db, user, p) for p in positions]


@router.get("/talent/key-positions/gaps",
            response_model=list[KeyPositionOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_succession_gaps(user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Posisi kunci TANPA suksesor siap sekarang — wajib ditandai (PRD)."""
    return [kp for kp in list_key_positions(user=user, db=db)
            if not kp.has_ready_successor]


@router.patch("/talent/positions/{position_id}/key",
              response_model=KeyPositionOut,
              dependencies=[Depends(require_permission(_OBJECT, "correct"))])
def flag_key_position(position_id: uuid.UUID,
                      body: KeyPositionFlagUpdate, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _require_hr(db, user)
    position = _tenant_row(db, user, Position, position_id, "Posisi")
    position.is_key = body.is_key
    db.flush()
    out = _key_position_out(db, user, position)
    _audit(db, user, request, "update", "position", position,
           {"is_key": position.is_key})
    db.commit()
    return out


@router.post("/talent/positions/{position_id}/nominations",
             response_model=SuccessionNominationOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def nominate_successor(position_id: uuid.UUID,
                       body: SuccessionNominationCreate, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _require_hr(db, user)
    position = _tenant_row(db, user, Position, position_id, "Posisi")
    if not position.is_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Nominasi hanya untuk posisi kunci")
    emp = _employment(db, user, body.employment_id)
    dup = db.execute(
        select(SuccessionNomination).where(
            SuccessionNomination.tenant_id == user.tenant_id,
            SuccessionNomination.position_id == position.id,
            SuccessionNomination.employment_id == emp.id)
    ).scalars().first()
    if dup is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Karyawan ini sudah dinominasikan untuk "
                            "posisi tersebut")
    nom = SuccessionNomination(
        tenant_id=user.tenant_id, position_id=position.id,
        employment_id=emp.id, readiness=body.readiness, notes=body.notes,
        nominated_by_user_id=user.id)
    db.add(nom)
    db.flush()
    _audit(db, user, request, "create", "succession_nomination", nom,
           {"position_id": str(position.id), "readiness": nom.readiness})
    db.commit()
    return SuccessionNominationOut(
        id=nom.id, employment_id=nom.employment_id,
        person_name=_person_name(db, emp), readiness=nom.readiness,
        notes=nom.notes, created_at=nom.created_at)


@router.delete("/talent/nominations/{nomination_id}",
               status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission(_OBJECT, "delete"))])
def delete_nomination(nomination_id: uuid.UUID, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _require_hr(db, user)
    nom = _tenant_row(db, user, SuccessionNomination, nomination_id,
                      "Nominasi")
    _audit(db, user, request, "delete", "succession_nomination", nom, None)
    db.delete(nom)
    db.commit()
    return None


# ------------------------------------------------------------ Pool (SUC-003)
@router.post("/talent/pools", response_model=TalentPoolOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def create_talent_pool(body: TalentPoolCreate, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _require_hr(db, user)
    cycle = _tenant_row(db, user, ReviewCycle, body.cycle_id,
                        "Siklus penilaian")
    invalid = [k for k in body.box_keys if k not in _BOX_KEYS]
    if invalid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Kunci kotak tidak dikenal: {invalid}")
    pool = TalentPool(tenant_id=user.tenant_id, name=body.name,
                      cycle_id=cycle.id, box_keys=body.box_keys,
                      created_by_user_id=user.id)
    db.add(pool)
    db.flush()
    policy = perf_service.get_policy(db, user.tenant_id)
    apprs = db.execute(
        select(Appraisal).where(
            Appraisal.tenant_id == user.tenant_id,
            Appraisal.cycle_id == cycle.id,
            Appraisal.final_score.is_not(None),
            Appraisal.potential_score.is_not(None))).scalars().all()
    members: list[TalentPoolMemberOut] = []
    for appr in apprs:
        box = perf_service.nine_box(appr.final_score,
                                    appr.potential_score, policy)
        if box["box_key"] not in body.box_keys:
            continue
        member = TalentPoolMember(tenant_id=user.tenant_id, pool_id=pool.id,
                                  employment_id=appr.employment_id,
                                  box_key=box["box_key"])
        db.add(member)
        emp = db.get(Employment, appr.employment_id)
        members.append(TalentPoolMemberOut(
            employment_id=appr.employment_id,
            person_name=_person_name(db, emp) if emp else "?",
            box_key=box["box_key"]))
    db.flush()
    _audit(db, user, request, "create", "talent_pool", pool,
           {"name": pool.name, "members": len(members)})
    db.commit()
    members.sort(key=lambda m: m.person_name)
    return TalentPoolOut(id=pool.id, name=pool.name, cycle_id=pool.cycle_id,
                         box_keys=pool.box_keys, members=members,
                         created_at=pool.created_at)


@router.get("/talent/pools", response_model=list[TalentPoolOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_talent_pools(user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    _require_hr(db, user)
    pools = db.execute(
        select(TalentPool).where(TalentPool.tenant_id == user.tenant_id)
        .order_by(TalentPool.created_at.desc())).scalars().all()
    result: list[TalentPoolOut] = []
    for pool in pools:
        rows = db.execute(
            select(TalentPoolMember).where(
                TalentPoolMember.tenant_id == user.tenant_id,
                TalentPoolMember.pool_id == pool.id)).scalars().all()
        members = []
        for m in rows:
            emp = db.get(Employment, m.employment_id)
            members.append(TalentPoolMemberOut(
                employment_id=m.employment_id,
                person_name=_person_name(db, emp) if emp else "?",
                box_key=m.box_key))
        members.sort(key=lambda m: m.person_name)
        result.append(TalentPoolOut(
            id=pool.id, name=pool.name, cycle_id=pool.cycle_id,
            box_keys=pool.box_keys, members=members,
            created_at=pool.created_at))
    return result


# ---------------------------------------------- Jalur karier & IDP (SUC-004)
@router.get("/talent/career-paths", response_model=list[CareerPathOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_career_paths(user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    rows = db.execute(
        select(CareerPath).where(CareerPath.tenant_id == user.tenant_id)
        .order_by(CareerPath.created_at)).scalars().all()
    return [CareerPathOut(
        id=r.id, from_job_id=r.from_job_id,
        from_job_title=_job_title(db, r.from_job_id),
        to_job_id=r.to_job_id, to_job_title=_job_title(db, r.to_job_id),
        notes=r.notes) for r in rows]


@router.post("/talent/career-paths", response_model=CareerPathOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def create_career_path(body: CareerPathCreate, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    _require_hr(db, user)
    if str(body.from_job_id) == str(body.to_job_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Jabatan asal dan tujuan tidak boleh sama")
    _tenant_row(db, user, Job, body.from_job_id, "Jabatan asal")
    _tenant_row(db, user, Job, body.to_job_id, "Jabatan tujuan")
    dup = db.execute(
        select(CareerPath).where(
            CareerPath.tenant_id == user.tenant_id,
            CareerPath.from_job_id == body.from_job_id,
            CareerPath.to_job_id == body.to_job_id)).scalars().first()
    if dup is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Jalur karier ini sudah ada")
    row = CareerPath(tenant_id=user.tenant_id,
                     from_job_id=body.from_job_id, to_job_id=body.to_job_id,
                     notes=body.notes)
    db.add(row)
    db.flush()
    _audit(db, user, request, "create", "career_path", row,
           {"from": str(row.from_job_id), "to": str(row.to_job_id)})
    db.commit()
    return CareerPathOut(
        id=row.id, from_job_id=row.from_job_id,
        from_job_title=_job_title(db, row.from_job_id),
        to_job_id=row.to_job_id, to_job_title=_job_title(db, row.to_job_id),
        notes=row.notes)


def _idp_out(db: Session, idp: Idp) -> IdpOut:
    emp = db.get(Employment, idp.employment_id)
    items: list[IdpItemOut] = []
    rows = db.execute(
        select(IdpItem).where(IdpItem.tenant_id == idp.tenant_id,
                              IdpItem.idp_id == idp.id)
        .order_by(IdpItem.created_at)).scalars().all()
    for item in rows:
        course = (db.get(TrainingCourse, item.course_id)
                  if item.course_id else None)
        items.append(IdpItemOut(
            id=item.id, title=item.title, course_id=item.course_id,
            course_name=course.name if course else None,
            target_date=item.target_date, status=item.status,
            notes=item.notes))
    return IdpOut(
        id=idp.id, employment_id=idp.employment_id,
        person_name=_person_name(db, emp) if emp else "?",
        target_job_id=idp.target_job_id,
        target_job_title=_job_title(db, idp.target_job_id),
        year=idp.year, status=idp.status, items=items)


@router.post("/talent/idps", response_model=IdpOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def create_idp(body: IdpCreate, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    emp = _employment(db, user, body.employment_id)
    _mutate_scope(db, user, emp)
    if body.target_job_id is not None:
        _tenant_row(db, user, Job, body.target_job_id, "Jabatan tujuan")
    dup = db.execute(
        select(Idp).where(Idp.tenant_id == user.tenant_id,
                          Idp.employment_id == emp.id,
                          Idp.year == body.year)).scalars().first()
    if dup is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"IDP tahun {body.year} sudah ada untuk "
                            "karyawan ini")
    idp = Idp(tenant_id=user.tenant_id, employment_id=emp.id,
              target_job_id=body.target_job_id, year=body.year)
    db.add(idp)
    db.flush()
    out = _idp_out(db, idp)
    _audit(db, user, request, "create", "idp", idp, {"year": idp.year})
    db.commit()
    return out


@router.get("/talent/employments/{employment_id}/idps",
            response_model=list[IdpOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_idps(employment_id: uuid.UUID,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    emp = _employment(db, user, employment_id)
    _view_scope(db, user, emp)
    rows = db.execute(
        select(Idp).where(Idp.tenant_id == user.tenant_id,
                          Idp.employment_id == emp.id)
        .order_by(Idp.year.desc())).scalars().all()
    return [_idp_out(db, r) for r in rows]


@router.post("/talent/idps/{idp_id}/items", response_model=IdpItemOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def add_idp_item(idp_id: uuid.UUID, body: IdpItemCreate, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    idp = _tenant_row(db, user, Idp, idp_id, "IDP")
    emp = _employment(db, user, idp.employment_id)
    _mutate_scope(db, user, emp)
    course = None
    if body.course_id is not None:
        course = _tenant_row(db, user, TrainingCourse, body.course_id,
                             "Kursus")
    item = IdpItem(tenant_id=user.tenant_id, idp_id=idp.id,
                   title=body.title, course_id=body.course_id,
                   target_date=body.target_date, notes=body.notes)
    db.add(item)
    db.flush()
    _audit(db, user, request, "create", "idp_item", item,
           {"title": item.title})
    db.commit()
    return IdpItemOut(id=item.id, title=item.title,
                      course_id=item.course_id,
                      course_name=course.name if course else None,
                      target_date=item.target_date, status=item.status,
                      notes=item.notes)


@router.patch("/talent/idp-items/{item_id}", response_model=IdpItemOut,
              dependencies=[Depends(require_permission(_OBJECT, "correct"))])
def update_idp_item(item_id: uuid.UUID, body: IdpItemUpdate,
                    request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    item = _tenant_row(db, user, IdpItem, item_id, "Item IDP")
    idp = _tenant_row(db, user, Idp, item.idp_id, "IDP")
    emp = _employment(db, user, idp.employment_id)
    _mutate_scope(db, user, emp)
    item.status = body.status
    db.flush()
    _audit(db, user, request, "update", "idp_item", item,
           {"status": item.status})
    db.commit()
    course = (db.get(TrainingCourse, item.course_id)
              if item.course_id else None)
    return IdpItemOut(id=item.id, title=item.title,
                      course_id=item.course_id,
                      course_name=course.name if course else None,
                      target_date=item.target_date, status=item.status,
                      notes=item.notes)


# ------------------------------------------------- Marketplace (SUC-005)
@router.get("/talent/opportunities",
            response_model=list[InternalOpportunityOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_opportunities(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    stmt = select(InternalOpportunity).where(
        InternalOpportunity.tenant_id == user.tenant_id)
    if not (user.is_superadmin or rbp_service.is_hr(db, user)):
        stmt = stmt.where(InternalOpportunity.status == "terbuka")
    return db.execute(
        stmt.order_by(InternalOpportunity.created_at.desc())
    ).scalars().all()


@router.post("/talent/opportunities",
             response_model=InternalOpportunityOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def create_opportunity(body: InternalOpportunityCreate, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    opp = InternalOpportunity(
        tenant_id=user.tenant_id, kind=body.kind, title=body.title,
        description=body.description, org_unit_id=body.org_unit_id,
        created_by_user_id=user.id)
    db.add(opp)
    db.flush()
    _audit(db, user, request, "create", "internal_opportunity", opp,
           {"kind": opp.kind, "title": opp.title})
    db.commit()
    return opp


@router.post("/talent/opportunities/{opportunity_id}/close",
             response_model=InternalOpportunityOut,
             dependencies=[Depends(require_permission(_OBJECT, "correct"))])
def close_opportunity(opportunity_id: uuid.UUID, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    opp = _tenant_row(db, user, InternalOpportunity, opportunity_id,
                      "Peluang internal")
    if not (user.is_superadmin or rbp_service.is_hr(db, user)
            or str(opp.created_by_user_id) == str(user.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR atau pembuat peluang yang dapat "
                            "menutupnya")
    opp.status = "ditutup"
    db.flush()
    _audit(db, user, request, "update", "internal_opportunity", opp,
           {"status": opp.status})
    db.commit()
    return opp


@router.post("/talent/opportunities/{opportunity_id}/apply",
             response_model=InternalApplicationOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(_OBJECT, "insert"))])
def apply_opportunity(opportunity_id: uuid.UUID,
                      body: InternalApplicationCreate, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    opp = _tenant_row(db, user, InternalOpportunity, opportunity_id,
                      "Peluang internal")
    own = population_service.get_user_employment(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya karyawan yang dapat melamar peluang "
                            "internal")
    if opp.status != "terbuka":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Peluang ini sudah ditutup")
    dup = db.execute(
        select(InternalApplication).where(
            InternalApplication.tenant_id == user.tenant_id,
            InternalApplication.opportunity_id == opp.id,
            InternalApplication.employment_id == own.id)).scalars().first()
    if dup is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Anda sudah melamar peluang ini")
    app_row = InternalApplication(
        tenant_id=user.tenant_id, opportunity_id=opp.id,
        employment_id=own.id, cover_note=body.cover_note)
    db.add(app_row)
    db.flush()
    _audit(db, user, request, "create", "internal_application", app_row,
           {"opportunity_id": str(opp.id)})
    db.commit()
    return InternalApplicationOut(
        id=app_row.id, opportunity_id=app_row.opportunity_id,
        employment_id=app_row.employment_id,
        person_name=_person_name(db, own), status=app_row.status,
        cover_note=app_row.cover_note, created_at=app_row.created_at)


@router.get("/talent/applications/mine",
            response_model=list[InternalApplicationOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def my_applications(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    own = population_service.get_user_employment(db, user)
    if own is None:
        return []
    rows = db.execute(
        select(InternalApplication).where(
            InternalApplication.tenant_id == user.tenant_id,
            InternalApplication.employment_id == own.id)
        .order_by(InternalApplication.created_at.desc())).scalars().all()
    return [InternalApplicationOut(
        id=r.id, opportunity_id=r.opportunity_id,
        employment_id=r.employment_id, person_name=_person_name(db, own),
        status=r.status, cover_note=r.cover_note, created_at=r.created_at)
        for r in rows]


@router.get("/talent/opportunities/{opportunity_id}/applications",
            response_model=list[InternalApplicationOut],
            dependencies=[Depends(require_permission(_OBJECT, "view"))])
def list_opportunity_applications(opportunity_id: uuid.UUID,
                                  user: User = Depends(get_current_user),
                                  db: Session = Depends(get_db)):
    opp = _tenant_row(db, user, InternalOpportunity, opportunity_id,
                      "Peluang internal")
    rows = db.execute(
        select(InternalApplication).where(
            InternalApplication.tenant_id == user.tenant_id,
            InternalApplication.opportunity_id == opp.id)
        .order_by(InternalApplication.created_at)).scalars().all()
    is_hr = user.is_superadmin or rbp_service.is_hr(db, user)
    is_creator = str(opp.created_by_user_id) == str(user.id)
    own = population_service.get_user_employment(db, user)
    result: list[InternalApplicationOut] = []
    for r in rows:
        emp = db.get(Employment, r.employment_id)
        if emp is None:
            continue
        visible = is_hr or is_creator
        if not visible and own is not None and str(own.id) == str(emp.id):
            visible = True  # lamaran sendiri selalu terlihat
        if not visible:
            # Privasi SUC-005: atasan pelamar hanya melihat lamaran yang
            # sudah masuk tahap seleksi atau sesudahnya.
            visible = (
                r.status in _VISIBLE_TO_MANAGER
                and population_service.can_view_person(
                    db, user, emp.person_id))
        if not visible:
            continue
        result.append(InternalApplicationOut(
            id=r.id, opportunity_id=r.opportunity_id,
            employment_id=r.employment_id,
            person_name=_person_name(db, emp), status=r.status,
            cover_note=r.cover_note, created_at=r.created_at))
    return result


@router.post("/talent/applications/{application_id}/decision",
             response_model=InternalApplicationOut,
             dependencies=[Depends(require_permission(_OBJECT, "correct"))])
def decide_application(application_id: uuid.UUID,
                       body: InternalApplicationDecision, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    app_row = _tenant_row(db, user, InternalApplication, application_id,
                          "Lamaran internal")
    opp = _tenant_row(db, user, InternalOpportunity,
                      app_row.opportunity_id, "Peluang internal")
    if not (user.is_superadmin or rbp_service.is_hr(db, user)
            or str(opp.created_by_user_id) == str(user.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR atau pembuat peluang yang dapat "
                            "memutuskan lamaran")
    if app_row.status in ("diterima", "ditolak"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Lamaran ini sudah diputuskan final")
    if app_row.status == "diajukan" and body.status == "diterima":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Lamaran harus melalui tahap seleksi dulu")
    app_row.status = body.status
    app_row.decided_by_user_id = user.id
    db.flush()
    _audit(db, user, request, "update", "internal_application", app_row,
           {"status": app_row.status})
    db.commit()
    emp = db.get(Employment, app_row.employment_id)
    return InternalApplicationOut(
        id=app_row.id, opportunity_id=app_row.opportunity_id,
        employment_id=app_row.employment_id,
        person_name=_person_name(db, emp) if emp else "?",
        status=app_row.status, cover_note=app_row.cover_note,
        created_at=app_row.created_at)
