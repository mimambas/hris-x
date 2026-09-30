"""Manajemen RBP: role, group, assignment, field permission."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.core.security import hash_password, validate_password_policy
from app.models import (
    FieldPermission,
    PermissionGroup,
    PermissionRole,
    Person,
    RoleAssignment,
    User,
)
from app.schemas.schemas import (
    AssignmentCreate,
    FieldPermissionCreate,
    FieldPermissionOut,
    GroupCreate,
    GroupOut,
    RoleCreate,
    RoleOut,
    UserCreate,
    UserOut,
)
from app.services.audit import write_audit

router = APIRouter(tags=["rbac"])


def _audit(db, user, request, action, object_type, object_id, new_values, reason):
    write_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        new_values=new_values,
        reason=reason,
        channel="api",
        ip=client_ip(request),
    )


@router.post(
    "/roles",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac", "insert"))],
)
def create_role(
    body: RoleCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.execute(
            select(PermissionRole).where(
                PermissionRole.tenant_id == user.tenant_id,
                PermissionRole.name == body.name,
            )
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nama role sudah dipakai")
    role = PermissionRole(
        tenant_id=user.tenant_id, name=body.name, description=body.description
    )
    db.add(role)
    db.flush()
    _audit(db, user, request, "create", "permission_role", role.id,
           snapshot(role, ["id", "name"]), body.reason)
    db.commit()
    return role


@router.get(
    "/roles",
    response_model=list[RoleOut],
    dependencies=[Depends(require_permission("rbac", "view"))],
)
def list_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(PermissionRole)
            .where(PermissionRole.tenant_id == user.tenant_id)
            .order_by(PermissionRole.name)
        )
        .scalars()
        .all()
    )


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac", "insert"))],
)
def create_user(
    body: UserCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Buat user login baru di tenant sendiri (Sprint 10).

    - Kebijakan password ditegakkan -> 422 bila lemah.
    - extra="forbid" di skema: field tak dikenal (mis. is_superadmin)
      ditolak 422 (anti mass assignment).
    - is_superadmin selalu False: user superadmin hanya dibuat via seed/
      operasi database langsung.
    """
    email = body.email.strip().lower()
    exists = (
        db.execute(
            select(User).where(
                User.tenant_id == user.tenant_id, User.email == email
            )
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email sudah dipakai")
    violations = validate_password_policy(body.password)
    if violations:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Password tidak memenuhi kebijakan: " + " ".join(violations),
        )
    person = None
    if body.person_id is not None:
        person = db.get(Person, body.person_id)
        if person is None or person.tenant_id != user.tenant_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Person tidak ditemukan")
    new_user = User(
        tenant_id=user.tenant_id,
        email=email,
        full_name=body.full_name.strip(),
        password_hash=hash_password(body.password),
        person_id=person.id if person else None,
        is_superadmin=False,
    )
    db.add(new_user)
    db.flush()
    _audit(db, user, request, "create", "user", new_user.id,
           snapshot(new_user, ["id", "email", "full_name", "person_id"]),
           body.reason)
    db.commit()
    return new_user


@router.post(
    "/groups",
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac", "insert"))],
)
def create_group(
    body: GroupCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = (
        db.execute(
            select(PermissionGroup).where(
                PermissionGroup.tenant_id == user.tenant_id,
                PermissionGroup.name == body.name,
            )
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nama group sudah dipakai")
    rule = body.population_rule or {"type": "all"}
    if not isinstance(rule, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "population_rule harus objek JSON"
        )
    group = PermissionGroup(
        tenant_id=user.tenant_id, name=body.name, population_rule=rule
    )
    db.add(group)
    db.flush()
    _audit(db, user, request, "create", "permission_group", group.id,
           snapshot(group, ["id", "name", "population_rule"]), body.reason)
    db.commit()
    return group


@router.get(
    "/groups",
    response_model=list[GroupOut],
    dependencies=[Depends(require_permission("rbac", "view"))],
)
def list_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.execute(
            select(PermissionGroup)
            .where(PermissionGroup.tenant_id == user.tenant_id)
            .order_by(PermissionGroup.name)
        )
        .scalars()
        .all()
    )


@router.post(
    "/roles/{role_id}/assign",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac", "insert"))],
)
def assign_role_to_group(
    role_id: uuid.UUID,
    body: AssignmentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.get(PermissionRole, role_id)
    group = db.get(PermissionGroup, body.group_id)
    if role is None or role.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role tidak ditemukan")
    if group is None or group.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group tidak ditemukan")
    exists = (
        db.execute(
            select(RoleAssignment).where(
                RoleAssignment.role_id == role.id, RoleAssignment.group_id == group.id
            )
        )
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Assignment sudah ada")
    pop = body.target_population or {"type": "all"}
    if not isinstance(pop, dict) or pop.get("type") not in ("all", "self", "team"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "target_population.type harus 'all', 'self', atau 'team'",
        )
    assignment = RoleAssignment(
        tenant_id=user.tenant_id,
        role_id=role.id,
        group_id=group.id,
        target_population=pop,
    )
    db.add(assignment)
    db.flush()
    _audit(db, user, request, "create", "role_assignment", assignment.id,
           {"role_id": str(role.id), "group_id": str(group.id),
            "target_population": pop}, body.reason)
    db.commit()
    return {"id": str(assignment.id)}


@router.post(
    "/roles/{role_id}/field-permissions",
    response_model=FieldPermissionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac", "insert"))],
)
def grant_field_permission(
    role_id: uuid.UUID,
    body: FieldPermissionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.get(PermissionRole, role_id)
    if role is None or role.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role tidak ditemukan")
    perm = FieldPermission(
        tenant_id=user.tenant_id,
        role_id=role.id,
        object_name=body.object_name,
        field_name=body.field_name,
        can_view=body.can_view,
        can_view_history=body.can_view_history,
        can_insert=body.can_insert,
        can_correct=body.can_correct,
        can_delete=body.can_delete,
    )
    db.add(perm)
    db.flush()
    _audit(db, user, request, "create", "field_permission", perm.id,
           snapshot(perm, ["id", "role_id", "object_name", "field_name",
                           "can_view", "can_view_history", "can_insert",
                           "can_correct", "can_delete"]), body.reason)
    db.commit()
    return perm


@router.get(
    "/roles/{role_id}/field-permissions",
    response_model=list[FieldPermissionOut],
    dependencies=[Depends(require_permission("rbac", "view"))],
)
def list_field_permissions(
    role_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = db.get(PermissionRole, role_id)
    if role is None or role.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role tidak ditemukan")
    return (
        db.execute(
            select(FieldPermission).where(
                FieldPermission.tenant_id == user.tenant_id,
                FieldPermission.role_id == role.id,
            )
        )
        .scalars()
        .all()
    )
