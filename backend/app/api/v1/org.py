"""Master data organisasi: baca saja di S1 (effective dating penuh = S2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Job, LegalEntity, Location, OrgUnit, Position, User
from app.schemas.schemas import (
    JobOut,
    LegalEntityOut,
    LocationOut,
    OrgUnitOut,
    PositionOut,
)

router = APIRouter(tags=["org"])
_view = [Depends(require_permission("org", "view"))]


@router.get("/org/legal-entities", response_model=list[LegalEntityOut], dependencies=_view)
def list_legal_entities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(LegalEntity)
            .where(LegalEntity.tenant_id == user.tenant_id)
            .order_by(LegalEntity.name)
        )
        .scalars()
        .all()
    )


@router.get("/org/units", response_model=list[OrgUnitOut], dependencies=_view)
def list_org_units(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(OrgUnit)
            .where(OrgUnit.tenant_id == user.tenant_id)
            .order_by(OrgUnit.name)
        )
        .scalars()
        .all()
    )


@router.get("/org/locations", response_model=list[LocationOut], dependencies=_view)
def list_locations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Location)
            .where(Location.tenant_id == user.tenant_id)
            .order_by(Location.name)
        )
        .scalars()
        .all()
    )


@router.get("/org/jobs", response_model=list[JobOut], dependencies=_view)
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Job).where(Job.tenant_id == user.tenant_id).order_by(Job.code)
        )
        .scalars()
        .all()
    )


@router.get("/org/positions", response_model=list[PositionOut], dependencies=_view)
def list_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Position)
            .where(Position.tenant_id == user.tenant_id)
            .order_by(Position.name)
        )
        .scalars()
        .all()
    )
