"""Password hashing (bcrypt via pwdlib) dan JWT."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, get_secret_key

_password_hash = PasswordHash((BcryptHasher(),))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, roles: list[str]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, get_secret_key(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_secret_key(), algorithms=[JWT_ALGORITHM])
