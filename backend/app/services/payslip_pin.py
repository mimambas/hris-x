"""PIN akses slip gaji self-service (EXP-003, PRD 13.1).

Satu PIN per akun (hash bcrypt). Verifikasi mencatat kegagalan:
5 kali salah beruntun mengunci 15 menit. Fungsi di sini murni
(tanpa HTTPException) — lapisan API memetakan hasil ke status HTTP
dan bertanggung jawab atas commit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_pin, verify_pin
from app.models import PayslipPin, User

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15

# Hasil check_pin:
OK = "ok"
NOT_SET = "belum_diatur"
LOCKED = "terkunci"
WRONG = "salah"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        # SQLite mengembalikan datetime naive; anggap UTC.
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_pin(db: Session, user: User) -> PayslipPin | None:
    return db.execute(
        select(PayslipPin).where(PayslipPin.tenant_id == user.tenant_id,
                                 PayslipPin.user_id == user.id)
    ).scalars().first()


def is_locked(pin: PayslipPin, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    locked_until = _aware(pin.locked_until)
    return locked_until is not None and locked_until > now


def set_pin(db: Session, user: User, pin_value: str) -> PayslipPin:
    """Buat atau timpa PIN user (pemanggil memvalidasi konfirmasi)."""
    pin = get_pin(db, user)
    if pin is None:
        pin = PayslipPin(tenant_id=user.tenant_id, user_id=user.id,
                         pin_hash=hash_pin(pin_value))
        db.add(pin)
    else:
        pin.pin_hash = hash_pin(pin_value)
    pin.failed_attempts = 0
    pin.locked_until = None
    db.flush()
    return pin


def check_pin(db: Session, user: User, pin_value: str | None) -> str:
    """Verifikasi PIN dan catat kegagalan. TIDAK commit.

    Pemanggil wajib commit agar pencatatan kegagalan/kunci tersimpan
    meski hasil bukan OK.
    """
    pin = get_pin(db, user)
    if pin is None:
        return NOT_SET
    now = datetime.now(timezone.utc)
    if is_locked(pin, now):
        return LOCKED
    if pin_value is None or not verify_pin(pin_value, pin.pin_hash):
        pin.failed_attempts = (pin.failed_attempts or 0) + 1
        if pin.failed_attempts >= MAX_FAILED_ATTEMPTS:
            pin.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            pin.failed_attempts = 0
            db.flush()
            return LOCKED
        db.flush()
        return WRONG
    if pin.failed_attempts:
        pin.failed_attempts = 0
        db.flush()
    return OK
