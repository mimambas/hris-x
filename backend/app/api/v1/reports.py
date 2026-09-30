"""Endpoint unduhan laporan XLSX (Sprint 9, PRD ANL-001/ANL-002).

Menghormati target population: manajer hanya mendapat baris timnya,
karyawan biasa 403. Unduhan tercatat di audit trail (aksi export).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user, require_permission
from app.services import audit as audit_svc
from app.services import dashboard as svc
from app.services import population

router = APIRouter(tags=["reports"])

XLSX_MEDIA = ("application/vnd.openxmlformats-officedocument."
              "spreadsheetml.sheet")


def _xlsx_response(data: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([data]), media_type=XLSX_MEDIA,
        headers={"Content-Disposition":
                 f'attachment; filename="{filename}"'},
    )


@router.get("/reports/employees.xlsx",
            dependencies=[Depends(require_permission("person", "view"))])
def employees_xlsx(
    as_of: date | None = Query(default=None, description="Format YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    visible = population.get_visible_person_ids(db, user)
    data = svc.build_employees_xlsx(db, user.tenant_id, as_of or date.today(),
                                    visible)
    audit_svc.write_audit(db=db, tenant_id=user.tenant_id,
                          actor_user_id=user.id, action="export",
                          object_type="report",
                          new_values={"report": "employees.xlsx"})
    db.commit()
    return _xlsx_response(data, f"karyawan-{date.today():%Y%m%d}.xlsx")


@router.get("/reports/payroll-summary.xlsx",
            dependencies=[Depends(require_permission("payroll", "view"))])
def payroll_summary_xlsx(
    period: str = Query(description="Format YYYY-MM, mis. 2026-09"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        svc.parse_period(period)
    except (ValueError, AttributeError):
        raise HTTPException(422, "Format period harus YYYY-MM")
    visible = population.get_visible_person_ids(db, user)
    data = svc.build_payroll_summary_xlsx(db, user.tenant_id, period, visible)
    if data is None:
        raise HTTPException(404, f"Tidak ada payroll run periode {period}")
    audit_svc.write_audit(db=db, tenant_id=user.tenant_id,
                          actor_user_id=user.id, action="export",
                          object_type="report",
                          new_values={"report": "payroll-summary.xlsx",
                                      "period": period})
    db.commit()
    return _xlsx_response(data, f"payroll-{period}.xlsx")
