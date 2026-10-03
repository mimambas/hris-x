"""Engagement & layanan HR (PRD 13.3).

EXP-020 pengumuman bertarget + tanda baca; EXP-021 survei pulse/eNPS
anonim (hash HMAC satu arah — suara ganda dicegah tanpa menyimpan
identitas; hasil hanya untuk >= 5 responden); EXP-022 kudos
antarkaryawan; EXP-023 helpdesk HR (tiket + SLA sederhana + basis
pengetahuan; defleksi asisten AI ditunda mengikuti pola tanpa-AI).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.config import get_secret_key
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Announcement,
    AnnouncementRead,
    Employment,
    HelpdeskMessage,
    HelpdeskTicket,
    JobInfo,
    KbArticle,
    Kudos,
    OrgUnitInfo,
    Person,
    Survey,
    SurveyResponse,
    User,
)
from app.schemas.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementReaderOut,
    KbArticleCreate,
    KbArticleOut,
    KudosCreate,
    KudosCandidateOut,
    KudosOut,
    KudosVisibilityUpdate,
    SurveyAnswerCreate,
    SurveyCreate,
    SurveyOut,
    SurveyResultOut,
    TicketCreate,
    TicketMessageCreate,
    TicketMessageOut,
    TicketOut,
    TicketStatusUpdate,
)
from app.services import effective_dating as ed
from app.services import notify as notify_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit
from app.services.pph21 import validate_ptkp

router = APIRouter(tags=["engagement"])

SLA_HOURS = {"akun": 8, "sistem": 8, "payroll": 24, "cuti": 24,
             "absensi": 24, "dokumen": 48, "lainnya": 48, "fasilitas": 72}
MIN_RESPONDENTS = 5


def _audit(db: Session, user: User, request: Request, action: str,
           object_type: str, obj, new_values: dict | None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type=object_type, object_id=obj.id,
                old_values=None, new_values=new_values, reason=None,
                channel="api", ip=client_ip(request))


def _require_hr(db: Session, user: User) -> None:
    if not (user.is_superadmin or rbp_service.is_hr(db, user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat melakukan ini")


def _own(db: Session, user: User) -> Employment | None:
    return population_service.get_user_employment(db, user)


def _person_name(db: Session, employment_id) -> str | None:
    emp = db.get(Employment, employment_id)
    if emp is None:
        return None
    person = db.get(Person, emp.person_id)
    return person.full_name if person is not None else None


def _my_org_unit_id(db: Session, user: User, emp: Employment):
    info = ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                    identity_field="employment_id",
                    identity_value=emp.id, as_of_date=date.today())
    return info.org_unit_id if info is not None else None


def _org_unit_name(db: Session, user: User, org_unit_id) -> str | None:
    if org_unit_id is None:
        return None
    info = ed.as_of(db=db, tenant_id=user.tenant_id, model=OrgUnitInfo,
                    identity_field="org_unit_id",
                    identity_value=org_unit_id, as_of_date=date.today())
    return info.name if info is not None else None


def _target_employments(db: Session, user: User,
                        ann: Announcement) -> list[Employment]:
    stmt = select(Employment).where(Employment.tenant_id == user.tenant_id,
                                    Employment.status == "active")
    rows = db.execute(stmt).scalars().all()
    if ann.target_type != "org_unit" or ann.target_org_unit_id is None:
        return rows
    out = []
    for emp in rows:
        info = ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                        identity_field="employment_id",
                        identity_value=emp.id, as_of_date=date.today())
        if info is not None and str(info.org_unit_id) == str(
                ann.target_org_unit_id):
            out.append(emp)
    return out


# ------------------------------------------------------------ EXP-020
@router.post("/announcements", response_model=AnnouncementOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("announcement",
                                                      "insert"))])
def create_announcement(body: AnnouncementCreate, request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    _require_hr(db, user)
    if body.target_type == "org_unit" and body.target_org_unit_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "target_org_unit_id wajib untuk target org_unit")
    if body.target_org_unit_id is not None:
        from app.models import OrgUnit
        ou = db.get(OrgUnit, body.target_org_unit_id)
        if ou is None or ou.tenant_id != user.tenant_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Unit organisasi tujuan tidak ditemukan")
    ann = Announcement(tenant_id=user.tenant_id, title=body.title,
                       body=body.body, target_type=body.target_type,
                       target_org_unit_id=body.target_org_unit_id,
                       published_by_user_id=user.id)
    db.add(ann)
    db.flush()
    # EXP-005: notifikasi in-app ke karyawan target (hormati preferensi).
    for emp in _target_employments(db, user, ann):
        target = notify_service.user_for_employment(db, emp.id)
        if target is not None and str(target.id) != str(user.id):
            notify_service.notify(
                db, tenant_id=user.tenant_id, user_id=target.id,
                category="pengumuman", title=f"📢 {ann.title}",
                body=ann.body[:140], link="/keterlibatan")
    out = _announcement_out(db, user, ann)
    _audit(db, user, request, "create", "announcement", ann,
           {"title": ann.title, "target_type": ann.target_type})
    db.commit()
    return out


def _announcement_out(db: Session, user: User,
                      ann: Announcement) -> AnnouncementOut:
    own = _own(db, user)
    read_by_me = False
    if own is not None:
        read_by_me = db.execute(
            select(AnnouncementRead).where(
                AnnouncementRead.tenant_id == user.tenant_id,
                AnnouncementRead.announcement_id == ann.id,
                AnnouncementRead.employment_id == own.id)
        ).scalars().first() is not None
    read_count = db.execute(
        select(func.count()).select_from(AnnouncementRead).where(
            AnnouncementRead.tenant_id == user.tenant_id,
            AnnouncementRead.announcement_id == ann.id)
    ).scalar_one()
    return AnnouncementOut(
        id=ann.id, title=ann.title, body=ann.body,
        target_type=ann.target_type,
        target_org_unit_id=ann.target_org_unit_id,
        org_unit_name=_org_unit_name(db, user, ann.target_org_unit_id),
        published_at=ann.published_at, read_by_me=read_by_me,
        read_count=read_count,
        target_count=len(_target_employments(db, user, ann)))


@router.get("/announcements", response_model=list[AnnouncementOut],
            dependencies=[Depends(require_permission("announcement",
                                                     "view"))])
def list_announcements(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    rows = db.execute(
        select(Announcement).where(Announcement.tenant_id == user.tenant_id)
        .order_by(Announcement.published_at.desc())
    ).scalars().all()
    if user.is_superadmin or rbp_service.is_hr(db, user):
        return [_announcement_out(db, user, a) for a in rows]
    own = _own(db, user)
    if own is None:
        return []
    my_ou = _my_org_unit_id(db, user, own)
    visible = [a for a in rows
               if a.target_type == "semua"
               or (a.target_org_unit_id is not None
                   and str(a.target_org_unit_id) == str(my_ou))]
    return [_announcement_out(db, user, a) for a in visible]


@router.post("/announcements/{announcement_id}/read",
             response_model=AnnouncementOut,
             dependencies=[Depends(require_permission("announcement",
                                                      "view"))])
def mark_announcement_read(announcement_id: uuid.UUID,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    ann = db.get(Announcement, announcement_id)
    if ann is None or ann.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pengumuman tidak ditemukan")
    own = _own(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment")
    existing = db.execute(
        select(AnnouncementRead).where(
            AnnouncementRead.tenant_id == user.tenant_id,
            AnnouncementRead.announcement_id == ann.id,
            AnnouncementRead.employment_id == own.id)
    ).scalars().first()
    if existing is None:
        db.add(AnnouncementRead(tenant_id=user.tenant_id,
                                announcement_id=ann.id,
                                employment_id=own.id))
        db.flush()
    out = _announcement_out(db, user, ann)
    db.commit()
    return out


@router.get("/announcements/{announcement_id}/readers",
            response_model=list[AnnouncementReaderOut],
            dependencies=[Depends(require_permission("announcement",
                                                     "view"))])
def announcement_readers(announcement_id: uuid.UUID,
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    _require_hr(db, user)
    ann = db.get(Announcement, announcement_id)
    if ann is None or ann.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pengumuman tidak ditemukan")
    reads = {
        str(r.employment_id): r.read_at
        for r in db.execute(
            select(AnnouncementRead).where(
                AnnouncementRead.tenant_id == user.tenant_id,
                AnnouncementRead.announcement_id == ann.id)
        ).scalars().all()
    }
    out = []
    for emp in _target_employments(db, user, ann):
        out.append(AnnouncementReaderOut(
            employment_id=emp.id,
            person_name=_person_name(db, emp.id) or "?",
            read_at=reads.get(str(emp.id))))
    out.sort(key=lambda x: (x.read_at is not None, x.person_name))
    return out


# ------------------------------------------------------------ EXP-021
def _respondent_hash(survey_id, employment_id) -> str:
    msg = f"{survey_id}:{employment_id}".encode()
    return hmac.new(get_secret_key().encode(), msg,
                    hashlib.sha256).hexdigest()


@router.post("/surveys", response_model=SurveyOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("survey", "insert"))])
def create_survey(body: SurveyCreate, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _require_hr(db, user)
    survey = Survey(tenant_id=user.tenant_id, kind=body.kind,
                    title=body.title, question=body.question,
                    status="aktif", created_by_user_id=user.id)
    db.add(survey)
    db.flush()
    out = _survey_out(db, user, survey)
    _audit(db, user, request, "create", "survey", survey,
           {"kind": survey.kind, "title": survey.title})
    db.commit()
    return out


def _survey_out(db: Session, user: User, survey: Survey) -> SurveyOut:
    count = db.execute(
        select(func.count()).select_from(SurveyResponse).where(
            SurveyResponse.tenant_id == user.tenant_id,
            SurveyResponse.survey_id == survey.id)
    ).scalar_one()
    own = _own(db, user)
    answered = False
    if own is not None:
        answered = db.execute(
            select(SurveyResponse).where(
                SurveyResponse.tenant_id == user.tenant_id,
                SurveyResponse.survey_id == survey.id,
                SurveyResponse.respondent_hash
                == _respondent_hash(survey.id, own.id))
        ).scalars().first() is not None
    return SurveyOut(id=survey.id, kind=survey.kind, title=survey.title,
                     question=survey.question, status=survey.status,
                     created_at=survey.created_at,
                     answered_by_me=answered, response_count=count)


@router.get("/surveys", response_model=list[SurveyOut],
            dependencies=[Depends(require_permission("survey", "view"))])
def list_surveys(user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    rows = db.execute(
        select(Survey).where(Survey.tenant_id == user.tenant_id)
        .order_by(Survey.created_at.desc())
    ).scalars().all()
    return [_survey_out(db, user, s) for s in rows]


@router.post("/surveys/{survey_id}/answer",
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("survey", "view"))])
def answer_survey(survey_id: uuid.UUID, body: SurveyAnswerCreate,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    survey = db.get(Survey, survey_id)
    if survey is None or survey.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Survei tidak ditemukan")
    if survey.status != "aktif":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Survei sudah ditutup")
    lo, hi = (0, 10) if survey.kind == "enps" else (1, 5)
    if not (lo <= body.score <= hi):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Skor harus {lo}-{hi} untuk survei "
                            f"{survey.kind}")
    own = _own(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment")
    digest = _respondent_hash(survey.id, own.id)
    dup = db.execute(
        select(SurveyResponse).where(
            SurveyResponse.tenant_id == user.tenant_id,
            SurveyResponse.survey_id == survey.id,
            SurveyResponse.respondent_hash == digest)
    ).scalars().first()
    if dup is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Anda sudah menjawab survei ini")
    db.add(SurveyResponse(tenant_id=user.tenant_id, survey_id=survey.id,
                          respondent_hash=digest, score=body.score,
                          comment=body.comment))
    db.commit()
    return {"ok": True, "message": "Terima kasih, jawaban Anda anonim."}


@router.get("/surveys/{survey_id}/results",
            response_model=SurveyResultOut,
            dependencies=[Depends(require_permission("survey", "view"))])
def survey_results(survey_id: uuid.UUID,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _require_hr(db, user)
    survey = db.get(Survey, survey_id)
    if survey is None or survey.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Survei tidak ditemukan")
    rows = db.execute(
        select(SurveyResponse).where(
            SurveyResponse.tenant_id == user.tenant_id,
            SurveyResponse.survey_id == survey.id)
    ).scalars().all()
    count = len(rows)
    if count < MIN_RESPONDENTS:
        return SurveyResultOut(survey_id=survey.id, kind=survey.kind,
                               response_count=count,
                               enough_responses=False)
    dist: dict[str, int] = {}
    for r in rows:
        dist[str(r.score)] = dist.get(str(r.score), 0) + 1
    average = sum(r.score for r in rows) / count
    enps = None
    if survey.kind == "enps":
        promoters = sum(1 for r in rows if r.score >= 9)
        detractors = sum(1 for r in rows if r.score <= 6)
        enps = round((promoters - detractors) / count * 100)
    return SurveyResultOut(survey_id=survey.id, kind=survey.kind,
                           response_count=count, enough_responses=True,
                           average=round(average, 2), enps=enps,
                           distribution=dist)


@router.post("/surveys/{survey_id}/close", response_model=SurveyOut,
             dependencies=[Depends(require_permission("survey",
                                                      "correct"))])
def close_survey(survey_id: uuid.UUID, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    _require_hr(db, user)
    survey = db.get(Survey, survey_id)
    if survey is None or survey.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Survei tidak ditemukan")
    survey.status = "ditutup"
    survey.closed_at = datetime.now(timezone.utc)
    db.flush()
    out = _survey_out(db, user, survey)
    _audit(db, user, request, "close", "survey", survey,
           {"status": "ditutup"})
    db.commit()
    return out


# ------------------------------------------------------------ EXP-022
def _kudos_out(db: Session, row: Kudos) -> KudosOut:
    return KudosOut(
        id=row.id, from_employment_id=row.from_employment_id,
        from_name=_person_name(db, row.from_employment_id),
        to_employment_id=row.to_employment_id,
        to_name=_person_name(db, row.to_employment_id),
        category=row.category, message=row.message,
        visible_on_profile=row.visible_on_profile,
        created_at=row.created_at)


@router.post("/kudos", response_model=KudosOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("kudos", "insert"))])
def give_kudos(body: KudosCreate, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    own = _own(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment")
    if str(body.to_employment_id) == str(own.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tidak bisa memberi kudos ke diri sendiri")
    target = db.get(Employment, body.to_employment_id)
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Karyawan penerima tidak ditemukan")
    row = Kudos(tenant_id=user.tenant_id, from_employment_id=own.id,
                to_employment_id=body.to_employment_id,
                category=body.category, message=body.message)
    db.add(row)
    db.flush()
    notify_service.notify_employment(
        db, tenant_id=user.tenant_id,
        employment_id=body.to_employment_id, category="kudos",
        title=f"🏅 {user.full_name} memberi Anda kudos",
        body=body.message[:140], link="/keterlibatan")
    out = _kudos_out(db, row)
    _audit(db, user, request, "create", "kudos", row,
           {"to_employment_id": str(row.to_employment_id),
            "category": row.category})
    db.commit()
    return out


@router.get("/kudos/candidates", response_model=list[KudosCandidateOut],
            dependencies=[Depends(require_permission("kudos", "view"))])
def kudos_candidates(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Daftar penerima kudos (nama di-resolve server-side).

    Diperlukan karena daftar Person untuk non-HR dibatasi RBAC —
    tanpa endpoint ini dropdown penerima kudos kosong bagi karyawan.
    """
    own = _own(db, user)
    rows = db.execute(
        select(Employment).where(Employment.tenant_id == user.tenant_id,
                                 Employment.status == "active")
    ).scalars().all()
    out = []
    for emp in rows:
        if own is not None and str(emp.id) == str(own.id):
            continue
        name = _person_name(db, emp.id)
        if name is not None:
            out.append(KudosCandidateOut(employment_id=emp.id,
                                         person_name=name))
    out.sort(key=lambda c: c.person_name)
    return out


