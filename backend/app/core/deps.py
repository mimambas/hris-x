"""Dependencies FastAPI: user saat ini & pemeriksaan izin RBP."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models import Tenant, User
from app.services import rbp as rbp_service

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token akses wajib diisi")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid atau kedaluwarsa")
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tenant tidak aktif")
    return user


def require_permission(object_name: str, action: str):
    """Dependency factory: tolak (403) bila user tak punya izin. Default DENY."""

    def checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not rbp_service.has_permission(db, user, object_name, action):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Izin '{action}' pada '{object_name}' ditolak",
            )
        return user

    return checker


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Khusus superadmin")
    return user
