"""Rekrutmen (Sprint 6): requisition → lowongan → lamaran → pipeline →
wawancara → e-offer → hire.

- Otorisasi: require_permission(object, action) per modul + batas unit
  kerja untuk hiring manager (lihat _check_req_scope, ADR-0009).
- Setiap transisi stage lamaran tercatat di audit (action="move_stage")
  dengan actor + timestamp + note.
- Endpoint publik (/public/...) TANPA auth: daftar lowongan & accept offer.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Candidate,
    Employment,
    Interview,
    InterviewFeedback,
    Job,
    JobApplication,
    JobInfo,
    JobPosting,
    JobRequisition,
    LegalEntity,
    Location,
    Offer,
    OrgUnit,
    Person,
    Tenant,
    User,
)
from app.schemas.schemas import (
    AcceptOfferCreate,
    AcceptOfferOut,
    ApplicationCreate,
    ApplicationMove,
    ApplicationOut,
    CandidateCreate,
    CandidateOut,
    FeedbackCreate,
    FeedbackOut,
    InterviewCreate,
    InterviewOut,
    JobPostingCreate,
    JobPostingOut,
    OfferCreate,
    OfferDecline,
    OfferOut,
    PublicJobOut,
    RequisitionCreate,
    RequisitionDecision,
    RequisitionOut,
)
from app.services import effective_dating as ed
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit
from app.services.offer_letter import render_offer_letter_pdf

router = APIRouter(tags=["recruitment"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}

# ------------------------------------------------------------------ Pipeline
_FORWARD = {"applied": "screening", "screening": "interview",
            "interview": "offering", "offering": "hired"}
_TERMINAL = ("rejected", "withdrawn", "hired")
_ORDER = ("applied", "screening", "interview", "offering", "hired")


def _check_move(current: str, to: str, note: str | None) -> None:
    """Validasi transisi stage; raise HTTPException 422 bila tidak valid."""
    if current in _TERMINAL:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Lamaran sudah final ('{current}'), tidak bisa dipindah")
    if to == current:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Stage tujuan sama dengan stage saat ini")
    if to in ("rejected", "withdrawn"):
        return  # cabang final dari stage mana pun
    if to == "hired":
        if current != "offering":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Status 'hired' hanya bisa dari stage 'offering'")
        return
    if to not in _ORDER:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Stage '{to}' tidak dikenal")
    if _FORWARD.get(current) == to:
        return  # maju satu langkah: note opsional
    if _ORDER.index(to) < _ORDER.index(current):
        if not (note or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Transisi mundur wajib menyertakan note")
        return
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"Transisi '{current}' → '{to}' tidak valid")


# ------------------------------------------------- Helper unit scope (ADR-0009)
def _user_org_unit_id(db: Session, user: User) -> uuid.UUID | None:
    """Org unit employment user dari job_info yang berlaku hari ini."""
    emp = population_service.get_user_employment(db, user)
    if emp is None:
        return None
    ji = ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                  identity_field="employment_id", identity_value=emp.id,
                  as_of_date=date.today())
    return ji.org_unit_id if ji is not None else None


def _scope_all(db: Session, user: User) -> bool:
    """True = HR-like (tidak dibatasi unit). Hiring manager = punya
    view+correct TAPI tidak punya insert atas requisition → dibatasi unit."""
    if user.is_superadmin:
        return True
    return rbp_service.has_permission(db, user, "requisition", "insert")


def _app_org_unit_id(db: Session, app: JobApplication) -> uuid.UUID | None:
    posting = db.get(JobPosting, app.posting_id)
    if posting is None:
        return None
    req = db.get(JobRequisition, posting.requisition_id)
    return req.org_unit_id if req is not None else None


def _check_req_scope(db: Session, user: User,
                     org_unit_id: uuid.UUID) -> None:
    if _scope_all(db, user):
        return
    own = _user_org_unit_id(db, user)
    if own is None or str(own) != str(org_unit_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya boleh mengelola requisition di unit kerja sendiri")


def _check_app_scope(db: Session, user: User, app: JobApplication) -> None:
    if _scope_all(db, user):
        return
    unit_id = _app_org_unit_id(db, app)
    own = _user_org_unit_id(db, user)
    if unit_id is None or own is None or str(own) != str(unit_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya boleh mengelola lamaran di unit kerja sendiri")


# ------------------------------------------------------------------ Helper get
def _tenant_row(db: Session, user: User, model, row_id: uuid.UUID,
                label: str):
    row = db.get(model, row_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{label} tidak ditemukan")
    return row


def _get_req(db: Session, user: User, req_id: uuid.UUID) -> JobRequisition:
    req = _tenant_row(db, user, JobRequisition, req_id, "Requisition")
    _check_req_scope(db, user, req.org_unit_id)
    return req


def _get_app(db: Session, user: User, app_id: uuid.UUID) -> JobApplication:
    app = _tenant_row(db, user, JobApplication, app_id, "Lamaran")
    _check_app_scope(db, user, app)
    return app


def _public_tenant(db: Session, slug: str) -> Tenant:
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == slug.strip().lower())
    ).scalar_one_or_none()
    if tenant is None or not tenant.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan")
    return tenant


# ================================================================ Requisition
@router.post("/recruitment/requisitions",
             response_model=RequisitionOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("requisition",
                                                       "insert"))])
def create_requisition(body: RequisitionCreate, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    ou = db.get(OrgUnit, body.org_unit_id)
    if ou is None or ou.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Unit organisasi tidak ditemukan")
    req = JobRequisition(tenant_id=user.tenant_id,
                         org_unit_id=body.org_unit_id,
                         job_title=body.job_title.strip(),
                         headcount=body.headcount,
                         reason=(body.reason or "").strip() or None,
                         status="draft",
                         created_by_user_id=user.id)
    db.add(req)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="requisition", object_id=req.id,
                new_values=snapshot(req, ["id", "org_unit_id", "job_title",
                                          "headcount", "status"]),
                reason="Requisition baru", channel="api",
                ip=client_ip(request))
    db.commit()
    return req


@router.get("/recruitment/requisitions",
            response_model=list[RequisitionOut],
            dependencies=[Depends(require_permission("requisition", "view"))])
def list_requisitions(user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    stmt = (select(JobRequisition)
            .where(JobRequisition.tenant_id == user.tenant_id)
            .order_by(JobRequisition.created_at.desc()))
    rows = db.execute(stmt).scalars().all()
    if not _scope_all(db, user):
        own = _user_org_unit_id(db, user)
        rows = [r for r in rows if own is not None
                and str(r.org_unit_id) == str(own)]
    return rows


@router.get("/recruitment/requisitions/{req_id}",
            response_model=RequisitionOut,
            dependencies=[Depends(require_permission("requisition", "view"))])
def get_requisition(req_id: uuid.UUID, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return _get_req(db, user, req_id)


def _transition_requisition(db, user, request, req: JobRequisition,
                            from_status: str, to_status: str,
                            note: str | None, reason: str):
    if req.status != from_status:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Requisition harus berstatus '{from_status}' "
                            f"(saat ini '{req.status}')")
    old = req.status
    req.status = to_status
    req.decided_by_user_id = user.id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = (note or "").strip() or None
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="requisition", object_id=req.id,
                old_values={"status": old}, new_values={"status": to_status},
                reason=reason, channel="api", ip=client_ip(request))


@router.post("/recruitment/requisitions/{req_id}/submit",
             response_model=RequisitionOut,
             dependencies=[Depends(require_permission("requisition",
                                                       "correct"))])
def submit_requisition(req_id: uuid.UUID, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    req = _get_req(db, user, req_id)
    _transition_requisition(db, user, request, req, "draft", "submitted",
                            None, "Requisition diajukan")
    db.commit()
    return req


@router.post("/recruitment/requisitions/{req_id}/approve",
             response_model=RequisitionOut,
             dependencies=[Depends(require_permission("requisition",
                                                       "correct"))])
def approve_requisition(req_id: uuid.UUID, body: RequisitionDecision,
                        request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    req = _get_req(db, user, req_id)
    _transition_requisition(db, user, request, req, "submitted", "approved",
                            body.note, "Requisition disetujui")
    db.commit()
    return req


@router.post("/recruitment/requisitions/{req_id}/reject",
             response_model=RequisitionOut,
             dependencies=[Depends(require_permission("requisition",
                                                       "correct"))])
def reject_requisition(req_id: uuid.UUID, body: RequisitionDecision,
                       request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    req = _get_req(db, user, req_id)
    _transition_requisition(db, user, request, req, "submitted", "rejected",
                            body.note, "Requisition ditolak")
    db.commit()
    return req


# ================================================================ Job posting
@router.post("/recruitment/postings",
             response_model=JobPostingOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("job_posting",
                                                       "insert"))])
def create_posting(body: JobPostingCreate, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    req = db.get(JobRequisition, body.requisition_id)
    if req is None or req.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Requisition tidak ditemukan")
    posting = JobPosting(
        tenant_id=user.tenant_id, requisition_id=req.id,
        title=body.title.strip(),
        description=(body.description or "").strip() or None,
        requirements=(body.requirements or "").strip() or None,
        employment_type=body.employment_type.strip().lower(),
        location=(body.location or "").strip() or None,
        status="draft", created_by_user_id=user.id)
    db.add(posting)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="job_posting",
                object_id=posting.id,
                new_values=snapshot(posting, ["id", "requisition_id", "title",
                                              "status"]),
                reason="Lowongan baru (draft)", channel="api",
                ip=client_ip(request))
    db.commit()
    return posting


@router.post("/recruitment/postings/{posting_id}/publish",
             response_model=JobPostingOut,
             dependencies=[Depends(require_permission("job_posting",
                                                       "correct"))])
def publish_posting(posting_id: uuid.UUID, request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    posting = _tenant_row(db, user, JobPosting, posting_id, "Lowongan")
    if posting.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya lowongan draft yang bisa dipublish")
    req = db.get(JobRequisition, posting.requisition_id)
    if req is None or req.status != "approved":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Lowongan tidak bisa dipublish: requisition belum approved")
    old = posting.status
    posting.status = "published"
    posting.published_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="job_posting",
                object_id=posting.id,
                old_values={"status": old},
                new_values={"status": "published"},
                reason="Lowongan dipublish", channel="api",
                ip=client_ip(request))
    db.commit()
    return posting


@router.post("/recruitment/postings/{posting_id}/close",
             response_model=JobPostingOut,
             dependencies=[Depends(require_permission("job_posting",
                                                       "correct"))])
def close_posting(posting_id: uuid.UUID, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    posting = _tenant_row(db, user, JobPosting, posting_id, "Lowongan")
    if posting.status != "published":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya lowongan published yang bisa ditutup")
    old = posting.status
    posting.status = "closed"
    posting.closed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="job_posting",
                object_id=posting.id,
                old_values={"status": old}, new_values={"status": "closed"},
                reason="Lowongan ditutup", channel="api",
                ip=client_ip(request))
    db.commit()
    return posting


@router.get("/recruitment/postings",
            response_model=list[JobPostingOut],
            dependencies=[Depends(require_permission("job_posting", "view"))])
def list_postings(status_: str | None = Query(default=None,
                                              alias="status"),
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    stmt = (select(JobPosting)
            .where(JobPosting.tenant_id == user.tenant_id)
            .order_by(JobPosting.created_at.desc()))
    if status_ is not None:
        stmt = stmt.where(JobPosting.status == status_.strip().lower())
    return db.execute(stmt).scalars().all()


@router.get("/recruitment/postings/{posting_id}",
            response_model=JobPostingOut,
            dependencies=[Depends(require_permission("job_posting", "view"))])
def get_posting(posting_id: uuid.UUID, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    return _tenant_row(db, user, JobPosting, posting_id, "Lowongan")


# ================================================================ Candidate
@router.post("/recruitment/candidates",
             response_model=CandidateOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("candidate",
                                                       "insert"))])
def create_candidate(body: CandidateCreate, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    exists = db.execute(
        select(Candidate.id).where(Candidate.tenant_id == user.tenant_id,
                                   Candidate.email == body.email)
    ).first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Email '{body.email}' sudah terdaftar sebagai kandidat")
    cand = Candidate(tenant_id=user.tenant_id, name=body.name.strip(),
                     email=body.email, phone=(body.phone or "").strip() or None,
                     source=body.source)
    db.add(cand)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="candidate", object_id=cand.id,
                new_values=snapshot(cand, ["id", "name", "email", "source"]),
                reason="Kandidat baru", channel="api",
                ip=client_ip(request))
    db.commit()
    return cand


@router.get("/recruitment/candidates",
            response_model=list[CandidateOut],
            dependencies=[Depends(require_permission("candidate", "view"))])
def list_candidates(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return db.execute(
        select(Candidate).where(Candidate.tenant_id == user.tenant_id)
        .order_by(Candidate.created_at.desc())
    ).scalars().all()


@router.post("/recruitment/candidates/{candidate_id}/cv",
             response_model=CandidateOut,
             dependencies=[Depends(require_permission("candidate",
                                                       "correct"))])
def upload_cv(candidate_id: uuid.UUID, request: Request,
              file: UploadFile = File(...),
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Upload CV kandidat (internal, multipart). Berkas di backend/uploads/.
    Kandidat bukan person → TIDAK memakai modul documents."""
    cand = _tenant_row(db, user, Candidate, candidate_id, "Kandidat")
    original = (file.filename or "").strip()
    ext = "." + original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Ekstensi '{ext or '?'}' tidak diizinkan "
                            f"({', '.join(sorted(ALLOWED_EXT))})")
    data = file.file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Berkas kosong")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Berkas melebihi batas {MAX_FILE_BYTES // 1024 // 1024} MB")
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", original) or "cv"
    stored = f"cv_{uuid.uuid4().hex}_{safe_name}"
    tenant_dir = UPLOAD_DIR / str(user.tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    (tenant_dir / stored).write_bytes(data)
    old_path = cand.cv_file_path
    cand.cv_file_path = str(Path(str(user.tenant_id)) / stored)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="candidate", object_id=cand.id,
                old_values={"cv_file_path": old_path},
                new_values={"cv_file_path": cand.cv_file_path,
                            "file_name": original},
                reason="Upload CV kandidat", channel="api",
                ip=client_ip(request))
    db.commit()
    return cand


