"""Ekspor data warehouse/BI (ANL-005): API tarik inkremental.

Dataset adalah objek terkurasi yang sama dengan report builder
(karyawan, absensi, cuti, lembur, payroll) sehingga izin RBP per
objek/field dan Target Population pemilik akses selalu berlaku.
Sinkron bersifat inkremental berbasis penanda alami data:

- absensi/lembur: tanggal (YYYY-MM-DD)
- cuti: tanggal mulai (YYYY-MM-DD)
- payroll: periode (YYYY-MM)
- karyawan: snapshot penuh (dimensi; muat ulang berkala)

Konsumen (Metabase, Sheets, skrip ETL) menarik dengan parameter
``since`` inklusif lalu melakukan upsert berdasarkan
(employment_id, penanda) / nik. Otentikasi ganda: JWT pengguna,
atau kunci API BI (header X-BI-Key) yang dibuat dari halaman
Report Builder — kunci hanya disimpan sebagai hash sha256 dan
mewarisi izin + populasi pemiliknya.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BiApiKey, User
from app.services import report_builder as rb

LOADERS = {
    "karyawan": rb._load_karyawan,
    "absensi": rb._load_absensi,
    "cuti": rb._load_cuti,
    "lembur": rb._load_lembur,
    "payroll": rb._load_payroll,
}

SYNC_FIELDS: dict[str, str | None] = {
    "karyawan": None,
    "absensi": "tanggal",
    "cuti": "tanggal_mulai",
    "lembur": "tanggal",
    "payroll": "periode",
}

MAX_LIMIT = 1000


def datasets_for(db: Session, user: User) -> list[dict]:
    out = []
    for key in rb.OBJECTS:
        if not rb.can_use_object(db, user, key):
            continue
        out.append({
            "dataset": key,
            "label": rb.OBJECTS[key]["label"],
            "sync_field": SYNC_FIELDS[key],
            "mode": ("inkremental" if SYNC_FIELDS[key]
                     else "snapshot-penuh"),
            "url": f"/api/v1/bi/exports/{key}",
        })
    return out


def export_rows(db: Session, user: User, dataset: str,
                since: str | None, limit: int) -> dict:
    if dataset not in LOADERS:
        raise ValueError(f"Dataset tidak dikenal: {dataset}")
    if not rb.can_use_object(db, user, dataset):
        raise PermissionError(
            f"Izin view objek '{dataset}' tidak dimiliki pemilik akses")
    sync_field = SYNC_FIELDS[dataset]
    if since and not sync_field:
        raise ValueError(
            "Dataset karyawan adalah snapshot penuh; parameter "
            "since tidak didukung. Tarik seluruh dataset lalu "
            "lakukan upsert berdasarkan nik.")
    limit = max(1, min(limit, MAX_LIMIT))
    rows = LOADERS[dataset](db, user)
    allowed_fields = [
        k for k in rb.OBJECTS[dataset]["fields"]
        if rb.field_allowed(db, user, dataset, k)
    ]
    cleaned = []
    for row in rows:
        item = {k: row.get(k) for k in allowed_fields}
        item["employment_id"] = row.get("_employment_id")
        cleaned.append(item)
    if sync_field and since:
        cleaned = [r for r in cleaned
                   if str(r.get(sync_field) or "") >= since]
    if sync_field:
        cleaned.sort(key=lambda r: (str(r.get(sync_field) or ""),
                                    r.get("nama") or "",
                                    str(r.get("employment_id") or "")))
    else:
        cleaned.sort(key=lambda r: (r.get("nama") or "",
                                    str(r.get("employment_id") or "")))
    total = len(cleaned)
    page = cleaned[:limit]
    next_since = None
    if sync_field and total > limit and page:
        next_since = str(page[-1].get(sync_field))
    return {
        "dataset": dataset,
        "sync_field": sync_field,
        "since": since,
        "count": len(page),
        "total_available": total,
        "truncated": total > limit,
        "next_since": next_since,
        "rows": page,
    }


# ---------------------------------------------------------------- kunci API

_PREFIX = "hrisx_bi_"


def hash_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_key(db: Session, user: User, name: str) -> tuple[BiApiKey, str]:
    # Token memuat tenant_id agar endpoint ekspor dapat mengeset
    # konteks RLS dari token SEBELUM query (pola bootstrap yang
    # sama dengan login JWT), tanpa menebak tenant dari hash.
    secret = secrets.token_urlsafe(32)
    token = f"{_PREFIX}{user.tenant_id}_{secret}"
    key = BiApiKey(tenant_id=user.tenant_id, owner_user_id=user.id,
                   name=name, key_hash=hash_key(token))
    db.add(key)
    db.flush()
    return key, token


def tenant_id_from_token(token: str | None):
    if not token or not token.startswith(_PREFIX):
        return None
    parts = token.split("_", 3)
    if len(parts) != 4:
        return None
    try:
        return uuid.UUID(parts[2])
    except (ValueError, AttributeError):
        return None


def list_keys(db: Session, user: User) -> list[BiApiKey]:
    return db.execute(
        select(BiApiKey).where(
            BiApiKey.tenant_id == user.tenant_id,
            BiApiKey.owner_user_id == user.id)
        .order_by(BiApiKey.created_at.desc())
    ).scalars().all()


def revoke_key(db: Session, user: User, key_id) -> BiApiKey | None:
    key = db.get(BiApiKey, key_id)
    if key is None or key.tenant_id != user.tenant_id \
            or key.owner_user_id != user.id:
        return None
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.flush()
    return key


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token or not token.startswith(_PREFIX):
        return None
    key = db.execute(
        select(BiApiKey).where(BiApiKey.key_hash == hash_key(token))
    ).scalars().first()
    if key is None or key.revoked_at is not None:
        return None
    user = db.get(User, key.owner_user_id)
    if user is None or not user.is_active \
            or str(user.tenant_id) != str(key.tenant_id):
        return None
    key.last_used_at = datetime.now(timezone.utc)
    db.flush()
    db.commit()
    return user
