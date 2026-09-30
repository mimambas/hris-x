"""Autentikasi: login multi-tenant -> JWT."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.models import Tenant, User
from app.schemas.schemas import LoginRequest, LoginResponse, MeResponse
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    tenant = (
        db.execute(select(Tenant).where(Tenant.slug == body.tenant_slug)).scalars().first()
    )
    user = None
    if tenant is not None and tenant.is_active:
        user = (
            db.execute(
                select(User).where(User.tenant_id == tenant.id, User.email == body.email)
            )
            .scalars()
            .first()
        )
    if user is None or not user.is_active or not verify_password(
        body.password, user.password_hash
    ):
        # Pesan generik agar tidak membocorkan tenant/user mana yang salah.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kredensial tidak valid")

    roles = rbp_service.get_user_roles(db, user)
    role_names = [r.name for r in roles]
    token = create_access_token(
        user_id=user.id, tenant_id=tenant.id, roles=role_names
    )
    write_audit(
        db=db,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        action="login",
        object_type="user",
        object_id=user.id,
        reason="Login via API",
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return LoginResponse(
        access_token=token,
        tenant_id=tenant.id,
        user_id=user.id,
        roles=role_names,
    )


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    roles = rbp_service.get_user_roles(db, user)
    return MeResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        is_superadmin=user.is_superadmin,
        roles=[r.name for r in roles],
    )
