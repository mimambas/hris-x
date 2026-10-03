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
    BigInteger,
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
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)  # Sprint 6: dari offer accept
    gender: Mapped[str | None] = mapped_column(String(1), nullable=True)  # Sprint 9: "L"/"P"
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
    # CMP-001: grade gaji yang melekat pada jabatan ini (boleh kosong).
    pay_grade_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("pay_grades.id"), nullable=True, index=True
    )

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
    # SUC-002: penanda posisi kunci untuk perencanaan suksesi.
    is_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
DOCUMENT_TYPES = ("ktp", "kk", "npwp_card", "ijazah", "kontrak", "paklaring", "sertifikat", "lain")


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
    # Reimbursement klaim (Sprint 8, BEN-001): earning NON-PAJAK, tidak masuk
    # `gross` kena pajak; direkonsiliasi terpisah di slip.
    reimbursement_amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    reimbursement_claim_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
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


# ---------------------------------------------------------------------------
# Rekrutmen (Sprint 6)
# ---------------------------------------------------------------------------
class JobRequisition(Base):
    """Kebutuhan rekrutmen: draft → submitted → approved/rejected.

    Approval 1 level oleh HR (izin requisition/correct). Hiring manager
    (izin view+correct tanpa insert) hanya boleh mengelola requisition
    yang org_unit_id-nya = unit kerjanya sendiri (batas di kode, ADR-0009).
    """

    __tablename__ = "job_requisitions"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=False, index=True
    )
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="draft")  # draft/submitted/approved/rejected
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobPosting(Base):
    """Lowongan: draft → published → closed. Publish hanya bila requisition
    sudah approved (dicek di API)."""

    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    requisition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_requisitions.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    employment_type: Mapped[str] = mapped_column(String(50), nullable=False,
                                                default="tetap")
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="draft")  # draft/published/closed
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Candidate(Base):
    """Kandidat eksternal (bukan person). Email unik per tenant."""

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)  # lowercase
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cv_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="website")  # website/referral/job_portal
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_candidate_tenant_email"),
    )


class JobApplication(Base):
    """Lamaran: applied → screening → interview → offering → hired;
    cabang rejected/withdrawn dari stage mana pun (bukan final)."""

    __tablename__ = "job_applications"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    posting_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_postings.id"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("candidates.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="applied")
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "posting_id", "candidate_id",
                         name="uq_app_posting_candidate"),
    )


class Interview(Base):
    """Jadwal wawancara satu lamaran; bisa lebih dari satu."""

    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_applications.id"), nullable=False, index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    interviewer_ids: Mapped[list] = mapped_column(JSON, nullable=False,
                                                  default=list)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False,
                                      default="onsite")  # onsite/online
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="scheduled")  # scheduled/completed/cancelled
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InterviewFeedback(Base):
    """Penilaian satu interviewer atas satu wawancara (1 baris/interviewer)."""

    __tablename__ = "interview_feedbacks"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    interview_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interviews.id"), nullable=False, index=True
    )
    interviewer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..5
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str] = mapped_column(
        String(20), nullable=False)  # hire/no_hire/consider
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("interview_id", "interviewer_id",
                         name="uq_feedback_interview_interviewer"),
    )


class Offer(Base):
    """Penawaran kerja (e-offer): draft → sent → accepted/declined/expired.

    Accept publik via offer_token acak (tanpa auth). Saat accept: Person +
    Employment dibuat, JobInfo di-insert dengan event 'hire'."""

    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_applications.id"), nullable=False, index=True
    )
    salary: Mapped[int] = mapped_column(Integer, nullable=False)  # rupiah
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    contract_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Data kepegawaian untuk pembuatan Employment+JobInfo saat accept.
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=False
    )
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id"), nullable=False
    )
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("legal_entities.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    offer_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="draft")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("application_id", name="uq_offer_application"),
    )


# ---------------------------------------------------------------------------
# Sprint 7 (PRD 24.2 S7): penilaian kinerja & pelatihan
# ---------------------------------------------------------------------------
class ReviewCycle(Base):
    """Siklus penilaian kinerja: draft → goal_setting → mid_year →
    year_end → calibration → closed."""

    __tablename__ = "review_cycles"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="draft")  # draft/goal_setting/mid_year/year_end/calibration/closed
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PerformanceGoal(Base):
    """Goal kinerja karyawan per siklus; bobot dalam persen."""

    __tablename__ = "performance_goals"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("review_cycles.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)  # persen
    target_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="draft")  # draft/submitted/approved/rejected
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_goals_tenant_cycle_emp", "tenant_id", "cycle_id",
              "employment_id"),
    )


