"""Target population per-user (Sprint 2, PRD 15.5).

Permission role (APA) x granted group (SIAPA) -> target population (DATA SIAPA).
Didefinisikan di RoleAssignment.target_population:

  {"type": "all"}  — seluruh data tenant (default; perilaku S1)
  {"type": "self"} — hanya record milik user sendiri
  {"type": "team"} — direct report: employment yang manager_employment_id-nya
                     (per JobInfo yang berlaku hari ini) adalah employment user

Semantik gabungan: bila SALAH SATU assignment memberi "all", user melihat
semua; selain itu hasilnya adalah gabungan (union) himpunan self/team dari
semua assignment yang grupnya cocok.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Employment,
    FieldPermission,
    JobInfo,
    PermissionGroup,
    RoleAssignment,
)
from app.services import effective_dating as ed
from app.services import rbp as rbp_service


def _role_can_view(db: Session, user, role_id, object_name: str) -> bool:
    """Izin view object-level untuk satu role (cermin has_permission S1)."""
    perms = (
        db.execute(
            select(FieldPermission).where(
                FieldPermission.tenant_id == user.tenant_id,
                FieldPermission.role_id == role_id,
                FieldPermission.object_name.in_([object_name, "*"]),
            )
        )
        .scalars()
        .all()
    )
    return any(bool(p.can_view) for p in perms)


def _user_population_types(db: Session, user, object_name: str) -> set[str]:
    """Kumpulan tipe target population dari assignment yang berlaku DAN
    rolenya memberi izin view pada object_name.

    Assignment yang rolenya tidak punya izin view objek ini diabaikan:
    target population hanya membatasi data yang memang boleh dilihat
    (default-deny tetap berlaku)."""
    types: set[str] = set()
    groups = {
        g.id: g
        for g in db.execute(
            select(PermissionGroup).where(
                PermissionGroup.tenant_id == user.tenant_id
            )
        )
        .scalars()
        .all()
    }
    assignments = (
        db.execute(
            select(RoleAssignment).where(
                RoleAssignment.tenant_id == user.tenant_id
            )
        )
        .scalars()
        .all()
    )
    for a in assignments:
        group = groups.get(a.group_id)
        if group is None:
            continue
        if not rbp_service.is_group_member(db, group, user):
            continue
        if not _role_can_view(db, user, a.role_id, object_name):
            continue
        pop = a.target_population or {"type": "all"}
        types.add(pop.get("type", "all"))
    return types


def get_user_employment(db: Session, user):
    """Employment terbaru user (per start_date), atau None."""
    if user.person_id is None:
        return None
    return (
        db.execute(
            select(Employment)
            .where(
                Employment.tenant_id == user.tenant_id,
                Employment.person_id == user.person_id,
            )
            .order_by(Employment.start_date.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def get_visible_person_ids(db: Session, user) -> set | None:
    """Himpunan person id yang boleh dilihat user, atau None = semua.

    Superadmin selalu None (melihat semua).
    """
    if user.is_superadmin:
        return None
    types = _user_population_types(db, user, "person")
    if not types or "all" in types:
        return None
    visible: set = set()
    today = date.today()
    if "self" in types and user.person_id is not None:
        visible.add(user.person_id)
    if "team" in types:
        emp = get_user_employment(db, user)
        if emp is not None:
            emps = (
                db.execute(
                    select(Employment).where(
                        Employment.tenant_id == user.tenant_id,
                        Employment.status == "active",
                    )
                )
                .scalars()
                .all()
            )
            for e in emps:
                job = ed.as_of(
                    db=db,
                    tenant_id=user.tenant_id,
                    model=JobInfo,
                    identity_field="employment_id",
                    identity_value=e.id,
                    as_of_date=today,
                )
                if (
                    job is not None
                    and job.manager_employment_id is not None
                    and str(job.manager_employment_id) == str(emp.id)
                ):
                    visible.add(e.person_id)
    return visible


def can_view_person(db: Session, user, person_id) -> bool:
    """True bila person_id berada dalam target population user."""
    visible = get_visible_person_ids(db, user)
    if visible is None:
        return True
    return any(str(pid) == str(person_id) for pid in visible)
