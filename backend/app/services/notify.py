"""Layanan notifikasi in-app (EXP-005, PRD 13.1).

notify() dipanggil di dalam transaksi pemanggil (tanpa commit) dan
menghormati preferensi kanal in_app pengguna: baris
NotificationPreference enabled=False menekan notifikasi. Kanal
email dan whatsapp belum terhubung — preferensinya disimpan lewat
API preferensi dan mulai berlaku saat kanal pengiriman tersedia.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employment, Notification, NotificationPreference, User

CATEGORIES: dict[str, str] = {
    "pengumuman": "Pengumuman perusahaan",
    "kudos": "Kudos & apresiasi",
    "helpdesk": "Helpdesk HR",
    "perubahan_data": "Perubahan data pribadi",
    "persetujuan": "Persetujuan & pengajuan",
}

CHANNELS: dict[str, dict] = {
    "in_app": {"label": "Di aplikasi", "available": True},
    "email": {"label": "Email", "available": False},
    "whatsapp": {"label": "WhatsApp", "available": False},
}


def preference_enabled(db: Session, user_id: uuid.UUID, category: str,
                       channel: str = "in_app") -> bool:
    row = db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
            NotificationPreference.channel == channel)
    ).scalars().first()
    if row is not None:
        return bool(row.enabled)
    return channel == "in_app"


def notify(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID,
           category: str, title: str, body: str = "",
           link: str | None = None) -> Notification | None:
    """Buat notifikasi in-app bila preferensi pengguna mengizinkan.

    Tidak melakukan commit — pemanggil yang memiliki transaksi.
    Mengembalikan None bila ditekan oleh preferensi.
    """
    if category not in CATEGORIES:
        raise ValueError(f"Kategori notifikasi tidak dikenal: {category}")
    if not preference_enabled(db, user_id, category, "in_app"):
        return None
    row = Notification(tenant_id=tenant_id, user_id=user_id,
                       category=category, title=title, body=body,
                       link=link)
    db.add(row)
    db.flush()
    return row


def user_for_employment(db: Session, employment_id: uuid.UUID) -> User | None:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.person_id is None:
        return None
    return db.execute(
        select(User).where(User.person_id == emp.person_id,
                           User.is_active.is_(True))
    ).scalars().first()


def user_for_person_id(db: Session, person_id: uuid.UUID) -> User | None:
    return db.execute(
        select(User).where(User.person_id == person_id,
                           User.is_active.is_(True))
    ).scalars().first()


def notify_employment(db: Session, *, tenant_id: uuid.UUID,
                      employment_id: uuid.UUID, category: str,
                      title: str, body: str = "",
                      link: str | None = None) -> Notification | None:
    target = user_for_employment(db, employment_id)
    if target is None:
        return None
    return notify(db, tenant_id=tenant_id, user_id=target.id,
                  category=category, title=title, body=body, link=link)
