"""Report builder self-service (ANL-002, PRD 13.4).

Katalog objek terkurasi dari services/report_builder.py; objek dan
field tanpa izin RBP tidak muncul di katalog dan ditolak saat
dijalankan. Definisi laporan tersimpan per pengguna; jadwal kirim
menyusul setelah kanal email tersedia.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import ReportDefinition, User
from app.schemas.schemas import (
    ReportDefinitionIn,
    ReportDefinitionOut,
    ReportObjectOut,
    ReportRunIn,
    ReportRunOut,
)
from app.services import report_builder as rb
from app.services.audit import write_audit

router = APIRouter(tags=["report-builder"])

XLSX_MEDIA = ("application/vnd.openxmlformats-officedocument."
              "spreadsheetml.sheet")


@router.get("/report-builder/catalog", response_model=list[ReportObjectOut])
def catalog(user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    return rb.catalog_for(db, user)


@router.post("/report-builder/run", response_model=ReportRunOut)
def run(body: ReportRunIn, user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    return rb.run_report(db, user, body.model_dump())


@router.post("/report-builder/export.xlsx")
def export_xlsx(body: ReportRunIn, request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    result = rb.run_report(db, user, body.model_dump())
    spec_obj = rb.OBJECTS[body.object]
    data = rb.build_xlsx(result["columns"], result["rows"],
                         sheet=spec_obj["label"])
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="export", object_type="report_builder",
                object_id=None,
                new_values={"object": body.object,
                            "rows": result["total_rows"]},
                reason=None, channel="api", ip=client_ip(request))
    db.commit()
    filename = f"laporan-{body.object}-{date.today():%Y%m%d}.xlsx"
    return StreamingResponse(
        iter([data]), media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _own_definition(db: Session, user: User,
                    def_id: uuid.UUID) -> ReportDefinition:
    row = db.get(ReportDefinition, def_id)
    if row is None or row.tenant_id != user.tenant_id \
            or str(row.owner_user_id) != str(user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Definisi laporan tidak ditemukan")
    return row


@router.get("/report-definitions", response_model=list[ReportDefinitionOut])
def list_definitions(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    rows = db.execute(
        select(ReportDefinition).where(
            ReportDefinition.tenant_id == user.tenant_id,
            ReportDefinition.owner_user_id == user.id)
        .order_by(ReportDefinition.updated_at.desc())
    ).scalars().all()
    return rows


@router.post("/report-definitions", response_model=ReportDefinitionOut,
             status_code=status.HTTP_201_CREATED)
def create_definition(body: ReportDefinitionIn, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    # Validasi spec dapat dijalankan dengan izin pemanggil saat ini.
    rb.run_report(db, user, body.spec.model_dump())
    row = ReportDefinition(tenant_id=user.tenant_id, owner_user_id=user.id,
                           name=body.name, spec=body.spec.model_dump())
    db.add(row)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="create", object_type="report_definition",
                object_id=row.id, old_values=None,
                new_values={"name": row.name}, reason=None, channel="api",
                ip=client_ip(request))
    out = ReportDefinitionOut.model_validate(row)
    db.commit()
    return out


@router.put("/report-definitions/{def_id}",
            response_model=ReportDefinitionOut)
def update_definition(def_id: uuid.UUID, body: ReportDefinitionIn,
                      request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    row = _own_definition(db, user, def_id)
    rb.run_report(db, user, body.spec.model_dump())
    row.name = body.name
    row.spec = body.spec.model_dump()
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="update", object_type="report_definition",
                object_id=row.id, old_values=None,
                new_values={"name": row.name}, reason=None, channel="api",
                ip=client_ip(request))
    out = ReportDefinitionOut.model_validate(row)
    db.commit()
    return out


@router.delete("/report-definitions/{def_id}", status_code=204)
def delete_definition(def_id: uuid.UUID, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    row = _own_definition(db, user, def_id)
    db.delete(row)
    db.flush()
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action="delete", object_type="report_definition",
                object_id=def_id, old_values={"name": row.name},
                new_values=None, reason=None, channel="api",
                ip=client_ip(request))
    db.commit()
    return None


@router.post("/report-definitions/{def_id}/run", response_model=ReportRunOut)
def run_definition(def_id: uuid.UUID,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    row = _own_definition(db, user, def_id)
    return rb.run_report(db, user, row.spec)
