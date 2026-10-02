"""Onboarding & offboarding (ONB, PRD 12.2, F2).

- Template checklist milik HR (kind onboarding/offboarding) + butir tugas
  per tim (hr/it/ga/manager/finance) dengan offset tenggat.
- Proses per karyawan: dibuat dari template; due_date tugas =
  start_date + due_offset_days. Tugas terlambat otomatis terflag
  `is_overdue` (eskalasi visual ONB-002).
- ONB-001: tugas dapat mensyaratkan tipe dokumen (`required_doc_type`,
  mis. "ktp"); status kesiapan dokumen diekspos di detail proses.
- ONB-004: offboarding = proses kind "offboarding" (clearance aset,
  cabut akses, exit interview, paklaring).
- ONB-003 (buddy/agenda/kursus wajib) = P2, ditunda ke F3.

Otorisasi: template hanya HR (`onboarding_template`); proses & tugas
memakai objek `onboarding_process` / `onboarding_task` + scope populasi
(karyawan: milik sendiri; manajer: timnya; HR: semua). Setiap mutasi
beraudit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    Document,
    Employment,
    OnboardingProcess,
    OnboardingTask,
    OnboardingTemplate,
    OnboardingTemplateTask,
    Person,
    User,
)
from app.schemas.schemas import (
    OnboardingProcessCreate,
    OnboardingProcessOut,
    OnboardingTaskAssign,
    OnboardingTaskOut,
    OnboardingTaskUpdate,
    OnboardingTemplateCreate,
    OnboardingTemplateOut,
    OnboardingTemplateTaskCreate,
    OnboardingTemplateTaskOut,
)
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

TEMPLATE_OBJECT = "onboarding_template"
PROCESS_OBJECT = "onboarding_process"
TASK_OBJECT = "onboarding_task"

TEAM_LABELS = {
    "hr": "HR",
    "it": "IT",
    "ga": "GA",
    "manager": "Atasan",
    "finance": "Keuangan",
}


# ------------------------------------------------------------------ Helper
def _tenant_row(db: Session, user: User, model, row_id: uuid.UUID,
                label: str):
    row = db.get(model, row_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{label} tidak ditemukan")
    return row


def _get_template(db: Session, user: User,
                  template_id: uuid.UUID) -> OnboardingTemplate:
    return _tenant_row(db, user, OnboardingTemplate, template_id, "Template")


def _get_process(db: Session, user: User,
                 process_id: uuid.UUID) -> OnboardingProcess:
    return _tenant_row(db, user, OnboardingProcess, process_id, "Proses")


def _get_task(db: Session, user: User, task_id: uuid.UUID) -> OnboardingTask:
    return _tenant_row(db, user, OnboardingTask, task_id, "Tugas")


def _person_name(db: Session, person_id: uuid.UUID) -> str | None:
    p = db.get(Person, person_id)
    return p.full_name if p else None


def _user_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    if not user_id:
        return None
    u = db.get(User, user_id)
    return u.full_name if u else None


def _process_stats(db: Session, process_id: uuid.UUID, today: date):
    tasks = db.execute(
        select(OnboardingTask).where(
            OnboardingTask.process_id == process_id
        )
    ).scalars().all()
    total = len(tasks)
    done = sum(1 for t in tasks if t.status in ("done", "skipped"))
    overdue = sum(
        1 for t in tasks
        if t.status not in ("done", "skipped") and t.due_date < today
    )
    return total, done, overdue


def _task_out(db: Session, t: OnboardingTask, today: date) -> OnboardingTaskOut:
    return OnboardingTaskOut(
        id=t.id,
        process_id=t.process_id,
        title=t.title,
        team=t.team,
        assignee_user_id=t.assignee_user_id,
        assignee_name=_user_name(db, t.assignee_user_id),
        due_date=t.due_date,
        status=t.status,
        is_overdue=t.status not in ("done", "skipped") and t.due_date < today,
        completed_at=t.completed_at,
        notes=t.notes,
    )


def _process_out(db: Session, p: OnboardingProcess,
                 today: date) -> OnboardingProcessOut:
    total, done, overdue = _process_stats(db, p.id, today)
    tmpl = db.get(OnboardingTemplate, p.template_id)
    return OnboardingProcessOut(
        id=p.id,
        person_id=p.person_id,
        person_name=_person_name(db, p.person_id),
        employment_id=p.employment_id,
        template_id=p.template_id,
        template_name=tmpl.name if tmpl else None,
        kind=p.kind,
        status=p.status,
        start_date=p.start_date,
        target_date=p.target_date,
        notes=p.notes,
        total_tasks=total,
        done_tasks=done,
        overdue_tasks=overdue,
        created_at=p.created_at,
        completed_at=p.completed_at,
    )


def _can_view_process(db: Session, user: User, p: OnboardingProcess) -> bool:
    if rbp_service.is_hr(db, user):
        return True
    return population_service.can_view_person(db, user, p.person_id)


def _can_act_task(db: Session, user: User, t: OnboardingTask) -> bool:
    """Boleh update tugas: HR, assignee, atau manajer dari karyawan proses."""
    if rbp_service.is_hr(db, user):
        return True
    if t.assignee_user_id and t.assignee_user_id == user.id:
        return True
    p = db.get(OnboardingProcess, t.process_id)
    return p is not None and population_service.can_view_person(
        db, user, p.person_id)


def _audit(request: Request, db: Session, user: User, action: str,
           object_type: str, object_id, old=None, new=None):
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        old_values=old,
        new_values=new,
        channel="api",
        ip=client_ip(request),
    )


# ------------------------------------------------------------------ Template (HR)
@router.post(
    "/templates",
    dependencies=[Depends(require_permission(TEMPLATE_OBJECT, "insert"))],
    status_code=status.HTTP_201_CREATED,
)
def create_template(
    body: OnboardingTemplateCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = OnboardingTemplate(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        kind=body.kind,
        created_by_user_id=user.id,
    )
    db.add(tmpl)
    db.flush()
    _audit(request, db, user, "create", TEMPLATE_OBJECT, tmpl.id,
           new={"name": tmpl.name, "kind": tmpl.kind})
    db.commit()
    return _template_out(db, tmpl)


def _template_out(db: Session, tmpl: OnboardingTemplate) -> OnboardingTemplateOut:
    count = db.execute(
        select(func.count()).select_from(OnboardingTemplateTask).where(
            OnboardingTemplateTask.template_id == tmpl.id
        )
    ).scalar() or 0
    return OnboardingTemplateOut(
        id=tmpl.id,
        name=tmpl.name,
        kind=tmpl.kind,
        is_active=tmpl.is_active,
        task_count=count,
        created_at=tmpl.created_at,
    )


@router.get(
    "/templates",
    dependencies=[Depends(require_permission(TEMPLATE_OBJECT, "view"))],
)
def list_templates(
    kind: str | None = Query(default=None,
                             pattern=r"^(onboarding|offboarding)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(OnboardingTemplate).where(
        OnboardingTemplate.tenant_id == user.tenant_id
    )
    if kind:
        stmt = stmt.where(OnboardingTemplate.kind == kind)
    tmpls = db.execute(stmt.order_by(OnboardingTemplate.name)).scalars().all()
    return [_template_out(db, t) for t in tmpls]


@router.get(
    "/templates/{template_id}",
    dependencies=[Depends(require_permission(TEMPLATE_OBJECT, "view"))],
)
def get_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = _get_template(db, user, template_id)
    tasks = db.execute(
        select(OnboardingTemplateTask).where(
            OnboardingTemplateTask.template_id == template_id
        ).order_by(OnboardingTemplateTask.sort_order,
                   OnboardingTemplateTask.title)
    ).scalars().all()
    out = _template_out(db, tmpl)
    return {
        "template": out,
        "tasks": [OnboardingTemplateTaskOut.model_validate(t) for t in tasks],
    }


@router.post(
    "/templates/{template_id}/tasks",
    dependencies=[Depends(require_permission(TEMPLATE_OBJECT, "correct"))],
    status_code=status.HTTP_201_CREATED,
)
def add_template_task(
    template_id: uuid.UUID,
    body: OnboardingTemplateTaskCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = _get_template(db, user, template_id)
    task = OnboardingTemplateTask(
        tenant_id=user.tenant_id,
        template_id=tmpl.id,
        title=body.title.strip(),
        team=body.team,
        due_offset_days=body.due_offset_days,
        sort_order=body.sort_order,
        required_doc_type=(body.required_doc_type or "").strip().lower() or None,
    )
    db.add(task)
    db.flush()
    _audit(request, db, user, "create", "onboarding_template_task", task.id,
           new={"template_id": str(tmpl.id), "title": task.title})
    db.commit()
    return OnboardingTemplateTaskOut.model_validate(task)


@router.delete(
    "/templates/{template_id}/tasks/{task_id}",
    dependencies=[Depends(require_permission(TEMPLATE_OBJECT, "correct"))],
)
def delete_template_task(
    template_id: uuid.UUID,
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_template(db, user, template_id)
    task = _get_task_template(db, user, template_id, task_id)
    _audit(request, db, user, "delete", "onboarding_template_task", task.id,
           old={"title": task.title})
    db.delete(task)
    db.commit()
    return {"ok": True}


def _get_task_template(db: Session, user: User, template_id: uuid.UUID,
                       task_id: uuid.UUID) -> OnboardingTemplateTask:
    task = db.get(OnboardingTemplateTask, task_id)
    if (task is None or task.tenant_id != user.tenant_id
            or task.template_id != template_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tugas template tidak ditemukan")
    return task


# ------------------------------------------------------------------ Proses
@router.post(
    "/processes",
    dependencies=[Depends(require_permission(PROCESS_OBJECT, "insert"))],
    status_code=status.HTTP_201_CREATED,
)
def start_process(
    body: OnboardingProcessCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tmpl = _get_template(db, user, body.template_id)
    if not tmpl.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Template tidak aktif")
    person = db.get(Person, body.person_id)
    if person is None or person.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Karyawan tidak ditemukan")
    employment = None
    if body.employment_id:
        employment = db.get(Employment, body.employment_id)
        if (employment is None or employment.tenant_id != user.tenant_id
                or employment.person_id != person.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Employment tidak ditemukan")
    if body.target_date and body.target_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Target selesai tidak boleh sebelum tanggal mulai")

    proc = OnboardingProcess(
        tenant_id=user.tenant_id,
        person_id=person.id,
        employment_id=employment.id if employment else None,
        template_id=tmpl.id,
        kind=tmpl.kind,
        start_date=body.start_date,
        target_date=body.target_date,
        notes=(body.notes or "").strip() or None,
        created_by_user_id=user.id,
    )
    db.add(proc)
    db.flush()

    # Salin butir template menjadi tugas instance.
    tmpl_tasks = db.execute(
        select(OnboardingTemplateTask).where(
            OnboardingTemplateTask.template_id == tmpl.id
        ).order_by(OnboardingTemplateTask.sort_order)
    ).scalars().all()
    for tt in tmpl_tasks:
        db.add(OnboardingTask(
            tenant_id=user.tenant_id,
            process_id=proc.id,
            title=tt.title,
            team=tt.team,
            due_date=body.start_date + timedelta(days=tt.due_offset_days),
            status="pending",
            required_doc_type=tt.required_doc_type,
        ))
    _audit(request, db, user, "create", PROCESS_OBJECT, proc.id,
           new={"person_id": str(person.id), "template": tmpl.name,
                "kind": tmpl.kind, "tasks": len(tmpl_tasks)})
    db.commit()
    return _process_out(db, proc, date.today())


@router.get(
    "/processes",
    dependencies=[Depends(require_permission(PROCESS_OBJECT, "view"))],
)
def list_processes(
    status_filter: str | None = Query(default=None, alias="status",
                                      pattern=r"^(in_progress|completed|cancelled)$"),
    kind: str | None = Query(default=None,
                             pattern=r"^(onboarding|offboarding)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(OnboardingProcess).where(
        OnboardingProcess.tenant_id == user.tenant_id
    )
    if status_filter:
        stmt = stmt.where(OnboardingProcess.status == status_filter)
    if kind:
        stmt = stmt.where(OnboardingProcess.kind == kind)
    procs = db.execute(
        stmt.order_by(OnboardingProcess.created_at.desc())
    ).scalars().all()
    # Scope populasi: karyawan hanya milik sendiri, manajer timnya, HR semua.
    if not rbp_service.is_hr(db, user):
        procs = [p for p in procs
                 if population_service.can_view_person(db, user, p.person_id)]
    today = date.today()
    return [_process_out(db, p, today) for p in procs]


@router.get(
    "/processes/{process_id}",
    dependencies=[Depends(require_permission(PROCESS_OBJECT, "view"))],
)
def get_process(
    process_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proc = _get_process(db, user, process_id)
    if not _can_view_process(db, user, proc):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Proses tidak ditemukan")
    today = date.today()
    tasks = db.execute(
        select(OnboardingTask).where(OnboardingTask.process_id == proc.id)
        .order_by(OnboardingTask.due_date, OnboardingTask.title)
    ).scalars().all()
    # ONB-001: tandai kesiapan dokumen yang disyaratkan tiap tugas.
    doc_types = _person_doc_types(db, proc.person_id)
    task_outs = []
    for t in tasks:
        o = _task_out(db, t, today)
        task_outs.append({
            **o.model_dump(),
            "required_doc_type": t.required_doc_type,
            "doc_ready": (t.required_doc_type in doc_types)
            if t.required_doc_type else None,
        })
    return {"process": _process_out(db, proc, today), "tasks": task_outs}


def _person_doc_types(db: Session, person_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        select(Document.doc_type).where(
            Document.person_id == person_id,
            Document.is_current.is_(True),
        )
    ).all()
    return {r[0] for r in rows}


@router.get(
    "/my-tasks",
    dependencies=[Depends(require_permission(TASK_OBJECT, "view"))],
)
def my_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tugas yang ditugaskan ke saya (belum selesai dulu)."""
    tasks = db.execute(
        select(OnboardingTask).where(
            OnboardingTask.tenant_id == user.tenant_id,
            OnboardingTask.assignee_user_id == user.id,
            OnboardingTask.status.notin_(["done", "skipped"]),
        ).order_by(OnboardingTask.due_date)
    ).scalars().all()
    today = date.today()
    return [_task_out(db, t, today) for t in tasks]


