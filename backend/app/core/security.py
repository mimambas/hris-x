"""Password hashing (bcrypt via pwdlib) dan JWT."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, get_secret_key

_password_hash = PasswordHash((BcryptHasher(),))

# ---------------------------------------------------------------- Kebijakan
# password (Sprint 10, go-live hardening)
# --------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 12


class PasswordPolicyError(ValueError):
    """Password melanggar kebijakan keamanan."""


def validate_password_policy(password: str) -> list[str]:
    """Kembalikan daftar pelanggaran kebijakan; kosong bila lolos.

    Aturan: min 12 karakter, wajib huruf besar, huruf kecil, angka, simbol.
    """
    errors: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(
            f"Password minimal {PASSWORD_MIN_LENGTH} karakter "
            f"(saat ini {len(password)})."
        )
    if not any(c.isupper() for c in password):
        errors.append("Password wajib mengandung huruf besar (A-Z).")
    if not any(c.islower() for c in password):
        errors.append("Password wajib mengandung huruf kecil (a-z).")
    if not any(c.isdigit() for c in password):
        errors.append("Password wajib mengandung angka (0-9).")
    if not any(not c.isalnum() for c in password):
        errors.append("Password wajib mengandung simbol (mis. !, @, #, $).")
    return errors


def hash_password(password: str) -> str:
    violations = validate_password_policy(password)
    if violations:
        raise PasswordPolicyError(" ".join(violations))
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
