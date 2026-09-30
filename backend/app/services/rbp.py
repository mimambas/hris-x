"""Evaluasi RBP tiga sumbu (PRD 15.5).

role (APA) x group (SIAPA, dinamis) -> target population (data SIAPA).

Keanggotaan grup dinamis dievaluasi saat request dari population_rule
terhadap JobInfo user yang berlaku hari ini. Default DENY: tanpa role
yang cocok, semua aksi ditolak.
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
    PermissionRole,
    RoleAssignment,
)
from app.services import effective_dating as ed

ACTION_FLAG = {
    "view": "can_view",
    "view_history": "can_view_history",
    "insert": "can_insert",
    "correct": "can_correct",
    "delete": "can_delete",
}

# Field JobInfo yang boleh dipakai di population_rule.
_GROUP_CONTEXT_FIELDS = {"location_id", "org_unit_id", "job_id", "legal_entity_id"}


def get_user_context(db: Session, user) -> dict | None:
    """Konteks employment user untuk evaluasi grup dinamis.

    Mengembalikan dict berisi location_id/org_unit_id/job_id/legal_entity_id
    dari JobInfo yang berlaku hari ini, atau None bila user tidak terikat
    ke Person/Employment aktif.
    """
    if user.person_id is None:
        return None
    today = date.today()
    emp = (
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
    if emp is None:
        return None
    if emp.end_date is not None and emp.end_date < today:
        return None
    job = ed.as_of(
        db=db,
        tenant_id=user.tenant_id,
        model=JobInfo,
        identity_field="employment_id",
        identity_value=emp.id,
        as_of_date=today,
    )
    ctx = {"legal_entity_id": str(emp.legal_entity_id)}
    if job is not None:
        ctx.update(
            {
                "location_id": str(job.location_id),
                "org_unit_id": str(job.org_unit_id),
                "job_id": str(job.job_id),
            }
        )
    return ctx


def is_group_member(db: Session, group: PermissionGroup, user) -> bool:
    rule = group.population_rule or {"type": "all"}
    if rule.get("type") == "all":
        return True
    field = rule.get("field")
    if field not in _GROUP_CONTEXT_FIELDS:
        return False
    ctx = get_user_context(db, user)
    if ctx is None or field not in ctx:
        return False
    op = rule.get("op", "=")
    actual = ctx[field]
    if op == "=":
        return actual == str(rule.get("value"))
    if op == "in":
        return actual in {str(v) for v in rule.get("value", [])}
    return False


def get_user_roles(db: Session, user) -> list[PermissionRole]:
    """Semua role user dari assignment yang grupnya cocok (dinamis)."""
    assignments = (
        db.execute(
            select(RoleAssignment).where(RoleAssignment.tenant_id == user.tenant_id)
        )
        .scalars()
        .all()
    )
    groups = {
        g.id: g
        for g in db.execute(
            select(PermissionGroup).where(PermissionGroup.tenant_id == user.tenant_id)
        )
        .scalars()
        .all()
    }
    roles: dict = {}
    for a in assignments:
        group = groups.get(a.group_id)
        if group is None:
            continue
        if not is_group_member(db, group, user):
            continue
        role = db.get(PermissionRole, a.role_id)
        if role is not None and role.tenant_id == user.tenant_id:
            roles[role.id] = role
    return list(roles.values())


def has_permission(db: Session, user, object_name: str, action: str) -> bool:
    """True bila user punya izin action pada object_name via salah satu role-nya.

    Superadmin selalu lolos. Baris FieldPermission dengan field_name="*"
    berlaku object-level.
    """
    if user.is_superadmin:
        return True
    flag = ACTION_FLAG.get(action)
    if flag is None:
        return False
    for role in get_user_roles(db, user):
        perms = (
            db.execute(
                select(FieldPermission).where(
                    FieldPermission.tenant_id == user.tenant_id,
                    FieldPermission.role_id == role.id,
                    FieldPermission.object_name.in_([object_name, "*"]),
                )
            )
            .scalars()
            .all()
        )
        if any(getattr(p, flag) for p in perms):
            return True
    return False
