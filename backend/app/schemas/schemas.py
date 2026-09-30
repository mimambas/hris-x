"""Skema Pydantic v2 untuk API v1."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ Auth
class LoginRequest(BaseModel):
    tenant_slug: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    roles: list[str]


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    full_name: str
    is_superadmin: bool
    roles: list[str]


# ------------------------------------------------------------------ Tenant
class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool


# ------------------------------------------------------------------ Person / Employment
class PersonCreate(BaseModel):
    nik: str = Field(min_length=16, max_length=16, pattern=r"^\d{16}$")
    full_name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    nik: str
    full_name: str


class EmploymentCreate(BaseModel):
    person_id: uuid.UUID
    legal_entity_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    status: str = "active"
    reason: str = Field(min_length=1, max_length=500)


class EmploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    person_id: uuid.UUID
    legal_entity_id: uuid.UUID
    start_date: date
    end_date: date | None
    status: str


# ------------------------------------------------------------------ JobInfo / CompInfo
class JobInfoCreate(BaseModel):
    employment_id: uuid.UUID
    valid_from: date
    job_id: uuid.UUID
    org_unit_id: uuid.UUID
    location_id: uuid.UUID
    manager_employment_id: uuid.UUID | None = None
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class JobInfoCorrect(BaseModel):
    job_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    manager_employment_id: uuid.UUID | None = None
    event: str | None = Field(default=None, max_length=100)
    event_reason: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class JobInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    valid_from: date
    valid_to: date
    seq_no: int
    job_id: uuid.UUID
    org_unit_id: uuid.UUID
    location_id: uuid.UUID
    manager_employment_id: uuid.UUID | None
    event: str
    event_reason: str


class CompInfoCreate(BaseModel):
    employment_id: uuid.UUID
    valid_from: date
    pay_group: str = "Bulanan"
    components: dict = Field(default_factory=dict)  # nominal WAJIB integer rupiah
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class CompInfoCorrect(BaseModel):
    pay_group: str | None = None
    components: dict | None = None
    event: str | None = Field(default=None, max_length=100)
    event_reason: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class CompInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    valid_from: date
    valid_to: date
    seq_no: int
    pay_group: str
    components: dict
    event: str
    event_reason: str


# ------------------------------------------------------------------ RBAC
class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    population_rule: dict = Field(default_factory=lambda: {"type": "all"})
    reason: str = Field(min_length=1, max_length=500)


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    population_rule: dict


class AssignmentCreate(BaseModel):
    group_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)


class FieldPermissionCreate(BaseModel):
    object_name: str = Field(min_length=1, max_length=100)
    field_name: str = Field(default="*", max_length=100)
    can_view: bool = False
    can_view_history: bool = False
    can_insert: bool = False
    can_correct: bool = False
    can_delete: bool = False
    reason: str = Field(min_length=1, max_length=500)


class FieldPermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role_id: uuid.UUID
    object_name: str
    field_name: str
    can_view: bool
    can_view_history: bool
    can_insert: bool
    can_correct: bool
    can_delete: bool


# ------------------------------------------------------------------ Audit
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    object_type: str
    object_id: str | None
    old_values: dict | None
    new_values: dict | None
    reason: str | None
    channel: str
    ip: str | None
    created_at: datetime


# ------------------------------------------------------------------ Org (read)
class LegalEntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    npwp: str | None


class OrgUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    legal_entity_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    timezone: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    title: str


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    org_unit_id: uuid.UUID
    name: str
