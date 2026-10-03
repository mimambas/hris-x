"""Endpoint PIN slip gaji (EXP-003, PRD 13.1).

PIN adalah kredensial akun: semua endpoint (kecuali reset oleh HR)
dibatasi ke akun sendiri dan hanya butuh login — tidak diikat izin
objek payroll agar karyawan tanpa akses menu payroll tetap bisa
mengatur PIN-nya. Penegakan PIN saat unduh ada di endpoint slip
payroll.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import PayrollLine, PayrollRun, User
from app.schemas.schemas import (
    PayslipMineOut,
    PayslipPinChange,
    PayslipPinReset,
    PayslipPinSet,
    PayslipPinStatusOut,
    PayslipPinVerify,
)
from app.services import payslip_pin as pin_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["payslip-pin"])

_ERR = {
    pin_service.NOT_SET: (status.HTTP_403_FORBIDDEN, "PIN_BELUM_DIATUR"),
    pin_service.LOCKED: (status.HTTP_403_FORBIDDEN, "PIN_TERKUNCI"),
    # 403 (bukan 401) agar klien tidak menafsirkannya sebagai sesi
    # berakhir dan meng-logout pengguna.
    pin_service.WRONG: (status.HTTP_403_FORBIDDEN, "PIN_SALAH"),
}


def _raise_for(result: str) -> None:
    code, detail = _ERR[result]
    raise HTTPException(code, detail)


def _audit(db: Session, user: User, request: Request, action: str,
           target_user_id, reason: str | None = None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type="payslip_pin",
                object_id=target_user_id, old_values=None,
                new_values={"target_user_id": str(target_user_id)},
                reason=reason, channel="api", ip=client_ip(request))


def _status(db: Session, user: User) -> PayslipPinStatusOut:
    pin = pin_service.get_pin(db, user)
    own = population_service.get_user_employment(db, user)
    return PayslipPinStatusOut(
        pin_set=pin is not None,
        locked=pin is not None and pin_service.is_locked(pin),
        employment_id=own.id if own is not None else None)


@router.get("/payroll/my-payslips", response_model=list[PayslipMineOut])
def my_payslips(user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Riwayat slip gaji milik sendiri (EXP-003: slip & riwayat gaji).

    Hanya dari run yang sudah dikunci — slip resmi. Tidak butuh izin
    objek payroll: kepemilikan dibuktikan dari akun yang login, dan
    unduhannya tetap digerbang PIN di endpoint slip payroll.
    """
    own = population_service.get_user_employment(db, user)
    if own is None:
        return []
    rows = db.execute(
        select(PayrollLine, PayrollRun)
        .join(PayrollRun, PayrollLine.payroll_run_id == PayrollRun.id)
        .where(PayrollLine.tenant_id == user.tenant_id,
               PayrollLine.employment_id == own.id,
               PayrollRun.status == "locked")
        .order_by(PayrollRun.period.desc())
    ).all()
    return [
        PayslipMineOut(run_id=run.id, period=run.period,
                       employment_id=line.employment_id,
                       person_name=line.person_name, nik=line.nik,
                       take_home_pay=line.take_home_pay)
        for line, run in rows
    ]


@router.get("/payslip-pin/status", response_model=PayslipPinStatusOut)
def pin_status(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    return _status(db, user)


@router.post("/payslip-pin/set", response_model=PayslipPinStatusOut,
             status_code=status.HTTP_201_CREATED)
def pin_set(body: PayslipPinSet, request: Request,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    if pin_service.get_pin(db, user) is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "PIN sudah diatur. Gunakan menu Ganti PIN.")
    if body.pin != body.pin_confirmation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Konfirmasi PIN tidak sama.")
    pin_service.set_pin(db, user, body.pin)
    _audit(db, user, request, "set", user.id)
    out = _status(db, user)
    db.commit()
    return out


@router.post("/payslip-pin/change", response_model=PayslipPinStatusOut)
def pin_change(body: PayslipPinChange, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    if body.new_pin != body.new_pin_confirmation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Konfirmasi PIN baru tidak sama.")
    result = pin_service.check_pin(db, user, body.current_pin)
    if result != pin_service.OK:
        db.commit()  # simpan pencatatan kegagalan/kunci
        _raise_for(result)
    pin_service.set_pin(db, user, body.new_pin)
    _audit(db, user, request, "change", user.id)
    out = _status(db, user)
    db.commit()
    return out


@router.post("/payslip-pin/verify")
def pin_verify(body: PayslipPinVerify,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    result = pin_service.check_pin(db, user, body.pin)
    db.commit()
    if result != pin_service.OK:
        _raise_for(result)
    return {"ok": True}


@router.post("/payslip-pin/reset", response_model=PayslipPinStatusOut)
def pin_reset(body: PayslipPinReset, request: Request,
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if not (user.is_superadmin or rbp_service.is_hr(db, user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Hanya HR yang dapat mereset PIN karyawan")
    target = db.get(User, body.user_id)
    if target is None or target.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Pengguna tidak ditemukan")
    pin = pin_service.get_pin(db, target)
    if pin is not None:
        db.delete(pin)
        db.flush()
    _audit(db, user, request, "reset", target.id, reason=body.reason)
    db.commit()
    return _status(db, target)
