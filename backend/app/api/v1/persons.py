"""Person & Employment (master data S1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Employment, LegalEntity, Person, User
from app.schemas.schemas import (
    EmploymentCreate,
    EmploymentOut,
    PersonCreate,
    PersonOut,
)
from app.services.audit import write_audit

router = APIRouter(tags=["master-data"])

_PERSON_FIELDS = ["id", "nik", "full_name"]
_EMPLOYMENT_FIELDS = ["id", "person_id", "legal_entity_id", "start_date", "end_date", "status"]


@router.post(
    "/persons",
    response_model=PersonOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("person", "insert"))],
)
def create_person(
    body: PersonCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.execute(
            select(Person).where(Person.tenant_id == user.tenant_id, Person.nik == body.nik)
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "NIK sudah terdaftar di tenant ini")
    person = Person(tenant_id=user.tenant_id, nik=body.nik, full_name=body.full_name)
    db.add(person)
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="create",
        object_type="person",
        object_id=person.id,
        new_values=snapshot(person, _PERSON_FIELDS),
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return person


@router.get(
    "/persons",
    response_model=list[PersonOut],
    dependencies=[Depends(require_permission("person", "view"))],
)
def list_persons(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Person)
            .where(Person.tenant_id == user.tenant_id)
            .order_by(Person.full_name)
        )
        .scalars()
        .all()
    )


@router.get(
    "/persons/{person_id}",
    response_model=PersonOut,
    dependencies=[Depends(require_permission("person", "view"))],
)
def get_person(
    person_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    person = db.get(Person, person_id)
    if person is None or person.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person tidak ditemukan")
    return person


@router.post(
    "/employments",
    response_model=EmploymentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("employment", "insert"))],
)
def create_employment(
    body: EmploymentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    person = db.get(Person, body.person_id)
    if person is None or person.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person tidak ditemukan")
    le = db.get(LegalEntity, body.legal_entity_id)
    if le is None or le.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Legal entity tidak ditemukan")
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Tanggal akhir tidak boleh sebelum tanggal mulai",
        )
    emp = Employment(
        tenant_id=user.tenant_id,
        person_id=body.person_id,
        legal_entity_id=body.legal_entity_id,
        start_date=body.start_date,
        end_date=body.end_date,
        status=body.status,
    )
    db.add(emp)
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="create",
        object_type="employment",
        object_id=emp.id,
        new_values=snapshot(emp, _EMPLOYMENT_FIELDS),
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return emp


@router.get(
    "/employments",
    response_model=list[EmploymentOut],
    dependencies=[Depends(require_permission("employment", "view"))],
)
def list_employments(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return (
        db.execute(
            select(Employment)
            .where(Employment.tenant_id == user.tenant_id)
            .order_by(Employment.start_date)
        )
        .scalars()
        .all()
    )
