"""Endpoint dasbor (Sprint 9, PRD ANL-001/ANL-003).

RBP:
- "dashboard" view untuk dasbor umum (Direktur/HR/Admin semua data,
  manajer terfilter otomatis ke timnya via target population, karyawan
  biasa 403 — kriteria penerimaan ANL-003).
- Dasbor payroll memakai izin "payroll" view (data gaji sensitif).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user, require_permission
from app.services import dashboard as svc
from app.services import population

router = APIRouter(prefix="/dashboard", tags=["dashboard"],
                   dependencies=[Depends(require_permission("dashboard", "view"))])


def _visible(user, db: Session):
    return population.get_visible_person_ids(db, user)


@router.get("/headcount")
def headcount(
    as_of: date | None = Query(default=None, description="Format YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return svc.headcount(db, user.tenant_id, as_of or date.today(),
                         _visible(user, db))


@router.get("/turnover")
def turnover(
    period: str = Query(description="Format YYYY-MM, mis. 2026-09"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        svc.parse_period(period)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Format period harus YYYY-MM")
    return svc.turnover(db, user.tenant_id, period, _visible(user, db))


@router.get("/attendance")
def attendance(
    period: str = Query(description="Format YYYY-MM, mis. 2026-09"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        svc.parse_period(period)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Format period harus YYYY-MM")
    return svc.attendance_dashboard(db, user.tenant_id, period,
                                    _visible(user, db))


@router.get("/leave")
def leave(
    year: int = Query(ge=2000, le=2100, description="Tahun, mis. 2026"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return svc.leave_dashboard(db, user.tenant_id, year, _visible(user, db))


@router.get("/payroll",
            dependencies=[Depends(require_permission("payroll", "view"))])
def payroll(
    period: str = Query(description="Format YYYY-MM, mis. 2026-09"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        svc.parse_period(period)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Format period harus YYYY-MM")
    result = svc.payroll_dashboard(db, user.tenant_id, period,
                                   _visible(user, db))
    if result is None:
        raise HTTPException(404, f"Tidak ada payroll run periode {period}")
    return result


@router.get("/demographics")
def demographics(
    as_of: date | None = Query(default=None, description="Format YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return svc.demographics(db, user.tenant_id, as_of or date.today(),
                            _visible(user, db))
