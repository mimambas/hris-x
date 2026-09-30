"""Manajemen tenant — khusus superadmin (dibuat oleh seed awal)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_superadmin
from app.models import Tenant, User
from app.schemas.schemas import TenantCreate, TenantOut
from app.services import lifecycle
from app.services.audit import write_audit

router = APIRouter(tags=["tenants"])


@router.get(
    "/tenants",
    response_model=list[TenantOut],
    dependencies=[Depends(require_superadmin)],
)
def list_tenants(db: Session = Depends(get_db)):
    return db.execute(select(Tenant).order_by(Tenant.slug)).scalars().all()


@router.post(
    "/tenants",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_superadmin)],
)
def create_tenant(
    body: TenantCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.execute(select(Tenant).where(Tenant.slug == body.slug)).scalars().first()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slug tenant sudah dipakai")
    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    db.flush()
    # Sprint 3 (CHR-002): tenant baru langsung punya katalog event default.
    lifecycle.seed_lifecycle_catalog(db, tenant.id, created_by_user_id=user.id)
    write_audit(
        db=db,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        action="create",
        object_type="tenant",
        object_id=tenant.id,
        new_values={"name": tenant.name, "slug": tenant.slug},
        reason="Pembuatan tenant baru",
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return tenant
