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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nik", name="uq_persons_tenant_nik"),
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
    """Sumbu ketiga: role diberikan kepada group -> target population."""

    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permission_roles.id"), nullable=False, index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permission_groups.id"), nullable=False, index=True
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
# Struktur organisasi (S1: master data; effective dating penuh = S2)
# ---------------------------------------------------------------------------
class LegalEntity(Base):
    __tablename__ = "legal_entities"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    npwp: Mapped[str | None] = mapped_column(String(32), nullable=True)


class OrgUnit(Base):
    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("legal_entities.id"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("org_units.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Asia/Jakarta")


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

    __table_args__ = (
        UniqueConstraint(
            "employment_id", "valid_from", "seq_no", name="uq_compinfo_emp_from_seq"
        ),
        Index("ix_compinfo_emp_from", "employment_id", "valid_from"),
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