@router.get("/recruitment/candidates/{candidate_id}/cv/download",
            dependencies=[Depends(require_permission("candidate", "view"))])
def download_cv(candidate_id: uuid.UUID, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    cand = _tenant_row(db, user, Candidate, candidate_id, "Kandidat")
    if not cand.cv_file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CV belum diunggah")
    path = UPLOAD_DIR / cand.cv_file_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Berkas tidak ditemukan")
    return FileResponse(path, filename=f"cv_{cand.name}.pdf")


# ================================================================ Application
@router.post("/recruitment/applications",
             response_model=ApplicationOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("job_application",
                                                       "insert"))])
def create_application(body: ApplicationCreate, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    posting = db.get(JobPosting, body.posting_id)
    if posting is None or posting.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Lowongan tidak ditemukan")
    if posting.status != "published":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Lamaran hanya bisa untuk lowongan yang published")
    cand = db.get(Candidate, body.candidate_id)
    if cand is None or cand.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kandidat tidak ditemukan")
    if not _scope_all(db, user):
        req = db.get(JobRequisition, posting.requisition_id)
        if req is not None:
            _check_req_scope(db, user, req.org_unit_id)
    dup = db.execute(
        select(JobApplication.id).where(
            JobApplication.tenant_id == user.tenant_id,
            JobApplication.posting_id == posting.id,
            JobApplication.candidate_id == cand.id)
    ).first()
    if dup:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Kandidat sudah melamar lowongan ini")
    app = JobApplication(tenant_id=user.tenant_id, posting_id=posting.id,
                         candidate_id=cand.id, status="applied")
    db.add(app)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="job_application",
                object_id=app.id,
                new_values={"posting_id": str(posting.id),
                            "candidate_id": str(cand.id),
                            "status": "applied"},
                reason="Lamaran baru", channel="api",
                ip=client_ip(request))
    db.commit()
    return app


