"""Struktur organisasi bertanggal efektif (Sprint 2, CHR-001).

- LegalEntity / OrgUnit / Location / CostCenter: tabel identitas + tabel
  info berversi. Perubahan (rename, pindah parent, nonaktif) = versi baru
  via layanan effective_dating generik (bukan update).
- Endpoint baca S1 dipertahankan (kontrak aditif: field lama + info versi).
- GET /org/chart?as_of= → pohon hierarki per tanggal (CHR-001).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    CostCenter,
    CostCenterInfo,
    Job,
    LegalEntity,
    LegalEntityInfo,
    Location,
    LocationInfo,
    OrgUnit,
    OrgUnitInfo,
    Position,
    User,
)
from app.schemas.schemas import (
    CostCenterCreate,
    CostCenterVersionCreate,
    CostCenterVersionOut,
    JobOut,
    LegalEntityCreate,
    LegalEntityOut,
    LegalEntityVersionCreate,
    LegalEntityVersionOut,
    LocationCreate,
    LocationOut,
    LocationVersionCreate,
    LocationVersionOut,
    OrgChartNode,
    OrgUnitCreate,
    OrgUnitOut,
    OrgUnitVersionCreate,
    OrgUnitVersionOut,
    PositionOut,
)
from app.services import effective_dating as ed
from app.services import org as org_service
from app.services.audit import write_audit

router = APIRouter(tags=["org"])
_view = [Depends(require_permission("org", "view"))]
_view_hist = [Depends(require_permission("org", "view_history"))]
_insert = [Depends(require_permission("org", "insert"))]

_view_cc = [Depends(require_permission("cost_center", "view"))]
_view_cc_hist = [Depends(require_permission("cost_center", "view_history"))]
_insert_cc = [Depends(require_permission("cost_center", "insert"))]


def _audit(db, user, request, action, object_type, object_id, new_values, reason,
           old_values=None):
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        old_values=old_values,
        new_values=new_values,
        reason=reason,
        channel="api",
        ip=client_ip(request),
    )


def _identity_or_404(db, user, model, identity_id, label: str):
    row = db.get(model, identity_id)
    if row is None or row.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} tidak ditemukan")
    return row


def _version_or_404(db, user, info_model, identity_field, identity_id,
                    as_of_date: date, label: str):
    ver = ed.as_of(
        db=db, tenant_id=user.tenant_id, model=info_model,
        identity_field=identity_field, identity_value=identity_id,
        as_of_date=as_of_date,
    )
    if ver is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"{label} tidak memiliki versi yang berlaku pada {as_of_date.isoformat()}",
        )
    return ver


# ---------------------------------------------------------------------------
# Daftar S1 (kontrak aditif: field lama + info versi per hari ini)
# ---------------------------------------------------------------------------
@router.get("/org/legal-entities", response_model=list[LegalEntityOut], dependencies=_view)
def list_legal_entities(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    today = date.today()
    out = []
    for le in db.execute(
        select(LegalEntity)
        .where(LegalEntity.tenant_id == user.tenant_id)
        .order_by(LegalEntity.id)
    ).scalars().all():
        ver = org_service.version_as_of(db, user.tenant_id, LegalEntityInfo, le.id, today)
        if ver is None:
            continue
        out.append(LegalEntityOut(id=le.id, name=ver.name, npwp=ver.npwp))
    out.sort(key=lambda o: o.name)
    return out


@router.get("/org/units", response_model=list[OrgUnitOut], dependencies=_view)
def list_org_units(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    out = []
    for unit in db.execute(
        select(OrgUnit).where(OrgUnit.tenant_id == user.tenant_id)
    ).scalars().all():
        ver = org_service.version_as_of(db, user.tenant_id, OrgUnitInfo, unit.id, today)
        if ver is None:
            continue
        out.append(
            OrgUnitOut(
                id=unit.id,
                legal_entity_id=ver.legal_entity_id,
                parent_id=ver.parent_id,
                name=ver.name,
            )
        )
    out.sort(key=lambda o: o.name)
    return out


@router.get("/org/locations", response_model=list[LocationOut], dependencies=_view)
def list_locations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    out = []
    for loc in db.execute(
        select(Location).where(Location.tenant_id == user.tenant_id)
    ).scalars().all():
        ver = org_service.version_as_of(db, user.tenant_id, LocationInfo, loc.id, today)
        if ver is None:
            continue
        out.append(LocationOut(id=loc.id, name=ver.name, timezone=ver.timezone))
    out.sort(key=lambda o: o.name)
    return out


@router.get("/org/jobs", response_model=list[JobOut], dependencies=_view)
def list_jobs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Job).where(Job.tenant_id == user.tenant_id).order_by(Job.code)
        )
        .scalars()
        .all()
    )


@router.get("/org/positions", response_model=list[PositionOut], dependencies=_view)
def list_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(Position)
            .where(Position.tenant_id == user.tenant_id)
            .order_by(Position.name)
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Legal entity berversi
# ---------------------------------------------------------------------------
_LE_FIELDS = ["id", "legal_entity_id", "name", "npwp", "valid_from", "valid_to",
              "seq_no", "event", "event_reason"]


@router.post(
    "/org/legal-entities",
    response_model=LegalEntityVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def create_legal_entity(
    body: LegalEntityCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    le = LegalEntity(tenant_id=user.tenant_id)
    db.add(le)
    db.flush()
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=LegalEntityInfo,
            identity_field="legal_entity_id", identity_value=le.id,
            valid_from=body.valid_from,
            values={"name": body.name, "npwp": body.npwp},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "legal_entity_info", ver.id,
           snapshot(ver, _LE_FIELDS), body.reason)
    db.commit()
    return ver


@router.post(
    "/org/legal-entities/{le_id}/versions",
    response_model=LegalEntityVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def version_legal_entity(
    le_id: uuid.UUID,
    body: LegalEntityVersionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, LegalEntity, le_id, "Legal entity")
    current = _version_or_404(db, user, LegalEntityInfo, "legal_entity_id", le_id,
                              body.valid_from, "Legal entity")
    values = {
        "name": body.name if body.name is not None else current.name,
        "npwp": body.npwp if "npwp" in body.model_fields_set else current.npwp,
    }
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=LegalEntityInfo,
            identity_field="legal_entity_id", identity_value=le_id,
            valid_from=body.valid_from, values=values,
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "legal_entity_info", ver.id,
           snapshot(ver, _LE_FIELDS), body.reason)
    db.commit()
    return ver


@router.get(
    "/org/legal-entities/{le_id}/timeline",
    response_model=list[LegalEntityVersionOut],
    dependencies=_view_hist,
)
def timeline_legal_entity(
    le_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, LegalEntity, le_id, "Legal entity")
    return org_service.version_timeline(db, user.tenant_id, LegalEntityInfo, le_id)


# ---------------------------------------------------------------------------
# Org unit berversi
# ---------------------------------------------------------------------------
_OU_FIELDS = ["id", "org_unit_id", "name", "parent_id", "legal_entity_id",
              "is_active", "valid_from", "valid_to", "seq_no", "event",
              "event_reason"]


def _validate_unit_refs(db, user, *, legal_entity_id, parent_id, valid_from,
                        unit_id=None):
    if legal_entity_id is not None:
        _version_or_404(db, user, LegalEntityInfo, "legal_entity_id",
                        legal_entity_id, valid_from, "Legal entity")
    if parent_id is not None:
        _identity_or_404(db, user, OrgUnit, parent_id, "Parent unit")
        _version_or_404(db, user, OrgUnitInfo, "org_unit_id", parent_id,
                        valid_from, "Parent unit")
    if unit_id is not None:
        try:
            org_service.assert_no_cycle(db, user.tenant_id, unit_id, parent_id,
                                        valid_from)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


@router.post(
    "/org/units",
    response_model=OrgUnitVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def create_org_unit(
    body: OrgUnitCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_unit_refs(db, user, legal_entity_id=body.legal_entity_id,
                        parent_id=body.parent_id, valid_from=body.valid_from)
    unit = OrgUnit(tenant_id=user.tenant_id)
    db.add(unit)
    db.flush()
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=OrgUnitInfo,
            identity_field="org_unit_id", identity_value=unit.id,
            valid_from=body.valid_from,
            values={"name": body.name, "parent_id": body.parent_id,
                    "legal_entity_id": body.legal_entity_id, "is_active": True},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "org_unit_info", ver.id,
           snapshot(ver, _OU_FIELDS), body.reason)
    db.commit()
    return ver


@router.post(
    "/org/units/{unit_id}/versions",
    response_model=OrgUnitVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def version_org_unit(
    unit_id: uuid.UUID,
    body: OrgUnitVersionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Versi baru unit: rename / pindah parent (restrukturisasi) / pindah
    legal entity / nonaktifkan. Penonaktifan unit yang masih memiliki
    employment aktif ditolak (422) dengan pesan jelas."""
    _identity_or_404(db, user, OrgUnit, unit_id, "Unit organisasi")
    current = _version_or_404(db, user, OrgUnitInfo, "org_unit_id", unit_id,
                              body.valid_from, "Unit organisasi")
    fields_set = body.model_fields_set
    new_parent = body.parent_id if "parent_id" in fields_set else current.parent_id
    new_le = (body.legal_entity_id if body.legal_entity_id is not None
              else current.legal_entity_id)
    new_active = (body.is_active if "is_active" in fields_set else current.is_active)

    _validate_unit_refs(db, user, legal_entity_id=new_le,
                        parent_id=new_parent, valid_from=body.valid_from,
                        unit_id=unit_id)

    if current.is_active and not new_active:
        n = org_service.unit_has_active_assignments(
            db, user.tenant_id, unit_id, date.today()
        )
        if n > 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unit tidak bisa dinonaktifkan: masih ada {n} employment aktif "
                f"yang ditempatkan di unit ini. Pindahkan dulu karyawan tersebut "
                f"ke unit lain.",
            )
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=OrgUnitInfo,
            identity_field="org_unit_id", identity_value=unit_id,
            valid_from=body.valid_from,
            values={"name": body.name if body.name is not None else current.name,
                    "parent_id": new_parent,
                    "legal_entity_id": new_le,
                    "is_active": new_active},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "org_unit_info", ver.id,
           snapshot(ver, _OU_FIELDS), body.reason)
    db.commit()
    return ver


