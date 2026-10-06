"""BPA1: agregat tahunan, PDF karyawan ber-PIN, ekspor XML DJP.

PAY-011/PAY-006/EXP-003: dokumen BPA1 karyawan diunduh dari
self-service dengan PIN slip yang sama; ekspor XML massal hanya
HR (izin payroll view) dan diblokir bila ada NIK tidak valid atau
NPWP pemberi kerja belum diatur.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import Depends, Header, HTTPException, Query, Request, Response, status
from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import Employment, LegalEntityInfo, User
from app.schemas import schemas as sch
from app.services import bpa1 as bpa1_service
from app.services import effective_dating as ed
from app.services import payslip_pin as pin_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["bpa1"])


def _employer_name(db: Session, tenant_id, legal_entity_id, year: int):
    if not legal_entity_id:
        return "-"
    info = ed.as_of(db=db, tenant_id=tenant_id, model=LegalEntityInfo,
                    identity_field="legal_entity_id",
                    identity_value=uuid.UUID(str(legal_entity_id)),
                    as_of_date=date(year, 12, 31))
    return info.name if info else "-"


@router.get("/bpa1/summary", response_model=sch.Bpa1SummaryOut,
            dependencies=[Depends(require_permission("payroll", "view"))])
def summary(year: int = Query(..., ge=2020, le=2100),
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    rows = bpa1_service.aggregate_year(db, user.tenant_id, year)
    return {
        "year": year,
        "rows": [{
            **{k: v for k, v in r.items()
               if k not in ("legal_entity_id",)},
            "legal_entity_id": r["legal_entity_id"],
            "nik_valid": bpa1_service.valid_nik(r["nik"]),
            "employer_name": _employer_name(
                db, user.tenant_id, r["legal_entity_id"], year),
        } for r in rows],
        "employers": bpa1_service.employers(db, user.tenant_id, year),
    }


@router.get("/bpa1/{employment_id}.pdf")
def bpa1_pdf(
    employment_id: uuid.UUID,
    request: Request,
    year: int = Query(..., ge=2020, le=2100),
    x_payslip_pin: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    own = population_service.get_user_employment(db, user)
    is_own = own is not None and str(own.id) == str(employment_id)
    if not is_own and not rbp_service.has_permission(
            db, user, "payroll", "view"):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Izin 'view' pada 'payroll' ditolak")
    if is_own:
        result = pin_service.check_pin(db, user, x_payslip_pin)
        if result != pin_service.OK:
            db.commit()
            detail = {
                pin_service.NOT_SET: "PIN_BELUM_DIATUR",
                pin_service.LOCKED: "PIN_TERKUNCI",
                pin_service.WRONG: "PIN_SALAH",
            }[result]
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail)
    rows = {r["employment_id"]: r
            for r in bpa1_service.aggregate_year(db, user.tenant_id, year)}
    row = rows.get(str(employment_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Tidak ada data payroll pada tahun tersebut")
    employer_name = _employer_name(db, user.tenant_id,
                                   row["legal_entity_id"], year)
    npwp = None
    for e in bpa1_service.employers(db, user.tenant_id, year):
        if e["legal_entity_id"] == row["legal_entity_id"]:
            npwp = e["npwp"]
    pdf = bpa1_service.render_bpa1_pdf(
        row=row, year=year, employer_name=employer_name,
        employer_npwp=npwp)
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="download", object_type="bpa1_pdf",
        object_id=employment_id, old_values=None,
        new_values={"year": year, "self_service": is_own},
        reason=None, channel="api", ip=client_ip(request))
    db.commit()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename=bpa1-{year}-{row['nik']}.pdf"})


@router.get("/bpa1/export.xml",
            dependencies=[Depends(require_permission("payroll", "view"))])
def export_xml(
    request: Request,
    year: int = Query(..., ge=2020, le=2100),
    legal_entity_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        xml, info = bpa1_service.build_xml(
            db, user.tenant_id, year, str(legal_entity_id))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            str(exc)) from exc
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="export", object_type="bpa1_xml", object_id=None,
        old_values=None, new_values=info,
        reason=None, channel="api", ip=client_ip(request))
    db.commit()
    return Response(
        content=xml, media_type="application/xml",
        headers={"Content-Disposition":
                 f"attachment; filename=bpa1-{year}.xml"})
