"""CompInfo bertanggal efektif: insert / correct / as_of / timeline.

Nominal di components WAJIB integer rupiah (PRD 18.4 aturan 3).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import CompInfo, Employment, User
from app.schemas.schemas import CompInfoCreate, CompInfoCorrect, CompInfoOut
from app.services import effective_dating as ed
from app.services.audit import write_audit

router = APIRouter(tags=["comp-info"])

_FIELDS = [
    "id", "employment_id", "valid_from", "valid_to", "seq_no",
    "pay_group", "components", "event", "event_reason",
]


class CompInfoInsertResponse(BaseModel):
    record: CompInfoOut
    retro_impact_periods: list[str] = []


def _validate_components(components: dict) -> None:
    for key, value in components.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Komponen '{key}' harus integer rupiah, bukan {type(value).__name__}",
            )


def _get_employment_or_404(db: Session, user: User, employment_id: uuid.UUID) -> Employment:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employment tidak ditemukan")
    return emp


@router.post(
    "/comp-info",
    response_model=CompInfoInsertResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("comp_info", "insert"))],
)
def insert_comp_info(
    body: CompInfoCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_employment_or_404(db, user, body.employment_id)
    _validate_components(body.components)
    try:
        record = ed.insert_record(
            db=db,
            tenant_id=user.tenant_id,
            model=CompInfo,
            identity_field="employment_id",
            identity_value=body.employment_id,
            valid_from=body.valid_from,
            values={"pay_group": body.pay_group, "components": body.components},
            event=body.event,
            event_reason=body.event_reason,
            created_by=user.id,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    retro_periods = (
        ed.detect_retro_impact(body.valid_from) if body.valid_from < date.today() else []
    )
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="insert",
        object_type="comp_info",
        object_id=record.id,
        new_values=snapshot(record, _FIELDS),
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return CompInfoInsertResponse(
        record=CompInfoOut.model_validate(record), retro_impact_periods=retro_periods
    )


@router.patch(
    "/comp-info/{record_id}/correct",
    response_model=CompInfoOut,
    dependencies=[Depends(require_permission("comp_info", "correct"))],
)
def correct_comp_info(
    record_id: uuid.UUID,
    body: CompInfoCorrect,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    values = body.model_dump(exclude={"reason"}, exclude_none=True)
    if not values:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Tidak ada field yang dibetulkan"
        )
    if "components" in values:
        _validate_components(values["components"])
    try:
        record, old_values = ed.correct_record(
            db=db,
            tenant_id=user.tenant_id,
            model=CompInfo,
            record_id=record_id,
            values=values,
        )
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record tidak ditemukan")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="correct",
        object_type="comp_info",
        object_id=record.id,
        old_values=old_values,
        new_values={k: getattr(record, k) for k in old_values},
        reason=body.reason,
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return record


@router.get(
    "/comp-info",
    response_model=CompInfoOut,
    dependencies=[Depends(require_permission("comp_info", "view"))],
)
def get_comp_info_as_of(
    employment_id: uuid.UUID,
    as_of: date = Query(default_factory=date.today, description="Format YYYY-MM-DD"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_employment_or_404(db, user, employment_id)
    record = ed.as_of(
        db=db,
        tenant_id=user.tenant_id,
        model=CompInfo,
        identity_field="employment_id",
        identity_value=employment_id,
        as_of_date=as_of,
    )
    if record is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Tidak ada data kompensasi yang berlaku pada {as_of.isoformat()}",
        )
    return record


@router.get(
    "/comp-info/timeline",
    response_model=list[CompInfoOut],
    dependencies=[Depends(require_permission("comp_info", "view_history"))],
)
def get_comp_info_timeline(
    employment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_employment_or_404(db, user, employment_id)
    return ed.timeline(
        db=db,
        tenant_id=user.tenant_id,
        model=CompInfo,
        identity_field="employment_id",
        identity_value=employment_id,
    )