@router.patch(
    "/tasks/{task_id}",
    dependencies=[Depends(require_permission(TASK_OBJECT, "correct"))],
)
def update_task(
    task_id: uuid.UUID,
    body: OnboardingTaskUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_task(db, user, task_id)
    if not _can_act_task(db, user, task):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Anda tidak berhak mengubah tugas ini")
    proc = db.get(OnboardingProcess, task.process_id)
    if proc is None or proc.status != "in_progress":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Proses sudah selesai/dibatalkan")
    old = {"status": task.status}
    task.status = body.status
    if body.notes is not None:
        task.notes = body.notes.strip() or None
    now = datetime.now(timezone.utc)
    if body.status in ("done", "skipped"):
        task.completed_at = now
        task.completed_by_user_id = user.id
    else:
        task.completed_at = None
        task.completed_by_user_id = None
    _audit(request, db, user, "update", TASK_OBJECT, task.id, old=old,
           new={"status": task.status})
    db.commit()
    return _task_out(db, task, date.today())


@router.post(
    "/tasks/{task_id}/assign",
    dependencies=[Depends(require_permission(TASK_OBJECT, "correct"))],
)
def assign_task(
    task_id: uuid.UUID,
    body: OnboardingTaskAssign,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HR/manajer menugaskan tugas ke user (atau melepas)."""
    task = _get_task(db, user, task_id)
    if not rbp_service.is_hr(db, user):
        proc = db.get(OnboardingProcess, task.process_id)
        if proc is None or not population_service.can_view_person(
                db, user, proc.person_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Hanya HR atau atasan yang dapat menugaskan")
    assignee = None
    if body.assignee_user_id:
        assignee = db.get(User, body.assignee_user_id)
        if (assignee is None or assignee.tenant_id != user.tenant_id
                or not assignee.is_active):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "User tidak ditemukan/aktif")
    old = {"assignee_user_id": str(task.assignee_user_id)
           if task.assignee_user_id else None}
    task.assignee_user_id = assignee.id if assignee else None
    if task.status == "pending" and assignee:
        task.status = "in_progress"
    _audit(request, db, user, "assign", TASK_OBJECT, task.id, old=old,
           new={"assignee_user_id": str(assignee.id) if assignee else None})
    db.commit()
    return _task_out(db, task, date.today())


@router.post(
    "/processes/{process_id}/complete",
    dependencies=[Depends(require_permission(PROCESS_OBJECT, "correct"))],
)
def complete_process(
    process_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat menyelesaikan proses")
    proc = _get_process(db, user, process_id)
    if proc.status != "in_progress":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Proses sudah selesai/dibatalkan")
    open_tasks = db.execute(
        select(func.count()).select_from(OnboardingTask).where(
            OnboardingTask.process_id == proc.id,
            OnboardingTask.status.notin_(["done", "skipped"]),
        )
    ).scalar() or 0
    if open_tasks:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Masih ada {open_tasks} tugas belum selesai/dilewati")
    proc.status = "completed"
    proc.completed_at = datetime.now(timezone.utc)
    _audit(request, db, user, "complete", PROCESS_OBJECT, proc.id)
    db.commit()
    return _process_out(db, proc, date.today())


@router.post(
    "/processes/{process_id}/cancel",
    dependencies=[Depends(require_permission(PROCESS_OBJECT, "correct"))],
)
def cancel_process(
    process_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not rbp_service.is_hr(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat membatalkan proses")
    proc = _get_process(db, user, process_id)
    if proc.status != "in_progress":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Proses sudah selesai/dibatalkan")
    proc.status = "cancelled"
    _audit(request, db, user, "cancel", PROCESS_OBJECT, proc.id)
    db.commit()
    return _process_out(db, proc, date.today())
