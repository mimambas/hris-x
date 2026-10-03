"""Perubahan data pribadi via approval + OTP (EXP-004, PRD 13.1).

Karyawan mengajukan perubahan alamat/telepon/email/rekening/
tanggungan dari profilnya. Rekening wajib verifikasi OTP sebelum
masuk antrean persetujuan HR (PRD). Kanal pengiriman OTP (email/
WhatsApp) belum terhubung: kode dibuat server, tersimpan ter-hash,
dan salinan sementaranya hanya bisa dibaca HR untuk diteruskan ke
karyawan (assisted OTP) — ganti dengan kanal nyata sebelum produksi.

Persetujuan menerapkan perubahan ke Person; tanggungan mengikuti
pola ptkp-change (Person.ptkp + versi CompInfo baru event
data_update untuk setiap employment aktif).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import (
    CompInfo,
    DataChangeRequest,
    Employment,
    Person,
    User,
)
from app.schemas.schemas import (
    DataChangeCreate,
    DataChangeDecision,
    DataChangeOut,
    DataChangeProfileOut,
    DataChangeVerifyOtp,
)
from app.services import effective_dating as ed
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit
from app.services.pph21 import validate_ptkp

router = APIRouter(tags=["data-changes"])

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
ACTIVE_STATUSES = ("menunggu_otp", "menunggu_persetujuan")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _require_hr(db: Session, user: User) -> None:
    if not (user.is_superadmin or rbp_service.is_hr(db, user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat melakukan ini")


def _own_person(db: Session, user: User) -> tuple[Person, Employment | None]:
    if user.person_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat data karyawan")
    person = db.get(Person, user.person_id)
    if person is None or person.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Data karyawan tidak ditemukan")
    return person, population_service.get_user_employment(db, user)


def _out(db: Session, req: DataChangeRequest) -> DataChangeOut:
    person = db.get(Person, req.person_id)
    out = DataChangeOut.model_validate(req)
    out.person_name = person.full_name if person is not None else None
    return out


def _get_or_404(db: Session, user: User,
                req_id: uuid.UUID) -> DataChangeRequest:
    req = db.get(DataChangeRequest, req_id)
    if req is None or req.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tidak ditemukan")
    return req


def _audit(db: Session, user: User, request: Request, action: str,
           req: DataChangeRequest, new_values: dict | None,
           reason: str | None = None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type="data_change_request",
                object_id=req.id, old_values=None,
                new_values=new_values, reason=reason, channel="api",
                ip=client_ip(request))


def _new_otp(req: DataChangeRequest) -> str:
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    req.otp_hash = hashlib.sha256(
        f"{req.id}:{code}".encode()).hexdigest()
    req.otp_code = code
    req.otp_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=OTP_TTL_MINUTES)
    req.otp_attempts = 0
    return code


def _validate_new_values(db: Session, user: User, person: Person,
                         body: DataChangeCreate) -> dict:
    """Validasi nilai baru per tipe; kembalikan dict yang dinormalkan."""
    nv = body.new_values or {}
    t = body.change_type
    if t == "alamat":
        address = str(nv.get("address") or "").strip()
        if len(address) < 10:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Alamat baru minimal 10 karakter")
        return {"address": address}
    if t == "telepon":
        phone = str(nv.get("phone") or "").strip()
        digits = "".join(c for c in phone if c.isdigit() or c == "+")
        if len(digits) < 9 or len(phone) > 30:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Nomor telepon tidak valid")
        return {"phone": phone}
    if t == "email":
        email = str(nv.get("email") or "").strip().lower()
        if "@" not in email or "." not in email.split("@")[-1] \
                or len(email) > 255:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Format email tidak valid")
        taken = db.execute(
            select(Person).where(Person.tenant_id == user.tenant_id,
                                 Person.email == email,
                                 Person.id != person.id)
        ).scalars().first()
        if taken is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Email sudah dipakai karyawan lain")
        return {"email": email}
    if t == "rekening":
        bank = str(nv.get("bank_name") or "").strip()
        no = str(nv.get("bank_account_no") or "").strip()
        if len(bank) < 2 or not no.isdigit() or not (6 <= len(no) <= 32):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Nama bank dan nomor rekening (6-32 angka) wajib valid")
        return {"bank_name": bank, "bank_account_no": no}
    # tanggungan
    ptkp_raw = str(nv.get("ptkp") or "").strip()
    try:
        ptkp = validate_ptkp(ptkp_raw)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    if person.ptkp == ptkp:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Status tanggungan sudah '{ptkp}'")
    return {"ptkp": ptkp}


def _snapshot_old(person: Person, change_type: str) -> dict:
    if change_type == "alamat":
        return {"address": person.address}
    if change_type == "telepon":
        return {"phone": person.phone}
    if change_type == "email":
        return {"email": person.email}
    if change_type == "rekening":
        return {"bank_name": person.bank_name,
                "bank_account_no": person.bank_account_no}
    return {"ptkp": person.ptkp}


# ------------------------------------------------------------- profil saya
@router.get("/data-changes/me", response_model=DataChangeProfileOut)
def my_profile(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    person, own = _own_person(db, user)
    return DataChangeProfileOut(
        person_id=person.id,
        employment_id=own.id if own is not None else None,
        full_name=person.full_name, nik=person.nik, email=person.email,
        phone=person.phone, address=person.address,
        bank_name=person.bank_name,
        bank_account_no=person.bank_account_no, ptkp=person.ptkp)


# --------------------------------------------------------------- pengajuan
@router.post("/data-changes", response_model=DataChangeOut,
             status_code=status.HTTP_201_CREATED)
def create_change(body: DataChangeCreate, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    person, own = _own_person(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment aktif")
    new_values = _validate_new_values(db, user, person, body)
    dup = db.execute(
        select(DataChangeRequest).where(
            DataChangeRequest.tenant_id == user.tenant_id,
            DataChangeRequest.person_id == person.id,
            DataChangeRequest.change_type == body.change_type,
            DataChangeRequest.status.in_(ACTIVE_STATUSES))
    ).scalars().first()
    if dup is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Masih ada permintaan perubahan yang sama yang berjalan. "
            "Selesaikan atau batalkan dulu.")
    req = DataChangeRequest(
        tenant_id=user.tenant_id, employment_id=own.id,
        person_id=person.id, change_type=body.change_type,
        old_values=_snapshot_old(person, body.change_type),
        new_values=new_values,
        status="menunggu_otp" if body.change_type == "rekening"
        else "menunggu_persetujuan",
        note=body.note)
    db.add(req)
    db.flush()
    if body.change_type == "rekening":
        _new_otp(req)
        db.flush()
    _audit(db, user, request, "create", req,
           {"change_type": req.change_type, "new_values": new_values})
    out = _out(db, req)
    db.commit()
    return out


@router.get("/data-changes/mine", response_model=list[DataChangeOut])
def my_changes(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    person, _ = _own_person(db, user)
    rows = db.execute(
        select(DataChangeRequest).where(
            DataChangeRequest.tenant_id == user.tenant_id,
            DataChangeRequest.person_id == person.id)
        .order_by(DataChangeRequest.created_at.desc())
    ).scalars().all()
    return [_out(db, r) for r in rows]


@router.get("/data-changes", response_model=list[DataChangeOut])
def all_changes(status_filter: str | None = Query(default=None),
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    _require_hr(db, user)
    stmt = select(DataChangeRequest).where(
        DataChangeRequest.tenant_id == user.tenant_id)
    if status_filter:
        stmt = stmt.where(DataChangeRequest.status == status_filter)
    rows = db.execute(
        stmt.order_by(DataChangeRequest.created_at.desc())).scalars().all()
    return [_out(db, r) for r in rows]


@router.get("/data-changes/{req_id}", response_model=DataChangeOut)
def change_detail(req_id: uuid.UUID,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    req = _get_or_404(db, user, req_id)
    person = None
    if user.person_id is not None:
        try:
            person, _ = _own_person(db, user)
        except HTTPException:
            person = None
    is_owner = person is not None and str(person.id) == str(req.person_id)
    if not (is_owner or user.is_superadmin
            or rbp_service.is_hr(db, user)):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tidak ditemukan")
    return _out(db, req)


@router.post("/data-changes/{req_id}/verify-otp",
             response_model=DataChangeOut)
def verify_otp(req_id: uuid.UUID, body: DataChangeVerifyOtp,
               request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    req = _get_or_404(db, user, req_id)
    person, _ = _own_person(db, user)
    if str(person.id) != str(req.person_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tidak ditemukan")
    if req.status != "menunggu_otp":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan tidak sedang menunggu OTP")
    now = datetime.now(timezone.utc)
    expires = _aware(req.otp_expires_at)
    if expires is None or expires < now:
        req.otp_code = None
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "OTP_KEDALUWARSA")
    if (req.otp_attempts or 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "OTP_TERKUNCI")
    digest = hashlib.sha256(f"{req.id}:{body.code}".encode()).hexdigest()
    if digest != req.otp_hash:
        req.otp_attempts = (req.otp_attempts or 0) + 1
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "OTP_SALAH")
    req.otp_verified_at = now
    req.otp_code = None
    req.status = "menunggu_persetujuan"
    db.flush()
    _audit(db, user, request, "verify_otp", req, None)
    out = _out(db, req)
    db.commit()
    return out


@router.post("/data-changes/{req_id}/resend-otp",
             response_model=DataChangeOut)
def resend_otp(req_id: uuid.UUID, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    req = _get_or_404(db, user, req_id)
    person, _ = _own_person(db, user)
    if str(person.id) != str(req.person_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tidak ditemukan")
    if req.status != "menunggu_otp":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan tidak sedang menunggu OTP")
    _new_otp(req)
    db.flush()
    _audit(db, user, request, "resend_otp", req, None)
    out = _out(db, req)
    db.commit()
    return out


@router.get("/data-changes/{req_id}/otp")
def read_otp_for_hr(req_id: uuid.UUID,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Assisted OTP: HR membaca kode untuk diteruskan ke karyawan.

    Hanya selama menunggu_otp & belum kedaluwarsa. Diganti kanal
    pengiriman nyata (email/WhatsApp) sebelum produksi.
    """
    _require_hr(db, user)
    req = _get_or_404(db, user, req_id)
    expires = _aware(req.otp_expires_at)
    if req.status != "menunggu_otp" or req.otp_code is None \
            or expires is None \
            or expires < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kode OTP tidak tersedia (sudah dipakai "
                            "atau kedaluwarsa)")
    return {"code": req.otp_code, "expires_at": req.otp_expires_at}


