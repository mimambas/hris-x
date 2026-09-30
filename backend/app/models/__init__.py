"""Model SQLAlchemy 2.0 untuk fondasi Sprint 1 HRIS-X.

Konvensi (PRD 18.4):
- Semua tabel bisnis punya tenant_id.
- Primary key UUIDv7 (terurut waktu).
- Uang = integer rupiah / numeric presisi tetap, tidak pernah float
  (dipakai di CompInfo.components sebagai integer).
- Hapus data = soft delete + audit (belum ada kebutuhan hapus di S1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import uuid7

MAX_DATE = date(9999, 12, 31)


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid7)


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)


# ---------------------------------------------------------------------------
# Tenant & User
# ---------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    nik: Mapped[str] = mapped_column(String(16), nullable=False)  # NIK 16 digit, unik per tenant
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # --- Data identitas Indonesia (Sprint 3, CHR-005) ---
    birth_place: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    npwp: Mapped[str | None] = mapped_column(String(16), nullable=True)  # format baru 16 digit
    ptkp: Mapped[str] = mapped_column(String(4), nullable=False, default="TK/0")
    bpjs_kes_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bpjs_tk_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nik", name="uq_persons_tenant_nik"),
        # Unik per tenant bila diisi; NULL tetap boleh ganda (SQLite & Postgres).
        UniqueConstraint("tenant_id", "email", name="uq_persons_tenant_email"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Tautan ke Person agar grup dinamis bisa dievaluasi dari data employment user.
    # Nullable: akun admin/sistem boleh tidak terikat ke Person.
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("persons.id"), nullable=True
    )
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )


# ---------------------------------------------------------------------------
# RBP tiga sumbu (PRD 15.5): role x group -> target population
# ---------------------------------------------------------------------------
class PermissionRole(Base):
    """Permission role: APA yang boleh dilakukan."""

    __tablename__ = "permission_roles"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
    )


class PermissionGroup(Base):
    """Granted group: SIAPA. Keanggotaan dinamis via population_rule (JSON).

    Contoh population_rule:
      {"type": "all"}
      {"field": "location_id", "op": "=", "value": "<uuid>"}
      {"field": "org_unit_id", "op": "in", "value": ["<uuid>", ...]}
    Field didukung: location_id, org_unit_id, legal_entity_id, job_id
    (dievaluasi terhadap JobInfo user yang berlaku hari ini).
    """

    __tablename__ = "permission_groups"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    population_rule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_groups_tenant_name"),
    )


class RoleAssignment(Base):
    """Sumbu ketiga: role diberikan kepada group -> target population.

    target_population (JSON) menentukan DATA SIAPA yang tercakup:
      {"type": "all"}  — seluruh data tenant (default)
      {"type": "self"} — hanya record milik user sendiri
      {"type": "team"} — direct report: employment yang manager_employment_id-nya
                         adalah employment user (per JobInfo yang berlaku hari ini)
    Dievaluasi per-request di app/services/population.py (Sprint 2).
    """

    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permission_roles.id"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permission_groups.id"), nullable=False, index=True
    )
    target_population: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=lambda: {"type": "all"}
    )

    __table_args__ = (
        UniqueConstraint("role_id", "group_id", name="uq_assignments_role_group"),
    )


class FieldPermission(Base):
    """Izin tingkat field (PRD PLT-041).

    field_name="*" berarti berlaku untuk seluruh objek (object-level grant).
    can_view_history=False memungkinkan pola "HRBP boleh lihat gaji kini,
    tapi tidak riwayat gaji".
    """

    __tablename__ = "field_permissions"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permission_roles.id"), nullable=False, index=True
    )
    object_name: Mapped[str] = mapped_column(String(100), nullable=False)  # mis. "job_info"
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, default="*")
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_view_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_insert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint(
            "role_id", "object_name", "field_name", name="uq_fieldperm_role_obj_field"
        ),
    )


# ---------------------------------------------------------------------------
# Struktur organisasi bertanggal efektif (Sprint 2, CHR-001).
#
# Pola: tabel identitas (id stabil, dirujuk FK dari JobInfo dsb.) +
# tabel info berversi (EffectiveDatedMixin). Atribut yang berubah dari
# waktu ke waktu (nama, parent, legal entity, status aktif) hidup di
# tabel info; record baru = versi baru, bukan update (CHR-004: setiap
# perubahan wajib punya event + event reason).
# ---------------------------------------------------------------------------


class EffectiveDatedMixin:
    """Kolom baku semua blok bertanggal efektif (bukan tabel)."""

    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False, default=MAX_DATE)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    event_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )


class LegalEntity(Base):
    """Identitas legal entity (PT/NPWP pemotong). Atribut berversi di LegalEntityInfo."""

    __tablename__ = "legal_entities"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()


class LegalEntityInfo(Base, EffectiveDatedMixin):
    __tablename__ = "legal_entity_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("legal_entities.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    npwp: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "legal_entity_id", "valid_from", "seq_no",
            name="uq_leinfo_le_from_seq",
        ),
    )


class OrgUnit(Base):
    """Identitas unit organisasi. Hierarki (grup -> legal entity -> BU ->
    divisi -> departemen -> tim) dibentuk via parent_id di OrgUnitInfo
    sehingga perpindahan unit antar-parent adalah versi baru bertanggal
    efektif, bukan update."""

    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()


class OrgUnitInfo(Base, EffectiveDatedMixin):
    __tablename__ = "org_unit_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Parent merujuk IDENTITAS unit (org_units.id), bukan baris versi,
    # agar relasi tetap stabil walau parent berganti versi.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=True, index=True
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("legal_entities.id"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "org_unit_id", "valid_from", "seq_no",
            name="uq_ouinfo_ou_from_seq",
        ),
    )


class Location(Base):
    """Identitas lokasi kerja. Atribut berversi di LocationInfo."""

    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()


class LocationInfo(Base, EffectiveDatedMixin):
    __tablename__ = "location_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Asia/Jakarta")

    __table_args__ = (
        UniqueConstraint(
            "location_id", "valid_from", "seq_no",
            name="uq_locinfo_loc_from_seq",
        ),
    )


class CostCenter(Base):
    """Identitas cost center untuk jurnal payroll per pusat biaya (CHR-001)."""

    __tablename__ = "cost_centers"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()


class CostCenterInfo(Base, EffectiveDatedMixin):
    __tablename__ = "cost_center_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    cost_center_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cost_centers.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "cost_center_id", "valid_from", "seq_no",
            name="uq_ccinfo_cc_from_seq",
        ),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_jobs_tenant_code"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=False, index=True
    )
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


# ---------------------------------------------------------------------------
# Person - Employment
# ---------------------------------------------------------------------------
class Employment(Base):
    """Hubungan kerja satu Person dengan satu LegalEntity."""

    __tablename__ = "employments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("persons.id"), nullable=False, index=True
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("legal_entities.id"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")


# ---------------------------------------------------------------------------
# Blok bertanggal efektif (PRD 15.2)
# ---------------------------------------------------------------------------
class JobInfo(Base, EffectiveDatedMixin):
    __tablename__ = "job_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=False
    )
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=False
    )
    manager_employment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "employment_id", "valid_from", "seq_no", name="uq_jobinfo_emp_from_seq"
        ),
        Index("ix_jobinfo_emp_from", "employment_id", "valid_from"),
    )


class CompInfo(Base, EffectiveDatedMixin):
    __tablename__ = "comp_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    pay_group: Mapped[str] = mapped_column(String(50), nullable=False, default="Bulanan")
    # Komponen gaji sebagai JSON; nominal WAJIB integer rupiah (PRD 18.4 aturan 3).
    # Contoh: {"gaji_pokok": 8000000, "tunjangan_tetap": 2000000}
    components: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Status PTKP yang dipakai perhitungan PPh 21 untuk versi ini
    # (Sprint 3, CHR-005). Disalin dari Person.ptkp saat versi dibuat.
    ptkp: Mapped[str] = mapped_column(String(8), nullable=False, default="TK/0")

    __table_args__ = (
        UniqueConstraint(
            "employment_id", "valid_from", "seq_no", name="uq_compinfo_emp_from_seq"
        ),
        Index("ix_compinfo_emp_from", "employment_id", "valid_from"),
    )


# ---------------------------------------------------------------------------
# Custom field / metadata (PRD 15.1, PLT-001 & PLT-003, CHR-009).
#
# Admin mendefinisikan field tanpa deploy. Nilai disimpan di kolom
# bertipe (bukan satu JSON blob) agar bisa difilter/diurut di DB.
# - Nonaktifkan definisi -> data lama tetap terbaca (PLT-003).
# - Hapus definisi = soft delete (is_active=False) + audit.
# ---------------------------------------------------------------------------
CUSTOM_FIELD_OBJECTS = (
    "person",
    "employment",
    "job_info",
    "comp_info",
    "org_unit",
    "legal_entity",
    "location",
    "cost_center",
)

CUSTOM_FIELD_TYPES = ("text", "number", "date", "select", "lookup", "attachment")

# Target lookup yang didukung untuk field_type="lookup".
LOOKUP_TARGETS = ("org_unit", "legal_entity", "location", "job", "position", "person")


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    object_name: Mapped[str] = mapped_column(String(100), nullable=False)
    field_key: Mapped[str] = mapped_column(String(50), nullable=False)
    label_id: Mapped[str] = mapped_column(String(200), nullable=False)
    label_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # select -> [{"value","label_id","label_en","is_active"}]
    # lookup -> {"target": "<salah satu LOOKUP_TARGETS>"}
    options: Mapped[dict | list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "object_name", "field_key",
            name="uq_cfdef_tenant_obj_key",
        ),
    )


class CustomFieldValue(Base):
    __tablename__ = "custom_field_values"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("custom_field_definitions.id"), nullable=False, index=True
    )
    # UUID (string) record target; satu nilai per (definisi, record).
    record_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "definition_id", "record_id", name="uq_cfval_def_record"
        ),
        Index("ix_cfval_tenant_def", "tenant_id", "definition_id"),
    )


# ---------------------------------------------------------------------------
# Audit trail (PRD 15.6) — append-only
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # insert | correct | create | update | login | ...
    object_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    object_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    old_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="api")
    # api | seed | import | agent
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Katalog event lifecycle + alasan (Sprint 3, CHR-002).
#
# Setiap tenant punya katalog event sendiri. Kode event stabil (dipakai
# derivasi status & API); nama boleh diubah admin tanpa merusak histori.
# Aturan keras: insert JobInfo/CompInfo/ContractInfo tanpa event+reason yang
# terdaftar di katalog -> ValueError -> 422 di API.
# ---------------------------------------------------------------------------
class LifecycleEvent(Base):
    """Satu baris katalog event milik tenant."""

    __tablename__ = "lifecycle_events"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "lifecycle" (hire/promosi/...) | "org" (pendirian/restrukturisasi/...)
    applies_to: Mapped[str] = mapped_column(String(20), nullable=False, default="lifecycle")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_lifecycle_tenant_code"),
        Index("ix_lifecycle_tenant_applies", "tenant_id", "applies_to"),
    )


class EventReason(Base):
    """Alasan yang diizinkan untuk satu event (dipilih user saat insert)."""

    __tablename__ = "event_reasons"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lifecycle_events.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "event_id", "reason", name="uq_eventreason_tenant_event_reason"
        ),
    )


# ---------------------------------------------------------------------------
# Kontrak kerja (Sprint 3, CHR-006).
#
# Pola identitas + info berversi (konsisten ADR-0004): masa berlaku kontrak
# = valid_from..valid_to pada ContractInfo. PKWTT memakai valid_to = MAX_DATE
# (kontrak terbuka, tak pernah "expiring"). Perpanjangan/konversi = versi baru.
# ---------------------------------------------------------------------------
class Contract(Base):
    """Identitas kontrak: satu employment dapat memiliki rangkaian versi kontrak."""

    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContractInfo(Base, EffectiveDatedMixin):
    """Versi kontrak (PKWT/PKWTT) bertanggal efektif."""

    __tablename__ = "contract_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    contract_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contracts.id"), nullable=False, index=True
    )
    contract_type: Mapped[str] = mapped_column(String(10), nullable=False)  # PKWT | PKWTT
    contract_number: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "contract_id", "valid_from", "seq_no", name="uq_contractinfo_c_from_seq"
        ),
        Index("ix_contractinfo_c_from", "contract_id", "valid_from"),
    )


class TenantContractPolicy(Base):
    """Aturan main kontrak per tenant (batas durasi & perpanjangan PKWT)."""

    __tablename__ = "tenant_contract_policies"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )
    max_pkwt_months: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_extensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# Dokumen karyawan (Sprint 3, CHR-012 dasar — tanpa e-sign).
#
# Satu dokumen = satu file. Upload baru untuk (person, doc_type) yang sama
# menaikkan version; versi lama tetap tersimpan (is_current=False).
# file_path relatif terhadap direktori upload aplikasi.
# ---------------------------------------------------------------------------
DOCUMENT_TYPES = ("ktp", "kk", "npwp_card", "ijazah", "kontrak", "paklaring", "lain")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("persons.id"), nullable=True, index=True
    )
    employment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=True, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_documents_tenant_person_type", "tenant_id", "person_id", "doc_type"),
    )


# ---------------------------------------------------------------------------
# Payroll (Sprint 4).
#
# Pola konsisten ADR-0001/0004/0006:
# - SalaryComponent = identitas (code unik per tenant); versi bertanggal
#   efektif di SalaryComponentInfo (perubahan rumus/nominal = versi baru).
# - CompAssignment = identitas (employment x komponen); versi bertanggal
#   efektif di CompAssignmentInfo (override amount / aktif-nonaktif).
# - Uang = integer rupiah (PRD 18.4 aturan 3).
# ---------------------------------------------------------------------------
class SalaryComponent(Base):
    """Identitas komponen gaji (gaji_pokok, tunjangan_tetap, lembur, ...)."""

    __tablename__ = "salary_components"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_salcomp_tenant_code"),
    )


class SalaryComponentInfo(Base, EffectiveDatedMixin):
    """Versi komponen gaji bertanggal efektif (PAY-001)."""

    __tablename__ = "salary_component_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    component_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("salary_components.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # earning | deduction
    calc_type: Mapped[str] = mapped_column(String(20), nullable=False)  # fixed | formula
    # fixed -> string integer rupiah ("8000000"); formula -> ekspresi aman
    # (dievaluasi app/services/formula.py, tanpa eval/exec).
    amount_or_formula: Mapped[str] = mapped_column(Text, nullable=False)
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_bpjs_base: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    __table_args__ = (
        UniqueConstraint(
            "component_id", "valid_from", "seq_no",
            name="uq_salcompinfo_c_from_seq",
        ),
        Index("ix_salcompinfo_c_from", "component_id", "valid_from"),
    )


class CompAssignment(Base):
    """Identitas: komponen X di-assign ke employment Y."""

    __tablename__ = "comp_assignments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("salary_components.id"), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employment_id", "component_id",
            name="uq_compassign_tenant_emp_comp",
        ),
    )


class CompAssignmentInfo(Base, EffectiveDatedMixin):
    """Versi assignment bertanggal efektif: override & aktif/nonaktif."""

    __tablename__ = "comp_assignment_info"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("comp_assignments.id"), nullable=False, index=True
    )
    # Bila diisi: menggantikan nilai default komponen fixed untuk karyawan ini.
    override_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "valid_from", "seq_no",
            name="uq_compassigninfo_a_from_seq",
        ),
        Index("ix_compassigninfo_a_from", "assignment_id", "valid_from"),
    )


class PayrollPolicy(Base):
    """Kebijakan penggajian per tenant (metode PPh 21, basis THR, ...)."""

    __tablename__ = "payroll_policies"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )
    pph21_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="gross"
    )  # gross | gross_up | net
    thr_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="gaji_pokok"
    )  # gaji_pokok | total_fixed
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PayrollRun(Base):
    """Satu periode penggajian ("YYYY-MM"). Terkunci -> tak bisa dihitung ulang."""

    __tablename__ = "payroll_runs"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    pph21_method: Mapped[str] = mapped_column(String(20), nullable=False, default="gross")
    include_thr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thr_holiday_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Input run: {"overtime_hours": {"<employment_id>": 2}, ...}
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "period", name="uq_payrollruns_tenant_period"),
    )


class PayrollLine(Base):
    """Satu baris slip: snapshot input + breakdown komponen (rekonsiliasi)."""

    __tablename__ = "payroll_lines"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_runs.id"), nullable=False, index=True
    )
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)
    nik: Mapped[str] = mapped_column(String(16), nullable=False)
    ptkp: Mapped[str] = mapped_column(String(8), nullable=False, default="TK/0")
    # Snapshot yang bisa direkonsiliasi: {code: amount_int} komponen reguler.
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Input snapshot: {"ptkp": ..., "hari_kerja": ..., "gaji_pokok": ...}
    inputs_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    gross: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deductions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pph21: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pph21_borne_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default="employee"
    )  # employee | employer
    thr_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retro_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retro_detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    take_home_pay: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Info beban perusahaan (tidak memotong take-home; untuk laporan iuran).
    employer_cost: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Error blocking validasi pra-kunci (PAY-009): [] = siap dikunci.
    validation_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint(
            "payroll_run_id", "employment_id",
            name="uq_payrolllines_run_employment",
        ),
        Index("ix_payrolllines_run", "payroll_run_id"),
    )


# ---------------------------------------------------------------------------
# Absensi, cuti, lembur (Sprint 5, PRD Bagian 10: TIM/LEV).
#
# Penyederhanaan vs PRD (jujur, dirinci di ADR-0008):
# - Tanpa geofence/GPS, face matching, deteksi fake GPS, mode offline,
#   integrasi mesin absensi (TIM-010 s/d TIM-015 = F1 di PRD, di sini
#   arsitektur disiapkan via kolom `source`, bukan implementasi penuh).
# - Koreksi absensi = versi baru (is_current), data asli tetap ada (TIM-021).
# - Saldo cuti disimpan sebagai counter (bukan ledger append-only penuh);
#   setiap mutasi tercatat di audit trail.
# ---------------------------------------------------------------------------
class Shift(Base):
    """Definisi shift kerja per tenant."""

    __tablename__ = "shifts"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )  # dipakai komponen jam:menit saja
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    is_overnight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_shifts_tenant_code"),
    )


class ShiftAssignment(Base):
    """Penugasan shift ke employment, bertanggal efektif (tanpa katalog event:
    ini penjadwalan operasional, bukan peristiwa lifecycle)."""

    __tablename__ = "shift_assignments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shifts.id"), nullable=False, index=True
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False, default=MAX_DATE)

    __table_args__ = (
        Index("ix_shiftassign_emp_from", "employment_id", "valid_from"),
    )


class Holiday(Base):
    """Kalender libur tenant: libur nasional & cuti bersama (LEV-003)."""

    __tablename__ = "holidays"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_cuti_bersama: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Cuti bersama memotong saldo cuti tahunan (opsional, default True).
    deducts_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Penanda idempotensi apply_mass_leave (sudah dipotong atau belum).
    mass_leave_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "date", name="uq_holidays_tenant_date"),
    )


ATTENDANCE_SOURCES = ("mobile", "web", "manual", "machine")
ATTENDANCE_STATUSES = ("present", "late", "absent", "leave", "holiday")


class AttendanceRecord(Base):
    """Satu hari absensi satu employment. Koreksi = versi baru (TIM-021);
    versi lama (is_current=False) tetap tersimpan sebagai jejak."""

    __tablename__ = "attendance_records"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    check_in: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    check_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="present")
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    work_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correction_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employment_id", "date", "version",
            name="uq_attendance_tenant_emp_date_ver",
        ),
        Index("ix_attendance_emp_date", "employment_id", "date"),
    )


class LeaveType(Base):
    """Jenis cuti/izin per tenant (LEV-001)."""

    __tablename__ = "leave_types"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quota_days: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    # none | monthly — akrual; monthly dipakai untuk pro-rata join mid-year.
    accrual: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    min_service_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_doc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # False untuk "izin" (tidak memotong kuota).
    deducts_balance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_leavetypes_tenant_code"),
    )


class LeaveBalance(Base):
    """Saldo cuti per employment per jenis per tahun kalender."""

    __tablename__ = "leave_balances"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leave_types.id"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    entitled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employment_id", "leave_type_id", "year",
            name="uq_leavebal_tenant_emp_type_year",
        ),
        Index("ix_leavebal_emp_year", "employment_id", "year"),
    )


LEAVE_REQUEST_STATUSES = (
    "draft", "submitted", "approved_l1", "approved", "rejected", "cancelled",
)


class LeaveRequest(Base):
    """Pengajuan cuti/izin dengan approval 2 level (LEV, MSS)."""

    __tablename__ = "leave_requests"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leave_types.id"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Hari kerja yang dipotong (Senin-Jumat, di luar libur tenant).
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    l1_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    l1_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    l2_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    l2_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    doc_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_leavereq_emp_status", "employment_id", "status"),
    )


class TenantLeavePolicy(Base):
    """Kebijakan cuti per tenant."""

    __tablename__ = "tenant_leave_policies"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )
    max_consecutive_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=12
    )
    # Daftar {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "name": ...}.
    blackout_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantAttendancePolicy(Base):
    """Kebijakan absensi per tenant (aturan telat dsb, TIM-020 sederhana)."""

    __tablename__ = "tenant_attendance_policies"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # Bila True, hari mangkir memotong gaji via komponen "potongan_mangkir".
    deduct_absent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OvertimeRate(Base):
    """Tabel pengali lembur bertanggal efektif (PP 35/2021; siap diganti
    bila UU ketenagakerjaan baru berlaku — PRD 10.4)."""

    __tablename__ = "overtime_rates"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False, default=MAX_DATE)
    first_hour_mult: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=1.5
    )
    next_hour_mult: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=2.0
    )
    # Pembagi upah sebulan -> upah per jam (default 173).
    divisor: Mapped[int] = mapped_column(Integer, nullable=False, default=173)

    __table_args__ = (
        Index("ix_overtimerate_tenant_from", "tenant_id", "valid_from"),
    )


OVERTIME_REQUEST_STATUSES = (
    "draft", "submitted", "approved_l1", "approved", "rejected", "cancelled",
)


class OvertimeRequest(Base):
    """Pengajuan lembur pra-persetujuan + approval 2 level (TIM-030)."""

    __tablename__ = "overtime_requests"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    hours: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Upah lembur (integer rupiah) dihitung saat approval final.
    pay_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    l1_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    l1_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    l2_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    l2_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_overtimereq_emp_date", "employment_id", "date"),
    )