class Appraisal(Base):
    """Penilaian satu karyawan dalam satu siklus: self → manager →
    kalibrasi (potential) → final_score."""

    __tablename__ = "appraisals"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("review_cycles.id"), nullable=False, index=True
    )
    # [{"goal_id": "<uuid>", "score": 1..5, "comment": "..."}]
    self_scores: Mapped[list | None] = mapped_column(JSON, nullable=True)
    self_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # [{"goal_id": "<uuid>", "score": 1..5}]
    manager_scores: Mapped[list | None] = mapped_column(JSON, nullable=True)
    manager_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    potential_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True)  # 1..5, diisi saat kalibrasi
    final_score: Mapped[float | None] = mapped_column(
        Numeric(4, 2), nullable=True)  # Σ(weight × manager_score)/100
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "employment_id", "cycle_id",
                         name="uq_appraisal_tenant_emp_cycle"),
    )


class TenantPerformancePolicy(Base):
    """Ambang batas kategori performance/potential per tenant untuk
    matriks 9-box."""

    __tablename__ = "tenant_performance_policies"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    perf_low_max: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False,
                                               default=2.5)
    perf_med_max: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False,
                                               default=3.75)
    pot_low_max: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False,
                                              default=2.5)
    pot_med_max: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False,
                                              default=3.5)

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_perf_policy_tenant"),
    )


class TrainingCourse(Base):
    """Katalog kursus/pelatihan.

    LRN-001 (PRD 12.5): kursus membawa konten belajar — ``content_type``
    pdf/video/link/offline + ``content_url``. LRN-003: ``passing_score``
    (nilai lulus post-test 0–100, None = tanpa gerbang nilai) dan
    ``cert_validity_months`` (masa berlaku sertifikasi, mis. K3; None =
    sertifikat tanpa kedaluwarsa).
    """

    __tablename__ = "training_courses"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duration_hours: Mapped[int] = mapped_column(Integer, nullable=False,
                                                default=0)
    cost: Mapped[int] = mapped_column(Integer, nullable=False,
                                      default=0)  # rupiah
    # --- LRN-001/003 ---
    content_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="offline"
    )  # pdf | video | link | offline
    content_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    passing_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cert_validity_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_course_tenant_code"),
    )


class TrainingEnrollment(Base):
    """Pendaftaran karyawan pada kursus."""

    __tablename__ = "training_enrollments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_courses.id"), nullable=False, index=True
    )
    # Opsional: enrollment yang lahir dari rekomendasi siklus kalibrasi.
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("review_cycles.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        default="registered")  # registered/in_progress/completed/cancelled
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Sertifikat: referensi ke documents.id; tanpa FK keras agar modul
    # dokumen tetap opsional (disimpan sebagai UUID nullable).
    certificate_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    # --- LRN-001/002/003: progres belajar, penugasan wajib, nilai tes ---
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)  # 0–100, terlacak per karyawan
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)
    pre_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Diisi saat selesai: completed_at + masa berlaku kursus (LRN-003).
    cert_expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def is_overdue(self) -> bool:
        """Terlambat: melewati tenggat dan belum selesai/dibatalkan."""
        return (
            self.due_date is not None
            and self.status not in ("completed", "cancelled")
            and self.due_date < date.today()
        )


class TrainingAssignment(Base):
    """Penugasan pelatihan wajib (LRN-002) ke populasi target.

    Satu baris per perintah penugasan; saat dibuat, sistem mematerialkan
    enrollment wajib (``is_mandatory`` + ``due_date``) untuk setiap
    employment aktif pada target: seluruh tenant (``all``), satu unit
    organisasi (``org_unit``), atau pemegang satu jabatan (``job``).
    """

    __tablename__ = "training_assignments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("training_courses.id"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False)  # all | org_unit | job
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=True, index=True)
    due_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enrollments_created: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