@router.get(
    "/org/units/{unit_id}/timeline",
    response_model=list[OrgUnitVersionOut],
    dependencies=_view_hist,
)
def timeline_org_unit(
    unit_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, OrgUnit, unit_id, "Unit organisasi")
    return org_service.version_timeline(db, user.tenant_id, OrgUnitInfo, unit_id)


@router.get(
    "/org/chart",
    response_model=list[OrgChartNode],
    dependencies=_view,
)
def get_org_chart(
    as_of: date = Query(default_factory=date.today, description="Format YYYY-MM-DD"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pohon hierarki unit aktif per tanggal (CHR-001: laporan per tanggal X
    memakai struktur saat itu; perubahan masa depan belum tampil)."""
    tree = org_service.build_chart(db, user.tenant_id, as_of)
    return [OrgChartNode.model_validate(n) for n in tree]


# ---------------------------------------------------------------------------
# Location berversi
# ---------------------------------------------------------------------------
_LOC_FIELDS = ["id", "location_id", "name", "timezone", "valid_from", "valid_to",
               "seq_no", "event", "event_reason"]


@router.post(
    "/org/locations",
    response_model=LocationVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def create_location(
    body: LocationCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    loc = Location(tenant_id=user.tenant_id)
    db.add(loc)
    db.flush()
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=LocationInfo,
            identity_field="location_id", identity_value=loc.id,
            valid_from=body.valid_from,
            values={"name": body.name, "timezone": body.timezone},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "location_info", ver.id,
           snapshot(ver, _LOC_FIELDS), body.reason)
    db.commit()
    return ver


@router.post(
    "/org/locations/{loc_id}/versions",
    response_model=LocationVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert,
)
def version_location(
    loc_id: uuid.UUID,
    body: LocationVersionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, Location, loc_id, "Lokasi")
    current = _version_or_404(db, user, LocationInfo, "location_id", loc_id,
                              body.valid_from, "Lokasi")
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=LocationInfo,
            identity_field="location_id", identity_value=loc_id,
            valid_from=body.valid_from,
            values={"name": body.name if body.name is not None else current.name,
                    "timezone": (body.timezone if body.timezone is not None
                                 else current.timezone)},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "location_info", ver.id,
           snapshot(ver, _LOC_FIELDS), body.reason)
    db.commit()
    return ver


@router.get(
    "/org/locations/{loc_id}/timeline",
    response_model=list[LocationVersionOut],
    dependencies=_view_hist,
)
def timeline_location(
    loc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, Location, loc_id, "Lokasi")
    return org_service.version_timeline(db, user.tenant_id, LocationInfo, loc_id)


# ---------------------------------------------------------------------------
# Cost center berversi
# ---------------------------------------------------------------------------
_CC_FIELDS = ["id", "cost_center_id", "code", "name", "org_unit_id", "is_active",
              "valid_from", "valid_to", "seq_no", "event", "event_reason"]


@router.post(
    "/org/cost-centers",
    response_model=CostCenterVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert_cc,
)
def create_cost_center(
    body: CostCenterCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.org_unit_id is not None:
        _identity_or_404(db, user, OrgUnit, body.org_unit_id, "Unit organisasi")
    cc = CostCenter(tenant_id=user.tenant_id)
    db.add(cc)
    db.flush()
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=CostCenterInfo,
            identity_field="cost_center_id", identity_value=cc.id,
            valid_from=body.valid_from,
            values={"code": body.code, "name": body.name,
                    "org_unit_id": body.org_unit_id, "is_active": True},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "cost_center_info", ver.id,
           snapshot(ver, _CC_FIELDS), body.reason)
    db.commit()
    return ver


@router.post(
    "/org/cost-centers/{cc_id}/versions",
    response_model=CostCenterVersionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_insert_cc,
)
def version_cost_center(
    cc_id: uuid.UUID,
    body: CostCenterVersionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, CostCenter, cc_id, "Cost center")
    current = _version_or_404(db, user, CostCenterInfo, "cost_center_id", cc_id,
                              body.valid_from, "Cost center")
    fields_set = body.model_fields_set
    new_ou = body.org_unit_id if "org_unit_id" in fields_set else current.org_unit_id
    if new_ou is not None:
        _identity_or_404(db, user, OrgUnit, new_ou, "Unit organisasi")
    try:
        ver = ed.insert_record(
            db=db, tenant_id=user.tenant_id, model=CostCenterInfo,
            identity_field="cost_center_id", identity_value=cc_id,
            valid_from=body.valid_from,
            values={"code": body.code if body.code is not None else current.code,
                    "name": body.name if body.name is not None else current.name,
                    "org_unit_id": new_ou,
                    "is_active": (body.is_active if "is_active" in fields_set
                                  else current.is_active)},
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
            event_applies_to="org",
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    _audit(db, user, request, "insert", "cost_center_info", ver.id,
           snapshot(ver, _CC_FIELDS), body.reason)
    db.commit()
    return ver


@router.get(
    "/org/cost-centers/{cc_id}/timeline",
    response_model=list[CostCenterVersionOut],
    dependencies=_view_cc_hist,
)
def timeline_cost_center(
    cc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _identity_or_404(db, user, CostCenter, cc_id, "Cost center")
    return org_service.version_timeline(db, user.tenant_id, CostCenterInfo, cc_id)


@router.get(
    "/org/cost-centers",
    response_model=list[CostCenterVersionOut],
    dependencies=_view_cc,
)
def list_cost_centers(
    as_of: date = Query(default_factory=date.today),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    out = []
    for cc in db.execute(
        select(CostCenter).where(CostCenter.tenant_id == user.tenant_id)
    ).scalars().all():
        ver = org_service.version_as_of(db, user.tenant_id, CostCenterInfo, cc.id,
                                        as_of)
        if ver is not None:
            out.append(ver)
    out.sort(key=lambda v: v.code)
    return out
