"""Skema Pydantic v2 untuk API v1."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.services.validation import (
    validate_bank_account,
    validate_birth_date,
    validate_bpjs,
    validate_email,
    validate_nik,
    validate_npwp,
    validate_ptkp,
)

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
    birth_place: str | None = Field(default=None, max_length=120)
    birth_date: date | None = None
    email: str | None = None
    npwp: str | None = None
    ptkp: str = "TK/0"
    bpjs_kes_no: str | None = None
    bpjs_tk_no: str | None = None
    bank_name: str | None = Field(default=None, max_length=100)
    bank_account_no: str | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("nik")
    @classmethod
    def _nik_valid(cls, v: str) -> str:
        return validate_nik(v)

    @field_validator("npwp")
    @classmethod
    def _npwp_valid(cls, v: str | None) -> str | None:
        return validate_npwp(v)

    @field_validator("ptkp")
    @classmethod
    def _ptkp_valid(cls, v: str) -> str:
        return validate_ptkp(v)

    @field_validator("email")
    @classmethod
    def _email_valid(cls, v: str | None) -> str | None:
        return validate_email(v)

    @field_validator("bpjs_kes_no")
    @classmethod
    def _bpjs_kes_valid(cls, v: str | None) -> str | None:
        return validate_bpjs(v, "BPJS Kesehatan")

    @field_validator("bpjs_tk_no")
    @classmethod
    def _bpjs_tk_valid(cls, v: str | None) -> str | None:
        return validate_bpjs(v, "BPJS Ketenagakerjaan")

    @field_validator("bank_account_no")
    @classmethod
    def _bank_acc_valid(cls, v: str | None) -> str | None:
        return validate_bank_account(v)

    @field_validator("birth_date")
    @classmethod
    def _birth_date_valid(cls, v: date | None) -> date | None:
        return validate_birth_date(v)


class PersonUpdate(BaseModel):
    """PATCH person. PTKP sengaja TIDAK ada di sini: perubahan PTKP wajib
    lewat POST /persons/{id}/ptkp-change agar versi CompInfo ikut dibuat."""

    model_config = ConfigDict(extra="forbid")

    nik: str | None = Field(default=None, min_length=16, max_length=16,
                            pattern=r"^\d{16}$")
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    birth_place: str | None = Field(default=None, max_length=120)
    birth_date: date | None = None
    email: str | None = None
    npwp: str | None = None
    bpjs_kes_no: str | None = None
    bpjs_tk_no: str | None = None
    bank_name: str | None = Field(default=None, max_length=100)
    bank_account_no: str | None = None
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("nik")
    @classmethod
    def _nik_valid(cls, v: str | None) -> str | None:
        return validate_nik(v) if v is not None else None

    @field_validator("npwp")
    @classmethod
    def _npwp_valid(cls, v: str | None) -> str | None:
        return validate_npwp(v)

    @field_validator("email")
    @classmethod
    def _email_valid(cls, v: str | None) -> str | None:
        return validate_email(v)

    @field_validator("bpjs_kes_no")
    @classmethod
    def _bpjs_kes_valid(cls, v: str | None) -> str | None:
        return validate_bpjs(v, "BPJS Kesehatan")

    @field_validator("bpjs_tk_no")
    @classmethod
    def _bpjs_tk_valid(cls, v: str | None) -> str | None:
        return validate_bpjs(v, "BPJS Ketenagakerjaan")

    @field_validator("bank_account_no")
    @classmethod
    def _bank_acc_valid(cls, v: str | None) -> str | None:
        return validate_bank_account(v)

    @field_validator("birth_date")
    @classmethod
    def _birth_date_valid(cls, v: date | None) -> date | None:
        return validate_birth_date(v)


class PtkpChangeRequest(BaseModel):
    """Perubahan status PTKP: update Person.ptkp + sisipkan versi CompInfo baru
    (event=data_update) agar PPh 21 memakai PTKP baru mulai tanggal efektif."""

    ptkp: str
    effective_date: date
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("ptkp")
    @classmethod
    def _ptkp_valid(cls, v: str) -> str:
        return validate_ptkp(v)


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    nik: str
    full_name: str
    birth_place: str | None
    birth_date: date | None
    email: str | None
    npwp: str | None
    ptkp: str
    bpjs_kes_no: str | None
    bpjs_tk_no: str | None
    bank_name: str | None
    bank_account_no: str | None


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
    ptkp: str
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


# ------------------------------------------------------------------ Lifecycle (CHR-002)
class EventReasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reason: str
    is_active: bool


class LifecycleEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    applies_to: str
    is_active: bool
    reasons: list[EventReasonOut] = []


class LifecycleEventCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    applies_to: str = Field(default="lifecycle", pattern=r"^(lifecycle|org)$")
    reasons: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=500)


class LifecycleEventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    reasons: list[str] | None = None  # ganti seluruh daftar alasan
    reason: str = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------ Kontrak (CHR-006)
class ContractCreate(BaseModel):
    employment_id: uuid.UUID
    contract_type: str = Field(pattern=r"^(?i)(pkwt|pkwtt)$")
    contract_number: str | None = Field(default=None, max_length=80)
    start_date: date
    end_date: date | None = None  # wajib untuk PKWT
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class ContractVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    contract_id: uuid.UUID
    contract_type: str
    contract_number: str
    valid_from: date
    valid_to: date
    seq_no: int
    event: str
    event_reason: str


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    current_version: ContractVersionOut | None = None
    versions: list[ContractVersionOut] = []


class ContractExtendRequest(BaseModel):
    new_end_date: date
    new_contract_number: str | None = Field(default=None, max_length=80)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class ContractConvertRequest(BaseModel):
    effective_date: date | None = None  # default: hari setelah versi berjalan berakhir
    new_contract_number: str | None = Field(default=None, max_length=80)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class ContractPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tenant_id: uuid.UUID
    max_pkwt_months: int
    max_extensions: int


class ContractPolicyUpdate(BaseModel):
    max_pkwt_months: int | None = Field(default=None, ge=1, le=120)
    max_extensions: int | None = Field(default=None, ge=0, le=10)
    reason: str = Field(min_length=1, max_length=500)


# ------------------------------------------------------------------ Impor Excel (CHR-007)
class ImportRowError(BaseModel):
    field: str
    message: str


class ImportRowReport(BaseModel):
    row_number: int  # nomor baris di Excel (1-based, termasuk header)
    status: str  # "valid" | "invalid"
    errors: list[ImportRowError] = []
    preview: dict = {}  # nik + nama untuk identifikasi cepat


class ImportDryRunResponse(BaseModel):
    filename: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: list[ImportRowReport] = []  # hanya baris invalid (ringkas)


class ImportCommitResponse(BaseModel):
    filename: str
    imported: int
    person_ids: list[uuid.UUID] = []


# ------------------------------------------------------------------ Dokumen (CHR-012 dasar)
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    person_id: uuid.UUID | None
    employment_id: uuid.UUID | None
    doc_type: str
    file_name: str
    mime_type: str
    size_bytes: int
    version: int
    is_current: bool
    notes: str | None


# ------------------------------------------------------------------ Payroll (Sprint 4)
class SalaryComponentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=60)  # kosong -> otomatis
    kind: str = Field(pattern=r"^(earning|deduction)$")
    calc_type: str = Field(pattern=r"^(fixed|formula)$")
    amount_or_formula: str = Field(min_length=1)  # integer rupiah | ekspresi
    is_taxable: bool = True
    is_bpjs_base: bool = False
    sequence: int = Field(default=100, ge=0, le=10000)
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class SalaryComponentVersionCreate(BaseModel):
    kind: str | None = Field(default=None, pattern=r"^(earning|deduction)$")
    calc_type: str | None = Field(default=None, pattern=r"^(fixed|formula)$")
    amount_or_formula: str | None = None
    is_taxable: bool | None = None
    is_bpjs_base: bool | None = None
    sequence: int | None = Field(default=None, ge=0, le=10000)
    valid_from: date
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class SalaryComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    kind: str | None = None
    calc_type: str | None = None
    amount_or_formula: str | None = None
    is_taxable: bool | None = None
    is_bpjs_base: bool | None = None
    sequence: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class CompAssignmentCreate(BaseModel):
    employment_id: uuid.UUID
    component_id: uuid.UUID
    valid_from: date
    override_amount: int | None = Field(default=None, ge=0)
    is_enabled: bool = True
    event: str = Field(min_length=1, max_length=100)
    event_reason: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=500)


class CompAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    component_id: uuid.UUID
    component_code: str | None = None
    override_amount: int | None = None
    is_enabled: bool | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class PayrollPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    pph21_method: str
    thr_basis: str


class PayrollPolicyUpdate(BaseModel):
    pph21_method: str | None = Field(default=None,
                                     pattern=r"^(gross|gross_up|net)$")
    thr_basis: str | None = Field(default=None,
                                  pattern=r"^(gaji_pokok|total_fixed)$")
    reason: str = Field(min_length=1, max_length=500)


class PayrollRunCreate(BaseModel):
    period: str = Field(min_length=7, max_length=7)  # "YYYY-MM"
    pph21_method: str | None = Field(default=None,
                                     pattern=r"^(gross|gross_up|net)$")
    include_thr: bool = False
    thr_holiday_date: date | None = None
    overtime_hours: dict[str, int] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)


class PayrollLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    person_name: str
    nik: str
    ptkp: str
    breakdown: dict
    inputs_snapshot: dict = {}
    gross: int
    total_deductions: int
    pph21: int
    pph21_borne_by: str
    thr_amount: int
    retro_amount: int
    retro_detail: dict
    take_home_pay: int
    employer_cost: dict
    bank_name: str | None
    bank_account_no: str | None
    validation_errors: list


class PayrollRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    period: str
    status: str
    pph21_method: str
    include_thr: bool
    totals: dict
    headcount: int
    created_at: datetime
    locked_at: datetime | None


# ------------------------------------------------------------------ Sprint 5: absensi, cuti, lembur
class ShiftCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    start_time: str = Field(min_length=5, max_length=5)  # "HH:MM"
    end_time: str = Field(min_length=5, max_length=5)
    is_overnight: bool = False
    grace_minutes: int = Field(default=15, ge=0, le=120)


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    is_overnight: bool
    grace_minutes: int
    is_active: bool


class ShiftAssignRequest(BaseModel):
    employment_id: uuid.UUID
    shift_id: uuid.UUID
    valid_from: date
    valid_to: date | None = None
    reason: str = Field(min_length=1, max_length=500)


class ShiftAssignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    shift_id: uuid.UUID
    valid_from: date
    valid_to: date


class CheckInOutRequest(BaseModel):
    employment_id: uuid.UUID
    at: datetime | None = None  # default: sekarang
    source: str = Field(default="web", pattern=r"^(mobile|web|manual|machine)$")
    reason: str = Field(default="", max_length=500)


class AttendanceCorrectRequest(BaseModel):
    check_in: datetime | None = None
    check_out: datetime | None = None
    reason: str = Field(min_length=1, max_length=500)


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    date: date
    version: int
    check_in: datetime | None
    check_out: datetime | None
    source: str
    status: str
    late_minutes: int
    early_leave_minutes: int
    work_minutes: int
    correction_reason: str | None


class HolidayCreate(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=200)
    is_cuti_bersama: bool = False
    deducts_leave: bool = True


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    date: date
    name: str
    is_cuti_bersama: bool
    deducts_leave: bool
    mass_leave_applied: bool = False


class LeaveTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    quota_days: int = Field(default=12, ge=0, le=365)
    accrual: str = Field(default="none", pattern=r"^(none|monthly)$")
    min_service_months: int = Field(default=0, ge=0, le=120)
    requires_doc: bool = False
    deducts_balance: bool = True


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    quota_days: int
    accrual: str
    min_service_months: int
    requires_doc: bool
    deducts_balance: bool
    is_active: bool


class LeaveBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    leave_type_id: uuid.UUID
    leave_type_code: str = ""
    year: int
    entitled: int
    used: int
    remaining: int


class LeaveRequestCreate(BaseModel):
    employment_id: uuid.UUID
    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    days: int
    reason: str | None
    status: str
    l1_approved_at: datetime | None
    l2_approved_at: datetime | None
    rejection_reason: str | None


class LeaveDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)  # wajib saat reject


class LeavePolicyUpdate(BaseModel):
    max_consecutive_days: int | None = Field(default=None, ge=1, le=365)
    blackout_dates: list[dict] | None = None
    reason: str = Field(min_length=1, max_length=500)


class LeavePolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    max_consecutive_days: int
    blackout_dates: list


class AttendancePolicyUpdate(BaseModel):
    grace_minutes: int | None = Field(default=None, ge=0, le=120)
    deduct_absent: bool | None = None
    reason: str = Field(min_length=1, max_length=500)


class AttendancePolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    grace_minutes: int
    deduct_absent: bool


class OvertimeRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    first_hour_mult: float
    next_hour_mult: float
    divisor: int


class OvertimeRequestCreate(BaseModel):
    employment_id: uuid.UUID
    date: date
    start_time: str = Field(min_length=5, max_length=5)  # "HH:MM"
    end_time: str = Field(min_length=5, max_length=5)
    reason: str | None = Field(default=None, max_length=500)


class OvertimeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employment_id: uuid.UUID
    date: date
    hours: float
    reason: str | None
    status: str
    pay_amount: int
    rejection_reason: str | None