# ---------------------------------------------------------------------------
# Klaim & pinjaman karyawan (Sprint 8, PRD Bagian 11.5: BEN-001/BEN-003).
#
# Penyederhanaan vs PRD (jujur, dirinci di ADR-0011):
# - Tanpa OCR struk (BEN-001): struk = dokumen upload biasa (modul Sprint 3).
# - Reimbursement masuk payroll run sebagai earning NON-PAJAK; opsi
#   "dibayar terpisah" (transfer) tercatat sebagai status paid dengan
#   paid_via="transfer" dan tidak masuk run.
# - Pinjaman: bunga flat tahunan sederhana (default 0%), tanpa denda;
#   tanpa EWA (BEN-004) dan cash advance settlement (BEN-002).
# ---------------------------------------------------------------------------
class ClaimType(Base):
    """Jenis klaim: plafon per tahun & per pengajuan, terkonfigurasi/tenant."""

    __tablename__ = "claim_types"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Plafon rupiah; None = tanpa batas.
    limit_per_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limit_per_claim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_receipt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_claimtypes_tenant_code"),
    )


class Claim(Base):
    """Pengajuan klaim dengan approval 2 level (atasan -> HR/Finance)."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    claim_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("claim_types.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Struk: referensi ke documents.id (tanpa FK keras, pola Sprint 7).
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    # draft/submitted/approved_l1/approved/paid/rejected/cancelled
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    # Cara bayar: payroll (masuk run) | transfer (dibayar terpisah).
    paid_via: Mapped[str] = mapped_column(
        String(20), nullable=False, default="payroll"
    )
    # Run payroll yang membawa reimbursement ini (hanya bila payroll).
    payroll_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payroll_runs.id"), nullable=True, index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    l1_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    l1_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TenantLoanPolicy(Base):
    """Kebijakan pinjaman per tenant."""

    __tablename__ = "tenant_loan_policies"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )
    # Maksimal pinjaman = multiplier x gaji bulanan (gaji_pokok+tunjangan_tetap).
    max_amount_multiplier: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=3.0
    )
    max_tenor_months: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24
    )
    # Bunga flat tahunan default (0.0 = tanpa bunga).
    default_interest_rate: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.0
    )
    # Bila False: 1 pinjaman aktif per karyawan.
    allow_multiple_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class Loan(Base):
    """Pinjaman/kasbon karyawan; cicilan otomatis dipotong dari payroll."""

    __tablename__ = "loans"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    principal_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # Bunga flat tahunan yang dipakai saat approve (mis. 0.06 = 6%).
    interest_rate: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False, default=0.0
    )
    # Total yang harus dibayar = pokok + bunga flat.
    total_payable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tenor_months: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_installment: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Sisa total (pokok+bunga) yang belum dibayar.
    remaining_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    purpose: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # draft/submitted/approved/active/completed/rejected/cancelled
    # ("approved" = transien saat approve; langsung menjadi "active".)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_off_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LoanInstallment(Base):
    """Satu angsuran pinjaman untuk satu periode payroll."""

    __tablename__ = "loan_installments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    loan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("loans.id"), nullable=False, index=True
    )
    # Periode payroll "YYYY-MM" tempat angsuran dipotong.
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # regular | payoff (pelunasan dipercepat: sisa total sekaligus).
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    # pending -> paid (saat payroll run dikunci).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    payroll_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payroll_runs.id"), nullable=True, index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("loan_id", "period",
                         name="uq_loaninstallments_loan_period"),
    )


# ------------------------------------------------------------------ Onboarding
# Modul ONB (PRD 12.2, F2): checklist onboarding & offboarding lintas tim.
# - Template (milik HR) -> Proses per karyawan -> Tugas dengan tenggat.
# - ONB-001: tugas dokumen (required_doc_type, mis. "ktp").
# - ONB-002: tim pelaksana (it/hr/ga/manager/finance) + due_date; terlambat
#   otomatis terflag di daftar (eskalasi visual).
# - ONB-004: offboarding = template kind="offboarding" (clearance aset,
#   cabut akses, exit interview, paklaring).
# ONB-003 (buddy/agenda/kursus wajib) = P2, ditunda ke F3.


class OnboardingTemplate(Base):
    """Template checklist onboarding/offboarding milik tenant (kelola HR)."""

    __tablename__ = "onboarding_templates"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # "onboarding" | "offboarding".
    kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                     default="onboarding")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OnboardingTemplateTask(Base):
    """Satu butir tugas dalam template (definisi, bukan instance)."""

    __tablename__ = "onboarding_template_tasks"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("onboarding_templates.id"), nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Tim pelaksana: "hr" | "it" | "ga" | "manager" | "finance".
    team: Mapped[str] = mapped_column(String(20), nullable=False,
                                      default="hr")
    # Offset hari relatif terhadap start_date proses (negatif = sebelum
    # hari pertama, mis. -3 = siapkan laptop 3 hari sebelumnya).
    due_offset_days: Mapped[int] = mapped_column(Integer, nullable=False,
                                                 default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)
    # Tipe dokumen yang wajib ada agar tugas dianggap selesai otomatis
    # (mis. "ktp"); NULL = penyelesaian manual.
    required_doc_type: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )


class OnboardingProcess(Base):
    """Satu proses onboarding/offboarding untuk satu karyawan."""

    __tablename__ = "onboarding_processes"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("persons.id"), nullable=False, index=True,
    )
    employment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=True, index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("onboarding_templates.id"), nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                      default="onboarding")
    # "in_progress" | "completed" | "cancelled".
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                       default="in_progress")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OnboardingTask(Base):
    """Satu butir tugas dalam sebuah proses (instance)."""

    __tablename__ = "onboarding_tasks"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    process_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("onboarding_processes.id"), nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    team: Mapped[str] = mapped_column(String(20), nullable=False,
                                      default="hr")
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True, index=True,
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # "pending" | "in_progress" | "done" | "skipped".
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                       default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tipe dokumen yang disyaratkan (disalin dari template; mis. "ktp").
    # NULL = penyelesaian manual.
    required_doc_type: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )


# ---------------------------------------------------------------------------
# Kompensasi (CMP, PRD 12.4, F3)
# - PayGrade: grade + salary band (min/mid/max); jabatan menempel ke grade
#   (Job.pay_grade_id). Compa-ratio = gaji_pokok / band_mid.
# - CompCycle: siklus merit/bonus + guideline; CompCycleBudget: anggaran
#   kenaikan tahunan per unit; CompProposal: usulan per karyawan dengan
#   approval berjenjang (over-budget -> persetujuan tambahan).
# ---------------------------------------------------------------------------


class PayGrade(Base):
    """CMP-001: pay grade dan salary band (min/mid/max) per tenant."""

    __tablename__ = "pay_grades"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    band_min: Mapped[int] = mapped_column(BigInteger, nullable=False)
    band_mid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    band_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_paygrade_tenant_code"),
    )


class CompCycle(Base):
    """CMP-002: siklus merit/bonus dengan guideline kenaikan."""

    __tablename__ = "comp_cycles"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # "merit" | "bonus".
    kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                      default="merit")
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    # "draft" | "open" | "finalized" | "cancelled".
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                       default="draft")
    # Guideline: [{"min_rating": 4.5, "max_rating": 5.0,
    #              "min_pct": 8, "max_pct": 12}, ...] (persen kenaikan).
    guideline: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CompCycleBudget(Base):
    """Anggaran total kenaikan (tahunan, rupiah) per unit dalam siklus."""

    __tablename__ = "comp_cycle_budgets"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("comp_cycles.id"), nullable=False, index=True
    )
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=False, index=True
    )
    budget_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "cycle_id", "org_unit_id",
                         name="uq_compbudget_cycle_unit"),
    )


class CompProposal(Base):
    """Usulan perubahan kompensasi satu karyawan dalam satu siklus."""

    __tablename__ = "comp_proposals"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("comp_cycles.id"), nullable=False, index=True
    )
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("persons.id"), nullable=False, index=True
    )
    # Snapshot unit saat usulan dibuat (dasar cek anggaran per unit).
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=True, index=True
    )
    current_salary: Mapped[int] = mapped_column(BigInteger, nullable=False)
    proposed_salary: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Snapshot rating penilaian terakhir (skala 1-5) untuk guideline.
    rating: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    guideline_min_pct: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True)
    guideline_max_pct: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True)
    # "draft" | "submitted" | "pending_extra_approval" | "approved" |
    # "rejected".
    status: Mapped[str] = mapped_column(String(30), nullable=False,
                                       default="draft")
    over_budget: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             default=False)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    extra_approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cycle_id", "employment_id",
                         name="uq_compproposal_cycle_emp"),
    )


# ---------------------------------------------------------------------------
# Suksesi & karier (SUC, PRD 12.6 F3).
#
# Penyederhanaan vs PRD (jujur):
# - SUC-006: tanpa inferensi AI. Semua skill baru berstatus "usulan" dan
#   wajib disetujui HR sebelum terhitung di profil talent/talent pool —
#   governance yang sama seperti yang PRD minta untuk hasil AI.
# - SUC-003: talent pool adalah snapshot materialisasi dari appraisal satu
#   siklus (final_score + potential_score terkalibrasi), bukan hitungan live.
# - SUC-005: privasi lamaran internal ditegakkan di lapis query — atasan
#   pelamar hanya melihat lamaran berstatus >= "seleksi".
# ---------------------------------------------------------------------------
class Skill(Base):
    """Ontologi skill per tenant dengan governance (SUC-006)."""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # usulan -> disetujui | ditolak (keputusan HR).
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="usulan")
    proposed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_skills_tenant_name"),
    )


class PersonSkill(Base):
    """Skill yang dimiliki karyawan beserta tingkat kemahiran (SUC-001)."""

    __tablename__ = "person_skills"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    skill_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("skills.id"), nullable=False, index=True)
    proficiency: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1)  # 1..5
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "employment_id", "skill_id",
                         name="uq_personskills_emp_skill"),
    )


class TalentProfile(Base):
    """Profil talent per employment (SUC-001): preferensi mobilitas &
    aspirasi karier. Skill, pengalaman, dan sertifikasi diagregasi dari
    Core HR (JobInfo), Learning (sertifikat), dan PersonSkill."""

    __tablename__ = "talent_profiles"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    # tidak_terbuka | dalam_kota | luar_kota | semua
    mobility_preference: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tidak_terbuka")
    career_aspiration: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "employment_id",
                         name="uq_talentprofiles_emp"),
    )


class SuccessionNomination(Base):
    """Nominasi suksesor untuk posisi kunci (SUC-002)."""

    __tablename__ = "succession_nominations"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    position_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("positions.id"), nullable=False, index=True)
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    # siap_sekarang | siap_1_tahun | siap_2_tahun
    readiness: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    nominated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "position_id", "employment_id",
                         name="uq_succnom_position_emp"),
    )


class TalentPool(Base):
    """Kelompok talent hasil snapshot matriks 9-box satu siklus (SUC-003)."""

    __tablename__ = "talent_pools"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("review_cycles.id"), nullable=False, index=True)
    # Kunci kotak 9-box yang dipilih, mis. ["star", "high_potential"].
    box_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class TalentPoolMember(Base):
    """Anggota talent pool (snapshot kotak 9-box saat pool dibuat)."""

    __tablename__ = "talent_pool_members"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    pool_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("talent_pools.id"), nullable=False, index=True)
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    box_key: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "pool_id", "employment_id",
                         name="uq_talentpoolmember_pool_emp"),
    )


class CareerPath(Base):
    """Peta jalur karier antarjabatan (SUC-004)."""

    __tablename__ = "career_paths"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    from_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=False, index=True)
    to_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "from_job_id", "to_job_id",
                         name="uq_careerpath_from_to"),
    )


class Idp(Base):
    """Individual Development Plan satu karyawan (SUC-004)."""

    __tablename__ = "idps"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    target_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id"), nullable=True, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # draft | aktif | selesai
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="aktif")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "employment_id", "year",
                         name="uq_idps_emp_year"),
    )


class IdpItem(Base):
    """Item pengembangan dalam IDP; boleh terhubung ke kursus (SUC-004)."""

    __tablename__ = "idp_items"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    idp_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("idps.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("training_courses.id"), nullable=True, index=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # belum | selesai
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="belum")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class InternalOpportunity(Base):
    """Peluang internal: proyek, gig, atau lowongan (SUC-005)."""

    __tablename__ = "internal_opportunities"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    # proyek | gig | lowongan
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=True, index=True)
    # draft | terbuka | ditutup
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="terbuka")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class InternalApplication(Base):
    """Lamaran karyawan ke peluang internal (SUC-005).

    Alur: diajukan -> seleksi -> diterima | ditolak. Atasan pelamar hanya
    boleh melihat lamaran berstatus >= "seleksi" (privasi PRD).
    """

    __tablename__ = "internal_applications"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("internal_opportunities.id"), nullable=False,
        index=True)
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="diajukan")
    cover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "opportunity_id", "employment_id",
                         name="uq_intapp_opp_emp"),
    )


class ApprovalDelegation(Base):
    """Delegasi approval atasan (EXP-013, PRD 13.2).

    Saat atasan cuti, kewenangan approval L1-nya (cuti, lembur, klaim)
    berpindah ke karyawan lain selama jendela tanggal yang ditentukan.
    Delegasi berakhir otomatis saat end_date lewat; status "dicabut"
    bila delegator/HR membatalkan lebih awal.
    """

    __tablename__ = "approval_delegations"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    delegator_employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    delegate_employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="aktif")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())


class Announcement(Base):
    """Pengumuman bertarget dengan tanda sudah dibaca (EXP-020).

    Target: semua karyawan ("semua") atau satu unit organisasi
    ("org_unit" + target_org_unit_id). HR melihat siapa yang belum
    membaca lewat AnnouncementRead.
    """

    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False,
                                             default="semua")
    target_org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=True)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class AnnouncementRead(Base):
    """Tanda baca pengumuman per karyawan (EXP-020)."""

    __tablename__ = "announcement_reads"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("announcements.id"), nullable=False, index=True)
    employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "announcement_id", "employment_id",
                         name="uq_annread_ann_emp"),
    )


class Survey(Base):
    """Survei pulse / eNPS anonim (EXP-021).

    kind "enps": skor 0-10; kind "pulse": skor 1-5. Hasil agregat hanya
    ditampilkan bila responden >= 5 (aturan PRD).
    """

    __tablename__ = "surveys"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="aktif")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class SurveyResponse(Base):
    """Respons survei — anonim by design (EXP-021).

    respondent_hash = HMAC-SHA256(survey_id + employment_id) memakai
    secret aplikasi: mencegah suara ganda tanpa menyimpan identitas
    responden. Tidak ada FK ke employments.
    """

    __tablename__ = "survey_responses"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    survey_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("surveys.id"), nullable=False, index=True)
    respondent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "survey_id", "respondent_hash",
                         name="uq_surveyresp_survey_hash"),
    )


class Kudos(Base):
    """Pengakuan antarkaryawan (EXP-022).

    Penerima boleh menyembunyikan kudos dari profilnya
    (visible_on_profile=False) — PRD: tampil di profil hanya bila
    karyawan mengizinkan.
    """

    __tablename__ = "kudos"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    from_employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    to_employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False,
                                          default="kolaborasi")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    visible_on_profile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class HelpdeskTicket(Base):
    """Tiket layanan HR (EXP-023): kategori + SLA sederhana.

    sla_due_at dihitung dari kategori saat tiket dibuat; status:
    baru -> diproses -> menunggu -> selesai (atau ditutup).
    """

    __tablename__ = "helpdesk_tickets"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    requester_employment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employments.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="baru")
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())


class HelpdeskMessage(Base):
    """Pesan pada tiket helpdesk (EXP-023)."""

    __tablename__ = "helpdesk_messages"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("helpdesk_tickets.id"), nullable=False, index=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class KbArticle(Base):
    """Artikel knowledge base helpdesk (EXP-023).

    Ditampilkan sebelum karyawan membuat tiket (defleksi manual;
    defleksi asisten AI ditunda mengikuti pola tanpa-AI).
    """

    __tablename__ = "kb_articles"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())


class PayslipPin(Base):
    """PIN akses slip gaji self-service (EXP-003, PRD 13.3/13.1).

    Satu PIN per akun pengguna, disimpan sebagai hash bcrypt (tidak
    pernah teks biasa). Akses slip gaji milik sendiri wajib PIN; 5
    kegagalan beruntun mengunci verifikasi selama 15 menit. HR dapat
    mereset PIN karyawan yang lupa (baris dihapus, karyawan membuat
    PIN baru pada akses berikutnya). Biometrik perangkat di PRD
    digantikan jalur PIN untuk aplikasi web ini.
    """

    __tablename__ = "payslip_pins"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True)
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id",
                         name="uq_payslip_pins_tenant_user"),
    )