@router.get("/recruitment/applications",
            response_model=list[ApplicationOut],
            dependencies=[Depends(require_permission("job_application",
                                                      "view"))])
def list_applications(posting_id: uuid.UUID | None = None,
                      status_: str | None = Query(default=None,
                                                  alias="status"),
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    stmt = (select(JobApplication)
            .where(JobApplication.tenant_id == user.tenant_id)
            .order_by(JobApplication.applied_at.desc()))
    if posting_id is not None:
        stmt = stmt.where(JobApplication.posting_id == posting_id)
    if status_ is not None:
        stmt = stmt.where(JobApplication.status == status_.strip().lower())
    rows = db.execute(stmt).scalars().all()
    if not _scope_all(db, user):
        own = _user_org_unit_id(db, user)
        rows = [a for a in rows
                if own is not None
                and str(_app_org_unit_id(db, a)) == str(own)]
    return rows


@router.get("/recruitment/applications/{app_id}",
            response_model=ApplicationOut,
            dependencies=[Depends(require_permission("job_application",
                                                      "view"))])
def get_application(app_id: uuid.UUID, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return _get_app(db, user, app_id)


@router.post("/recruitment/applications/{app_id}/move",
             response_model=ApplicationOut,
             dependencies=[Depends(require_permission("job_application",
                                                       "correct"))])
def move_application(app_id: uuid.UUID, body: ApplicationMove,
                     request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Pindah stage pipeline. Setiap transisi tercatat di audit
    (action='move_stage') dengan actor + timestamp + note."""
    app = _get_app(db, user, app_id)
    _check_move(app.status, body.to_stage, body.note)
    old = app.status
    app.status = body.to_stage
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="move_stage", object_type="job_application",
                object_id=app.id,
                old_values={"status": old},
                new_values={"status": body.to_stage},
                reason=(body.note or "").strip() or None,
                channel="api", ip=client_ip(request))
    db.commit()
    return app


# ================================================================ Interview
@router.post("/recruitment/interviews",
             response_model=InterviewOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("interview",
                                                       "insert"))])
def create_interview(body: InterviewCreate, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    app = db.get(JobApplication, body.application_id)
    if app is None or app.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Lamaran tidak ditemukan")
    _check_app_scope(db, user, app)
    if app.status in ("hired", "rejected", "withdrawn"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tidak bisa menjadwalkan wawancara untuk lamaran final")
    for uid in body.interviewer_ids:
        u = db.get(User, uid)
        if u is None or u.tenant_id != user.tenant_id or not u.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Interviewer {uid} tidak valid")
    iv = Interview(tenant_id=user.tenant_id, application_id=app.id,
                   scheduled_at=body.scheduled_at,
                   interviewer_ids=[str(uid) for uid in body.interviewer_ids],
                   location=(body.location or "").strip() or None,
                   mode=body.mode, status="scheduled")
    db.add(iv)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="interview", object_id=iv.id,
                new_values=snapshot(iv, ["id", "application_id",
                                         "scheduled_at", "mode", "status"]),
                reason="Wawancara dijadwalkan", channel="api",
                ip=client_ip(request))
    db.commit()
    return iv


@router.get("/recruitment/interviews",
            response_model=list[InterviewOut],
            dependencies=[Depends(require_permission("interview", "view"))])
def list_interviews(application_id: uuid.UUID | None = None,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    stmt = (select(Interview)
            .where(Interview.tenant_id == user.tenant_id)
            .order_by(Interview.scheduled_at))
    if application_id is not None:
        stmt = stmt.where(Interview.application_id == application_id)
    return db.execute(stmt).scalars().all()


def _interview_or_404(db: Session, user: User,
                      interview_id: uuid.UUID) -> Interview:
    iv = _tenant_row(db, user, Interview, interview_id, "Wawancara")
    app = db.get(JobApplication, iv.application_id)
    if app is not None:
        _check_app_scope(db, user, app)
    return iv


@router.post("/recruitment/interviews/{interview_id}/complete",
             response_model=InterviewOut,
             dependencies=[Depends(require_permission("interview",
                                                       "correct"))])
def complete_interview(interview_id: uuid.UUID, request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    iv = _interview_or_404(db, user, interview_id)
    if iv.status != "scheduled":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya wawancara scheduled yang bisa diselesaikan")
    old = iv.status
    iv.status = "completed"
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="interview", object_id=iv.id,
                old_values={"status": old}, new_values={"status": "completed"},
                reason="Wawancara selesai", channel="api",
                ip=client_ip(request))
    db.commit()
    return iv


@router.post("/recruitment/interviews/{interview_id}/cancel",
             response_model=InterviewOut,
             dependencies=[Depends(require_permission("interview",
                                                       "correct"))])
def cancel_interview(interview_id: uuid.UUID, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    iv = _interview_or_404(db, user, interview_id)
    if iv.status != "scheduled":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya wawancara scheduled yang bisa dibatalkan")
    old = iv.status
    iv.status = "cancelled"
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="interview", object_id=iv.id,
                old_values={"status": old}, new_values={"status": "cancelled"},
                reason="Wawancara dibatalkan", channel="api",
                ip=client_ip(request))
    db.commit()
    return iv


@router.post("/recruitment/interviews/{interview_id}/feedback",
             response_model=FeedbackOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("interview",
                                                       "correct"))])
def submit_feedback(interview_id: uuid.UUID, body: FeedbackCreate,
                    request: Request,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    iv = _interview_or_404(db, user, interview_id)
    if str(body.interviewer_id) not in [str(x) for x in iv.interviewer_ids]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Interviewer tidak terdaftar di wawancara ini")
    interviewer = db.get(User, body.interviewer_id)
    if interviewer is None or interviewer.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Interviewer tidak valid")
    dup = db.execute(
        select(InterviewFeedback.id).where(
            InterviewFeedback.tenant_id == user.tenant_id,
            InterviewFeedback.interview_id == iv.id,
            InterviewFeedback.interviewer_id == body.interviewer_id)
    ).first()
    if dup:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Feedback interviewer ini sudah ada")
    fb = InterviewFeedback(tenant_id=user.tenant_id, interview_id=iv.id,
                           interviewer_id=body.interviewer_id,
                           score=body.score,
                           notes=(body.notes or "").strip() or None,
                           recommendation=body.recommendation)
    db.add(fb)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="interview_feedback",
                object_id=fb.id,
                new_values={"interview_id": str(iv.id), "score": fb.score,
                            "recommendation": fb.recommendation},
                reason="Feedback wawancara", channel="api",
                ip=client_ip(request))
    db.commit()
    return fb


@router.get("/recruitment/interviews/{interview_id}/feedback",
            response_model=list[FeedbackOut],
            dependencies=[Depends(require_permission("interview", "view"))])
def list_feedback(interview_id: uuid.UUID,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    iv = _interview_or_404(db, user, interview_id)
    return db.execute(
        select(InterviewFeedback)
        .where(InterviewFeedback.tenant_id == user.tenant_id,
               InterviewFeedback.interview_id == iv.id)
        .order_by(InterviewFeedback.created_at)
    ).scalars().all()


# ================================================================ Offer
def _validate_offer_refs(db: Session, user: User, body: OfferCreate):
    for model, label, attr in (
            (Job, "Jabatan", "job_id"),
            (OrgUnit, "Unit organisasi", "org_unit_id"),
            (Location, "Lokasi", "location_id"),
            (LegalEntity, "Legal entity", "legal_entity_id")):
        row = db.get(model, getattr(body, attr))
        if row is None or row.tenant_id != user.tenant_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"{label} tidak ditemukan")


@router.post("/recruitment/offers",
             response_model=OfferOut,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("offer", "insert"))])
def create_offer(body: OfferCreate, request: Request,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    app = db.get(JobApplication, body.application_id)
    if app is None or app.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Lamaran tidak ditemukan")
    _check_app_scope(db, user, app)
    if app.status != "offering":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Offer hanya bisa dibuat saat lamaran di stage 'offering'")
    exists = db.execute(
        select(Offer.id).where(Offer.application_id == app.id)
    ).first()
    if exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Lamaran ini sudah punya offer")
    _validate_offer_refs(db, user, body)
    now = datetime.now(timezone.utc)
    expires = body.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "expires_at harus di masa depan")
    offer = Offer(tenant_id=user.tenant_id, application_id=app.id,
                  salary=body.salary, start_date=body.start_date,
                  contract_type=body.contract_type.strip(),
                  job_id=body.job_id, org_unit_id=body.org_unit_id,
                  location_id=body.location_id,
                  legal_entity_id=body.legal_entity_id,
                  expires_at=body.expires_at, status="draft",
                  created_by_user_id=user.id)
    db.add(offer)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="offer", object_id=offer.id,
                new_values=snapshot(offer, ["id", "application_id", "salary",
                                            "start_date", "contract_type",
                                            "status"]),
                reason="Offer dibuat (draft)", channel="api",
                ip=client_ip(request))
    db.commit()
    return offer


@router.post("/recruitment/offers/{offer_id}/send",
             response_model=OfferOut,
             dependencies=[Depends(require_permission("offer", "correct"))])
def send_offer(offer_id: uuid.UUID, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    offer = _tenant_row(db, user, Offer, offer_id, "Offer")
    if offer.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya offer draft yang bisa dikirim")
    old = offer.status
    offer.status = "sent"
    offer.offer_token = secrets.token_urlsafe(32)
    offer.sent_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="offer", object_id=offer.id,
                old_values={"status": old}, new_values={"status": "sent"},
                reason="Offer dikirim ke kandidat", channel="api",
                ip=client_ip(request))
    db.commit()
    return offer


@router.post("/recruitment/offers/{offer_id}/decline",
             response_model=OfferOut,
             dependencies=[Depends(require_permission("offer", "correct"))])
def decline_offer(offer_id: uuid.UUID, body: OfferDecline, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    offer = _tenant_row(db, user, Offer, offer_id, "Offer")
    if offer.status != "sent":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Hanya offer sent yang bisa ditandai declined")
    old = offer.status
    offer.status = "declined"
    offer.decided_at = datetime.now(timezone.utc)
    app = db.get(JobApplication, offer.application_id)
    if app is not None and app.status not in ("hired", "rejected",
                                              "withdrawn"):
        app.status = "withdrawn"
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="offer", object_id=offer.id,
                old_values={"status": old}, new_values={"status": "declined"},
                reason=(body.note or "").strip() or "Kandidat menolak",
                channel="api", ip=client_ip(request))
    db.commit()
    return offer


@router.get("/recruitment/offers",
            response_model=list[OfferOut],
            dependencies=[Depends(require_permission("offer", "view"))])
def list_offers(user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    return db.execute(
        select(Offer).where(Offer.tenant_id == user.tenant_id)
        .order_by(Offer.created_at.desc())
    ).scalars().all()


@router.get("/recruitment/offers/{offer_id}",
            response_model=OfferOut,
            dependencies=[Depends(require_permission("offer", "view"))])
def get_offer(offer_id: uuid.UUID, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return _tenant_row(db, user, Offer, offer_id, "Offer")


@router.get("/recruitment/offers/{offer_id}/pdf",
            dependencies=[Depends(require_permission("offer", "view"))])
def offer_pdf(offer_id: uuid.UUID, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    offer = _tenant_row(db, user, Offer, offer_id, "Offer")
    app = db.get(JobApplication, offer.application_id)
    cand = db.get(Candidate, app.candidate_id) if app else None
    posting = db.get(JobPosting, app.posting_id) if app else None
    tenant = db.get(Tenant, user.tenant_id)
    pdf = render_offer_letter_pdf(
        company_name=tenant.name if tenant else "-",
        candidate_name=cand.name if cand else "-",
        position_title=posting.title if posting else "-",
        salary=offer.salary, start_date=offer.start_date,
        contract_type=offer.contract_type, expires_at=offer.expires_at,
        offer_no=f"OFR/{offer.start_date.year}/{str(offer.id)[:8].upper()}",
    )
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename=offer_{offer.id}.pdf"})


# ================================================================ Publik
@router.get("/public/jobs", response_model=list[PublicJobOut])
def public_jobs(tenant: str = Query(...),
                db: Session = Depends(get_db)):
    """Daftar lowongan published — TANPA auth. Tenant via ?tenant=<slug>."""
    t = _public_tenant(db, tenant)
    return db.execute(
        select(JobPosting)
        .where(JobPosting.tenant_id == t.id,
               JobPosting.status == "published")
        .order_by(JobPosting.published_at.desc())
    ).scalars().all()


def _now_naive_aware(expires: datetime) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if expires.tzinfo is None:
        now = now.replace(tzinfo=None)
    return now, expires


@router.post("/public/offers/{token}/accept", response_model=AcceptOfferOut)
def accept_offer_public(token: str, body: AcceptOfferCreate,
                        request: Request, db: Session = Depends(get_db)):
    """Kandidat menerima offer via token — TANPA auth. Membuat Person +
    Employment + JobInfo (event 'hire')."""
    offer = db.execute(
        select(Offer).where(Offer.offer_token == token)
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tautan penawaran tidak valid")
    now, expires = _now_naive_aware(offer.expires_at)
    if offer.status == "expired" or now > expires:
        if offer.status != "expired":
            offer.status = "expired"
            db.flush()
            write_audit(db=db, tenant_id=offer.tenant_id,
                        actor_user_id=None, action="update",
                        object_type="offer", object_id=offer.id,
                        old_values={"status": offer.status},
                        new_values={"status": "expired"},
                        reason="Offer kedaluwarsa saat dibuka kandidat",
                        channel="public", ip=client_ip(request))
            db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Penawaran sudah kedaluwarsa")
    if offer.status != "sent":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Penawaran tidak dalam status terkirim")

    tenant_id = offer.tenant_id
    dup = db.execute(
        select(Person.id).where(Person.tenant_id == tenant_id,
                                Person.nik == body.nik)
    ).first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "NIK sudah terdaftar di tenant ini")
    if body.email:
        email_dup = db.execute(
            select(Person.id).where(Person.tenant_id == tenant_id,
                                    Person.email == body.email.strip().lower())
        ).first()
        if email_dup:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Email sudah terdaftar di tenant ini")

    sys_user = db.execute(
        select(User).where(User.tenant_id == tenant_id,
                           User.is_superadmin == True)  # noqa: E712
        .limit(1)
    ).scalar_one_or_none()
    if sys_user is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tidak ada akun sistem untuk mencatat hire")

    person = Person(
        tenant_id=tenant_id, nik=body.nik, full_name=body.full_name.strip(),
        birth_place=(body.birth_place or "").strip() or None,
        birth_date=body.birth_date, gender=body.gender,
        email=body.email.strip().lower() if body.email else None,
        phone=(body.phone or "").strip() or None,
        bank_name=(body.bank_name or "").strip() or None,
        bank_account_no=body.bank_account_no, ptkp="TK/0")
    db.add(person)
    db.flush()
    emp = Employment(tenant_id=tenant_id, person_id=person.id,
                     legal_entity_id=offer.legal_entity_id,
                     start_date=offer.start_date, status="active")
    db.add(emp)
    db.flush()
    job_info = None
    try:
        job_info = ed.insert_record(
            db=db, tenant_id=tenant_id, model=JobInfo,
            identity_field="employment_id", identity_value=emp.id,
            valid_from=offer.start_date,
            values={"job_id": offer.job_id, "org_unit_id": offer.org_unit_id,
                    "location_id": offer.location_id,
                    "manager_employment_id": None},
            event="hire", event_reason="Rekrutmen reguler",
            created_by=sys_user.id, event_applies_to="lifecycle")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    app = db.get(JobApplication, offer.application_id)
    old_stage = app.status if app is not None else None
    if app is not None:
        app.status = "hired"
    old_offer = offer.status
    offer.status = "accepted"
    offer.decided_at = datetime.now(timezone.utc)
    db.flush()

    write_audit(db=db, tenant_id=tenant_id, actor_user_id=None,
                action="create", object_type="person", object_id=person.id,
                new_values={"nik": person.nik, "full_name": person.full_name},
                reason="Hire dari e-offer (accept publik)",
                channel="public", ip=client_ip(request))
    write_audit(db=db, tenant_id=tenant_id, actor_user_id=None,
                action="move_stage", object_type="job_application",
                object_id=app.id if app else None,
                old_values={"status": old_stage}, new_values={"status": "hired"},
                reason="Offer diterima kandidat", channel="public",
                ip=client_ip(request))
    write_audit(db=db, tenant_id=tenant_id, actor_user_id=None,
                action="update", object_type="offer", object_id=offer.id,
                old_values={"status": old_offer},
                new_values={"status": "accepted"},
                reason="Offer diterima kandidat", channel="public",
                ip=client_ip(request))
    db.commit()
    return AcceptOfferOut(person_id=person.id, employment_id=emp.id,
                          job_info_id=job_info.id, nik=person.nik,
                          full_name=person.full_name,
                          start_date=emp.start_date)
