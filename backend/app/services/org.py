"""Operasi struktur organisasi bertanggal efektif (Sprint 2, CHR-001).

- Versi org (nama, parent, legal entity, status aktif) disimpan di tabel
  *Info lewat layanan effective_dating generik (ADR-0001); tidak ada
  logika tanggal ganda di sini.
- build_chart: pohon hierarki per tanggal (laporan "per tanggal X", CHR-001).
- assert_no_cycle: cegah parent sirkular saat pindah unit.
- unit_has_active_assignments: dipakai validasi penonaktifan unit.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CostCenter,
    CostCenterInfo,
    Employment,
    JobInfo,
    LegalEntity,
    LegalEntityInfo,
    Location,
    LocationInfo,
    OrgUnit,
    OrgUnitInfo,
)
from app.services import effective_dating as ed

# identity_field per tabel info.
_INFO_IDENTITY = {
    OrgUnitInfo: "org_unit_id",
    LegalEntityInfo: "legal_entity_id",
    LocationInfo: "location_id",
    CostCenterInfo: "cost_center_id",
}


def version_as_of(db: Session, tenant_id, info_model, identity_value, as_of_date: date):
    """Versi info yang berlaku pada tanggal tertentu."""
    return ed.as_of(
        db=db,
        tenant_id=tenant_id,
        model=info_model,
        identity_field=_INFO_IDENTITY[info_model],
        identity_value=identity_value,
        as_of_date=as_of_date,
    )


def version_timeline(db: Session, tenant_id, info_model, identity_value) -> list:
    return ed.timeline(
        db=db,
        tenant_id=tenant_id,
        model=info_model,
        identity_field=_INFO_IDENTITY[info_model],
        identity_value=identity_value,
    )


def _identity_exists(db: Session, tenant_id, model, identity_id) -> bool:
    row = db.get(model, identity_id)
    return row is not None and row.tenant_id == tenant_id


def assert_no_cycle(
    db: Session, tenant_id, org_unit_id, new_parent_id, as_of_date: date
) -> None:
    """Pastikan new_parent_id bukan diri sendiri / turunan unit tersebut.

    Melempar ValueError bila sirkular.
    """
    if new_parent_id is None:
        return
    if str(new_parent_id) == str(org_unit_id):
        raise ValueError("Unit tidak boleh menjadi parent bagi dirinya sendiri")
    if not _identity_exists(db, tenant_id, OrgUnit, new_parent_id):
        raise ValueError("Parent unit tidak ditemukan di tenant ini")
    # Telusuri rantai parent ke atas dari calon parent; bila mencapai
    # org_unit_id berarti sirkular.
    seen = set()
    current = new_parent_id
    while current is not None:
        key = str(current)
        if key == str(org_unit_id):
            raise ValueError(
                "Parent sirkular: calon parent adalah turunan dari unit ini"
            )
        if key in seen:
            break  # data lama rusak; hentikan agar tidak infinite loop
        seen.add(key)
        ver = version_as_of(db, tenant_id, OrgUnitInfo, current, as_of_date)
        current = ver.parent_id if ver is not None else None


def unit_has_active_assignments(
    db: Session, tenant_id, org_unit_id, as_of_date: date
) -> int:
    """Jumlah employment aktif yang penempatannya (JobInfo per tanggal)
    menunjuk ke unit ini. Dipakai menolak penonaktifan unit berpenghuni."""
    emps = (
        db.execute(
            select(Employment).where(
                Employment.tenant_id == tenant_id,
                Employment.status == "active",
            )
        )
        .scalars()
        .all()
    )
    count = 0
    for emp in emps:
        job = ed.as_of(
            db=db,
            tenant_id=tenant_id,
            model=JobInfo,
            identity_field="employment_id",
            identity_value=emp.id,
            as_of_date=as_of_date,
        )
        if job is not None and str(job.org_unit_id) == str(org_unit_id):
            count += 1
    return count


def build_chart(db: Session, tenant_id, as_of_date: date) -> list[dict]:
    """Pohon unit aktif per tanggal: roots (parent None) + children rekursif.

    Setiap node: id (identitas stabil), name, legal_entity {id, name},
    children [...]. Diurut nama per level agar deterministik.
    """
    units = (
        db.execute(select(OrgUnit).where(OrgUnit.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    nodes: dict[str, dict] = {}
    parent_of: dict[str, str | None] = {}
    children_of: dict[str | None, list[str]] = {}
    for unit in units:
        ver = version_as_of(db, tenant_id, OrgUnitInfo, unit.id, as_of_date)
        if ver is None or not ver.is_active:
            continue
        le_name: str | None = None
        le_ver = version_as_of(
            db, tenant_id, LegalEntityInfo, ver.legal_entity_id, as_of_date
        )
        if le_ver is not None:
            le_name = le_ver.name
        key = str(unit.id)
        nodes[key] = {
            "id": unit.id,
            "name": ver.name,
            "legal_entity": {"id": ver.legal_entity_id, "name": le_name},
            "children": [],
        }
        parent_key = str(ver.parent_id) if ver.parent_id is not None else None
        parent_of[key] = parent_key
        children_of.setdefault(parent_key, []).append(key)

    attached: set[str] = set()

    def attach(parent_key: str | None) -> list[dict]:
        result = []
        for child_key in sorted(
            children_of.get(parent_key, []), key=lambda k: nodes[k]["name"]
        ):
            node = nodes[child_key]
            attached.add(child_key)
            node["children"] = attach(child_key)
            result.append(node)
        return result

    roots = attach(None)
    # Unit yatim (parent-nya tidak aktif / tidak punya versi pada tanggal
    # itu) ditampilkan sebagai root agar tidak hilang dari chart.
    for key in sorted(nodes, key=lambda k: nodes[k]["name"]):
        parent_key = parent_of[key]
        if key not in attached and parent_key is not None and parent_key not in nodes:
            roots.append(nodes[key])
            attached.add(key)
    roots.sort(key=lambda n: n["name"])
    return roots