@router.get("/kudos/feed", response_model=list[KudosOut],
            dependencies=[Depends(require_permission("kudos", "view"))])
def kudos_feed(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    rows = db.execute(
        select(Kudos).where(Kudos.tenant_id == user.tenant_id)
        .order_by(Kudos.created_at.desc()).limit(50)
    ).scalars().all()
    return [_kudos_out(db, r) for r in rows]


@router.get("/kudos/mine", response_model=list[KudosOut],
            dependencies=[Depends(require_permission("kudos", "view"))])
def kudos_mine(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    own = _own(db, user)
    if own is None:
        return []
    rows = db.execute(
        select(Kudos).where(Kudos.tenant_id == user.tenant_id,
                            Kudos.to_employment_id == own.id)
        .order_by(Kudos.created_at.desc())
    ).scalars().all()
    return [_kudos_out(db, r) for r in rows]


@router.get("/kudos/profile/{employment_id}",
            response_model=list[KudosOut],
            dependencies=[Depends(require_permission("kudos", "view"))])
def kudos_profile(employment_id: uuid.UUID,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    rows = db.execute(
        select(Kudos).where(Kudos.tenant_id == user.tenant_id,
                            Kudos.to_employment_id == employment_id,
                            Kudos.visible_on_profile.is_(True))
        .order_by(Kudos.created_at.desc())
    ).scalars().all()
    return [_kudos_out(db, r) for r in rows]


@router.patch("/kudos/{kudos_id}/visibility", response_model=KudosOut,
              dependencies=[Depends(require_permission("kudos",
                                                        "correct"))])
def kudos_visibility(kudos_id: uuid.UUID, body: KudosVisibilityUpdate,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    row = db.get(Kudos, kudos_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kudos tidak ditemukan")
    own = _own(db, user)
    if own is None or str(own.id) != str(row.to_employment_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya penerima yang mengatur visibilitasnya")
    row.visible_on_profile = body.visible_on_profile
    db.flush()
    out = _kudos_out(db, row)
    db.commit()
    return out


# ------------------------------------------------------------ EXP-023
def _ticket_out(db: Session, t: HelpdeskTicket) -> TicketOut:
    count = db.execute(
        select(func.count()).select_from(HelpdeskMessage).where(
            HelpdeskMessage.tenant_id == t.tenant_id,
            HelpdeskMessage.ticket_id == t.id)
    ).scalar_one()
    due = t.sla_due_at
    if due is not None and due.tzinfo is None:
        # SQLite mengembalikan datetime naive; anggap UTC.
        due = due.replace(tzinfo=timezone.utc)
    breached = bool(
        due is not None
        and t.status not in ("selesai", "ditutup")
        and due < datetime.now(timezone.utc))
    return TicketOut(
        id=t.id, requester_employment_id=t.requester_employment_id,
        requester_name=_person_name(db, t.requester_employment_id),
        category=t.category, subject=t.subject,
        description=t.description, status=t.status,
        assignee_user_id=t.assignee_user_id, sla_due_at=t.sla_due_at,
        sla_breached=breached, resolved_at=t.resolved_at,
        created_at=t.created_at, message_count=count)


def _ticket_or_404(db: Session, user: User,
                   ticket_id: uuid.UUID) -> HelpdeskTicket:
    t = db.get(HelpdeskTicket, ticket_id)
    if t is None or t.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tiket tidak ditemukan")
    return t


def _can_access_ticket(db: Session, user: User, t: HelpdeskTicket) -> bool:
    if user.is_superadmin or rbp_service.is_hr(db, user):
        return True
    own = _own(db, user)
    return own is not None and str(own.id) == str(
        t.requester_employment_id)


@router.post("/tickets", response_model=TicketOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("helpdesk",
                                                      "insert"))])
def create_ticket(body: TicketCreate, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    own = _own(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment")
    due = datetime.now(timezone.utc) + timedelta(
        hours=SLA_HOURS[body.category])
    t = HelpdeskTicket(tenant_id=user.tenant_id,
                       requester_employment_id=own.id,
                       category=body.category, subject=body.subject,
                       description=body.description, status="baru",
                       sla_due_at=due)
    db.add(t)
    db.flush()
    out = _ticket_out(db, t)
    _audit(db, user, request, "create", "helpdesk_ticket", t,
           {"category": t.category, "subject": t.subject})
    db.commit()
    return out


@router.get("/tickets/mine", response_model=list[TicketOut],
            dependencies=[Depends(require_permission("helpdesk", "view"))])
def my_tickets(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    own = _own(db, user)
    if own is None:
        return []
    rows = db.execute(
        select(HelpdeskTicket).where(
            HelpdeskTicket.tenant_id == user.tenant_id,
            HelpdeskTicket.requester_employment_id == own.id)
        .order_by(HelpdeskTicket.created_at.desc())
    ).scalars().all()
    return [_ticket_out(db, t) for t in rows]


@router.get("/tickets", response_model=list[TicketOut],
            dependencies=[Depends(require_permission("helpdesk", "view"))])
def all_tickets(status_filter: str | None = Query(default=None),
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    _require_hr(db, user)
    stmt = select(HelpdeskTicket).where(
        HelpdeskTicket.tenant_id == user.tenant_id)
    if status_filter:
        stmt = stmt.where(HelpdeskTicket.status == status_filter)
    rows = db.execute(
        stmt.order_by(HelpdeskTicket.created_at.desc())).scalars().all()
    return [_ticket_out(db, t) for t in rows]


@router.get("/tickets/{ticket_id}", response_model=TicketOut,
            dependencies=[Depends(require_permission("helpdesk", "view"))])
def ticket_detail(ticket_id: uuid.UUID,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    t = _ticket_or_404(db, user, ticket_id)
    if not _can_access_ticket(db, user, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tiket tidak ditemukan")
    return _ticket_out(db, t)


@router.get("/tickets/{ticket_id}/messages",
            response_model=list[TicketMessageOut],
            dependencies=[Depends(require_permission("helpdesk", "view"))])
def ticket_messages(ticket_id: uuid.UUID,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    t = _ticket_or_404(db, user, ticket_id)
    if not _can_access_ticket(db, user, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tiket tidak ditemukan")
    rows = db.execute(
        select(HelpdeskMessage).where(
            HelpdeskMessage.tenant_id == user.tenant_id,
            HelpdeskMessage.ticket_id == t.id)
        .order_by(HelpdeskMessage.created_at)
    ).scalars().all()
    return rows


@router.post("/tickets/{ticket_id}/messages",
             response_model=TicketMessageOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("helpdesk", "view"))])
def add_ticket_message(ticket_id: uuid.UUID, body: TicketMessageCreate,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    t = _ticket_or_404(db, user, ticket_id)
    if not _can_access_ticket(db, user, t):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tiket tidak ditemukan")
    if t.status in ("selesai", "ditutup"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tiket sudah ditutup")
    msg = HelpdeskMessage(tenant_id=user.tenant_id, ticket_id=t.id,
                          author_user_id=user.id,
                          author_name=user.full_name, body=body.body)
    db.add(msg)
    if t.status == "baru" and rbp_service.is_hr(db, user):
        t.status = "diproses"
        t.assignee_user_id = user.id
    db.flush()
    # EXP-005: kabari pembuat tiket bila yang membalas bukan dia.
    maker = notify_service.user_for_employment(
        db, t.requester_employment_id)
    if maker is not None and str(maker.id) != str(user.id):
        notify_service.notify(
            db, tenant_id=user.tenant_id, user_id=maker.id,
            category="helpdesk",
            title=f"🎫 Balasan baru pada tiket: {t.subject}",
            body=body.body[:140], link="/keterlibatan")
    db.commit()
    return msg


@router.patch("/tickets/{ticket_id}/status", response_model=TicketOut,
              dependencies=[Depends(require_permission("helpdesk",
                                                        "correct"))])
def update_ticket_status(ticket_id: uuid.UUID, body: TicketStatusUpdate,
                         request: Request,
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    _require_hr(db, user)
    t = _ticket_or_404(db, user, ticket_id)
    old = t.status
    t.status = body.status
    if body.status == "selesai":
        t.resolved_at = datetime.now(timezone.utc)
    db.flush()
    notify_service.notify_employment(
        db, tenant_id=user.tenant_id,
        employment_id=t.requester_employment_id, category="helpdesk",
        title=f"🎫 Status tiket berubah: {t.subject}",
        body=f"Status tiket Anda kini: {body.status}.",
        link="/keterlibatan")
    out = _ticket_out(db, t)
    _audit(db, user, request, "update", "helpdesk_ticket", t,
           {"from": old, "to": body.status})
    db.commit()
    return out


# ------------------------------------------------------- Basis pengetahuan
@router.get("/kb/articles", response_model=list[KbArticleOut],
            dependencies=[Depends(require_permission("helpdesk", "view"))])
def list_kb(q: str | None = Query(default=None),
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    stmt = select(KbArticle).where(KbArticle.tenant_id == user.tenant_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (KbArticle.title.ilike(like)) | (KbArticle.body.ilike(like))
            | (KbArticle.keywords.ilike(like)))
    rows = db.execute(
        stmt.order_by(KbArticle.title)).scalars().all()
    return rows


@router.post("/kb/articles", response_model=KbArticleOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("helpdesk",
                                                      "insert"))])
def create_kb(body: KbArticleCreate, request: Request,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    _require_hr(db, user)
    art = KbArticle(tenant_id=user.tenant_id, category=body.category,
                    title=body.title, body=body.body,
                    keywords=body.keywords, created_by_user_id=user.id)
    db.add(art)
    db.flush()
    _audit(db, user, request, "create", "kb_article", art,
           {"title": art.title, "category": art.category})
    db.commit()
    return art


@router.delete("/kb/articles/{article_id}", status_code=204,
               dependencies=[Depends(require_permission("helpdesk",
                                                        "delete"))])
def delete_kb(article_id: uuid.UUID, request: Request,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    _require_hr(db, user)
    art = db.get(KbArticle, article_id)
    if art is None or art.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Artikel tidak ditemukan")
    _audit(db, user, request, "delete", "kb_article", art,
           {"title": art.title})
    db.delete(art)
    db.commit()
    return None
