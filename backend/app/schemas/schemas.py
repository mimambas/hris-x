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
    # {"type": "all"|"self"|"team"} — default "all" (perilaku S1).
    target_population: dict = Field(default_factory=lambda: {"type": "all"})
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


# ------------------------------------------------------------------ Org bertanggal efektif (Sprint 2)
class OrgVersionBase(BaseModel):
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)  # alasan audit


class LegalEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    npwp: str | None = Field(default=None, max_length=32)
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class LegalEntityVersionCreate(OrgVersionBase):
    name: str | None = Field(default=None, max_length=200)
    npwp: str | None = Field(default=None, max_length=32)


class LegalEntityVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    legal_entity_id: uuid.UUID
    name: str
    npwp: str | None
    valid_from: date
    valid_to: date
    seq_no: int
    event: str
    event_reason: str


class OrgUnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    legal_entity_id: uuid.UUID
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class OrgUnitVersionCreate(OrgVersionBase):
    name: str | None = Field(default=None, max_length=200)
    parent_id: uuid.UUID | None = None
    legal_entity_id: uuid.UUID | None = None
    is_active: bool | None = None


class OrgUnitVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    org_unit_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    legal_entity_id: uuid.UUID
    is_active: bool
    valid_from: date
    valid_to: date
    seq_no: int
    event: str
    event_reason: str


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="Asia/Jakarta", max_length=50)
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class LocationVersionCreate(OrgVersionBase):
    name: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=50)


class LocationVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    location_id: uuid.UUID
    name: str
    timezone: str
    valid_from: date
    valid_to: date
    seq_no: int
    event: str
    event_reason: str


class CostCenterCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    org_unit_id: uuid.UUID | None = None
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class CostCenterVersionCreate(OrgVersionBase):
    code: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=200)
    org_unit_id: uuid.UUID | None = None
    is_active: bool | None = None


class CostCenterVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    cost_center_id: uuid.UUID
    code: str
    name: str
    org_unit_id: uuid.UUID | None
    is_active: bool
    valid_from: date
    valid_to: date
    seq_no: int
    event: str
    event_reason: str


class OrgChartLegalEntity(BaseModel):
    id: uuid.UUID
    name: str | None


class OrgChartNode(BaseModel):
    id: uuid.UUID
    name: str
    legal_entity: OrgChartLegalEntity
    children: list["OrgChartNode"] = Field(default_factory=list)


OrgChartNode.model_rebuild()


# ------------------------------------------------------------------ Custom field (Sprint 2)
class CustomFieldDefinitionCreate(BaseModel):
    object_name: str = Field(min_length=1, max_length=100)
    field_key: str = Field(min_length=1, max_length=50)
    label_id: str = Field(min_length=1, max_length=200)
    label_en: str | None = Field(default=None, max_length=200)
    field_type: str = Field(min_length=1, max_length=20)
    required: bool = False
    options: list | dict = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=500)


class CustomFieldDefinitionUpdate(BaseModel):
    label_id: str | None = Field(default=None, max_length=200)
    label_en: str | None = Field(default=None, max_length=200)
    required: bool | None = None
    options: list | dict | None = None
    is_active: bool | None = None
    reason: str = Field(min_length=1, max_length=500)


class CustomFieldDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    object_name: str
    field_key: str
    label_id: str
    label_en: str | None
    field_type: str
    required: bool
    options: list | dict
    is_active: bool


class CustomFieldValueSet(BaseModel):
    definition_id: uuid.UUID
    record_id: uuid.UUID
    value: str | int | float | None = None
    reason: str = Field(min_length=1, max_length=500)


class CustomFieldValueOut(BaseModel):
    field_key: str
    label_id: str
    label_en: str | None
    field_type: str
    value: str | None
    definition_active: bool
