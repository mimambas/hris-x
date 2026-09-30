"""Person & Employment (master data S1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import CompInfo, Employment, LegalEntity, Person, User
from app.schemas.schemas import (
    EmploymentCreate,
    EmploymentOut,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    PtkpChangeRequest,
)
from app.services import effective_dating as ed
from app.services import population as pop_service
from app.services.audit import write_audit

router = APIRouter(tags=["master-data"])

_PERSON_FIELDS = [
    "id", "nik", "full_name", "birth_place", "birth_date", "email", "npwp",
    "ptkp", "bpjs_kes_no", "bpjs_tk_no", "bank_name", "bank_account_no",
]
_EMPLOYMENT_FIELDS = ["id", "person_id", "legal_entity_id", "start_date", "end_date", "status"]


def _email_taken(db, tenant_id, email, exclude_id=None) -> bool:
    if not email:
        return False
    stmt = select(Person).where(
        Person.tenant_id == tenant_id, Person.email == email
    )
    if exclude_id is not None:
        stmt = stmt.where(Person.id != exclude_id)
    return db.execute(stmt.limit(1)).first() is not None


def _get_person_or_404(db, user, person_id) -> Person:
    person = db.get(Person, person_id)
    if person is None or person.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person tidak ditemukan")
    if not pop_service.can_view_person(db, user, person_id):
        # 404 (bukan 403) agar tidak membocorkan keberadaan data di luar populasi.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person tidak ditemukan")
    return person


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
    if body.email and _email_taken(db, user.tenant_id, body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email sudah terdaftar di tenant ini")
    person = Person(
        tenant_id=user.tenant_id,
        nik=body.nik,
        full_name=body.full_name,
        birth_place=body.birth_place,
        birth_date=body.birth_date,
        email=body.email,
        npwp=body.npwp,
        ptkp=body.ptkp,
        bpjs_kes_no=body.bpjs_kes_no,
        bpjs_tk_no=body.bpjs_tk_no,
        bank_name=body.bank_name,
        bank_account_no=body.bank_account_no,
    )
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
    """Daftar person, otomatis difilter sesuai target population user
    (Sprint 2, PRD 15.5): manajer melihat timnya, karyawan melihat
    dirinya sendiri, HR/admin melihat semua."""
    stmt = select(Person).where(Person.tenant_id == user.tenant_id)
    visible = pop_service.get_visible_person_ids(db, user)
    if visible is not None:
        stmt = stmt.where(Person.id.in_(visible))
    return db.execute(stmt.order_by(Person.full_name)).scalars().all()


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
    return _get_person_or_404(db, user, person_id)


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


@router.patch(
    "/persons/{person_id}",
    response_model=PersonOut,
    dependencies=[Depends(require_permission("person", "correct"))],
)
def update_person(
    person_id: uuid.UUID,
    body: PersonUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ubah data person. PTKP tidak bisa lewat sini (pakai /ptkp-change)."""
    person = _get_person_or_404(db, user, person_id)
    values = body.model_dump(exclude={"reason"})
    # Terapkan hanya field yang dikirim eksplisit (boleh dikosongkan -> None).
    changes = {}
    for field in (
        "nik", "full_name", "birth_place", "birth_date", "email", "npwp",
        "bpjs_kes_no", "bpjs_tk_no", "bank_name", "bank_account_no",
    ):
        if field not in body.model_fields_set:
            continue
        new_val = values[field]
        if getattr(person, field) != new_val:
            changes[field] = (getattr(person, field), new_val)
            setattr(person, field, new_val)
    if "nik" in changes:
        dup = (
            db.execute(
                select(Person).where(
                    Person.tenant_id == user.tenant_id,
                    Person.nik == person.nik,
                    Person.id != person.id,
                )
            )
            .scalars()
            .first()
        )
        if dup:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "NIK sudah terdaftar di tenant ini"
            )
    if "email" in changes and _email_taken(db, user.tenant_id, person.email,
                                           exclude_id=person.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Email sudah terdaftar di tenant ini"
        )
    if not changes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Tidak ada field yang berubah"
        )
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="update",
        object_type="person",
        object_id=person.id,
        old_values={k: v[0] for k, v in changes.items()},
        new_values={k: v[1] for k, v in changes.items()},
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return person


@router.post(
    "/persons/{person_id}/ptkp-change",
    dependencies=[Depends(require_permission("person", "correct"))],
)
def change_ptkp(
    person_id: uuid.UUID,
    body: PtkpChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Perubahan status PTKP (CHR-005): update Person.ptkp + sisipkan versi
    CompInfo baru (event=data_update) untuk SETIAP employment aktif person,
    agar PPh 21 memakai PTKP baru mulai tanggal efektif."""
    from app.schemas.schemas import CompInfoOut

    person = _get_person_or_404(db, user, person_id)
    if person.ptkp == body.ptkp:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Status PTKP sudah '{body.ptkp}'",
        )
    employments = (
        db.execute(
            select(Employment).where(
                Employment.tenant_id == user.tenant_id,
                Employment.person_id == person.id,
            )
        )
        .scalars()
        .all()
    )
    if not employments:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Person belum memiliki employment",
        )
    old_ptkp = person.ptkp
    person.ptkp = body.ptkp
    new_versions = []
    try:
        for emp in employments:
            current = ed.as_of(
                db=db,
                tenant_id=user.tenant_id,
                model=CompInfo,
                identity_field="employment_id",
                identity_value=emp.id,
                as_of_date=body.effective_date,
            )
            if current is None:
                raise ValueError(
                    f"Employment {emp.id} belum memiliki data kompensasi"
                )
            record = ed.insert_record(
                db=db,
                tenant_id=user.tenant_id,
                model=CompInfo,
                identity_field="employment_id",
                identity_value=emp.id,
                valid_from=body.effective_date,
                values={
                    "pay_group": current.pay_group,
                    "components": dict(current.components),
                    "ptkp": body.ptkp,
                },
                event="data_update",
                event_reason="Perubahan status PTKP",
                created_by=user.id,
                event_applies_to="lifecycle",
            )
            new_versions.append(record)
            write_audit(
                db=db,
                tenant_id=user.tenant_id,
                actor_user_id=user.id,
                action="insert",
                object_type="comp_info",
                object_id=record.id,
                new_values={"ptkp": body.ptkp,
                            "valid_from": body.effective_date.isoformat()},
                reason=f"Perubahan PTKP {old_ptkp} -> {body.ptkp}: {body.reason}",
                channel="api",
                ip=client_ip(request),
            )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="update",
        object_type="person",
        object_id=person.id,
        old_values={"ptkp": old_ptkp},
        new_values={"ptkp": body.ptkp},
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return {
        "person_id": str(person.id),
        "ptkp_lama": old_ptkp,
        "ptkp_baru": body.ptkp,
        "effective_date": body.effective_date.isoformat(),
        "comp_versions": [CompInfoOut.model_validate(v) for v in new_versions],
    }
