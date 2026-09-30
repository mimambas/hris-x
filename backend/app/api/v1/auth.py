"""Autentikasi: login multi-tenant -> JWT."""

from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.models import Tenant, User
from app.schemas.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
)
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Rate limiting login (Sprint 10, ADR-0013).
# In-memory, PER-INSTANCE: dict (ip, email) -> deque timestamp kegagalan.
# Hanya kegagalan yang dihitung; login sukses me-reset counter.
# Catatan: untuk multi-instance pakai Redis — itu scope F2.
# ---------------------------------------------------------------------------
LOGIN_MAX_FAILED = 5
LOGIN_WINDOW_SECONDS = 60

_failed_logins: dict[tuple[str | None, str], deque[float]] = {}


def _login_key(request: Request, email: str) -> tuple[str | None, str]:
    return (client_ip(request), email.strip().lower())


def _failed_count(key: tuple[str | None, str]) -> int:
    now = time.monotonic()
    q = _failed_logins.get(key)
    if not q:
        return 0
    while q and now - q[0] > LOGIN_WINDOW_SECONDS:
        q.popleft()
    if not q:
        _failed_logins.pop(key, None)
        return 0
    return len(q)


def _record_failed_login(key: tuple[str | None, str]) -> None:
    q = _failed_logins.setdefault(key, deque())
    q.append(time.monotonic())
    _failed_count(key)  # pangkas entri kedaluwarsa


def clear_login_attempts() -> None:
    """Kosongkan counter (dipakai test agar antar-test terisolasi)."""
    _failed_logins.clear()


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    key = _login_key(request, body.email)
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
        _record_failed_login(key)
        if _failed_count(key) > LOGIN_MAX_FAILED:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Terlalu banyak percobaan login gagal. "
                "Coba lagi setelah 1 menit.",
                headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
            )
        # Pesan generik agar tidak membocorkan tenant/user mana yang salah.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kredensial tidak valid")

    # Sukses: reset counter percobaan gagal untuk (ip, email) ini.
    _failed_logins.pop(key, None)

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


@router.post("/auth/change-password", status_code=status.HTTP_200_OK)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ganti password milik sendiri (Sprint 10: kebijakan password ditegakkan)."""
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Password lama tidak cocok"
        )
    violations = validate_password_policy(body.new_password)
    if violations:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Password baru tidak memenuhi kebijakan: " + " ".join(violations),
        )
    user.password_hash = hash_password(body.new_password)
    db.flush()
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="change_password",
        object_type="user",
        object_id=user.id,
        reason="Ganti password mandiri",
        channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return {"ok": True}