@router.post("/data-changes/{req_id}/cancel",
             response_model=DataChangeOut)
def cancel_change(req_id: uuid.UUID, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    req = _get_or_404(db, user, req_id)
    person, _ = _own_person(db, user)
    if str(person.id) != str(req.person_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tidak ditemukan")
    if req.status not in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan sudah diputuskan")
    req.status = "dibatalkan"
    req.otp_code = None
    db.flush()
    _audit(db, user, request, "cancel", req, None)
    out = _out(db, req)
    db.commit()
    return out


# -------------------------------------------------------------- persetujuan
def _apply(db: Session, user: User, req: DataChangeRequest,
           request: Request) -> None:
    person = db.get(Person, req.person_id)
    nv = req.new_values
    if req.change_type == "alamat":
        person.address = nv["address"]
    elif req.change_type == "telepon":
        person.phone = nv["phone"]
    elif req.change_type == "email":
        person.email = nv["email"]
    elif req.change_type == "rekening":
        person.bank_name = nv["bank_name"]
        person.bank_account_no = nv["bank_account_no"]
    elif req.change_type == "tanggungan":
        old_ptkp = person.ptkp
        person.ptkp = nv["ptkp"]
        employments = db.execute(
            select(Employment).where(
                Employment.tenant_id == user.tenant_id,
                Employment.person_id == person.id)
        ).scalars().all()
        for emp in employments:
            current = ed.as_of(
                db=db, tenant_id=user.tenant_id, model=CompInfo,
                identity_field="employment_id", identity_value=emp.id,
                as_of_date=date.today())
            if current is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Karyawan belum memiliki data kompensasi untuk "
                    "memperbarui PTKP")
            ed.insert_record(
                db=db, tenant_id=user.tenant_id, model=CompInfo,
                identity_field="employment_id", identity_value=emp.id,
                valid_from=date.today(),
                values={"pay_group": current.pay_group,
                        "components": dict(current.components),
                        "ptkp": nv["ptkp"]},
                event="data_update",
                event_reason="Perubahan status PTKP",
                created_by=user.id, event_applies_to="lifecycle")
        write_audit(
            db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
            action="update", object_type="person", object_id=person.id,
            old_values={"ptkp": old_ptkp},
            new_values={"ptkp": nv["ptkp"]},
            reason="EXP-004 tanggungan disetujui", channel="api",
            ip=client_ip(request))
    db.flush()


@router.post("/data-changes/{req_id}/approve",
             response_model=DataChangeOut)
def approve_change(req_id: uuid.UUID, body: DataChangeDecision,
                   request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    _require_hr(db, user)
    req = _get_or_404(db, user, req_id)
    if req.status == "menunggu_otp":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Rekening wajib verifikasi OTP karyawan sebelum disetujui")
    if req.status != "menunggu_persetujuan":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan sudah diputuskan")
    _apply(db, user, req, request)
    now = datetime.now(timezone.utc)
    req.status = "disetujui"
    req.decided_by_user_id = user.id
    req.decision_reason = body.reason
    req.decided_at = now
    req.applied_at = now
    req.otp_code = None
    db.flush()
    out = _out(db, req)
    _audit(db, user, request, "approve", req,
           {"change_type": req.change_type,
            "new_values": req.new_values},
           reason=body.reason)
    db.commit()
    return out


@router.post("/data-changes/{req_id}/reject",
             response_model=DataChangeOut)
def reject_change(req_id: uuid.UUID, body: DataChangeDecision,
                  request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _require_hr(db, user)
    req = _get_or_404(db, user, req_id)
    if req.status not in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan sudah diputuskan")
    if not (body.reason or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Alasan penolakan wajib diisi")
    req.status = "ditolak"
    req.decided_by_user_id = user.id
    req.decision_reason = body.reason
    req.decided_at = datetime.now(timezone.utc)
    req.otp_code = None
    db.flush()
    out = _out(db, req)
    _audit(db, user, request, "reject", req,
           {"change_type": req.change_type}, reason=body.reason)
    db.commit()
    return out
