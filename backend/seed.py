"""Seed demo Sprint 1 HRIS-X.

Jalankan dari direktori backend/:
    ../.venv/bin/python seed.py

Isi:
- Tenant "hashiru" (Hashiru Studio)
- Admin: admin@hashiru.id / Password123! (superadmin)
- 2 legal entity, 2 lokasi, unit organisasi bertingkat, job, position
- 5 karyawan contoh + riwayat JobInfo/CompInfo, termasuk promosi
  bertanggal masa depan (skenario penerimaan PRD 9.3)
- Role HR Admin / Manajer / Karyawan + grup dinamis + field permission

Idempoten: bila tenant "hashiru" sudah ada, seed dilewati.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_database_url  # noqa: E402
from app.core.db import init_db, new_session  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    CompInfo,
    CostCenter,
    CostCenterInfo,
    CustomFieldDefinition,
    Employment,
    FieldPermission,
    Job,
    JobInfo,
    LegalEntity,
    LegalEntityInfo,
    Location,
    LocationInfo,
    OrgUnit,
    OrgUnitInfo,
    PermissionGroup,
    PermissionRole,
    Person,
    Position,
    RoleAssignment,
    Tenant,
    User,
)
from app.services import effective_dating as ed  # noqa: E402
from app.services.audit import write_audit  # noqa: E402

ADMIN_EMAIL = "admin@hashiru.id"
ADMIN_PASSWORD = "Password123!"
# Struktur organisasi seed berlaku sejak tanggal ini (mendahului semua employment).
ORG_VALID_FROM = date(2022, 1, 1)


def _audit(db, tenant_id, actor_id, action, object_type, object_id, new_values, reason):
    write_audit(
        db=db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        new_values=new_values,
        reason=reason,
        channel="seed",
        ip=None,
    )


def main() -> None:
    engine = init_db(get_database_url())
    Base.metadata.create_all(engine)
    db = new_session()
    try:
        existing = (
            db.execute(select(Tenant).where(Tenant.slug == "hashiru")).scalars().first()
        )
        if existing:
            print("Tenant 'hashiru' sudah ada — seed dilewati.")
            return

        tenant = Tenant(name="Hashiru Studio", slug="hashiru")
        db.add(tenant)
        db.flush()

        admin = User(
            tenant_id=tenant.id,
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name="Administrator",
            is_superadmin=True,
        )
        db.add(admin)
        db.flush()
        _audit(db, tenant.id, admin.id, "create", "tenant", tenant.id,
               {"name": tenant.name, "slug": tenant.slug}, "Seed: tenant demo")

        # ---- Struktur organisasi (Sprint 2: identitas + info berversi) ----
        def add_le(name, npwp):
            le = LegalEntity(tenant_id=tenant.id)
            db.add(le)
            db.flush()
            ver = ed.insert_record(
                db=db, tenant_id=tenant.id, model=LegalEntityInfo,
                identity_field="legal_entity_id", identity_value=le.id,
                valid_from=ORG_VALID_FROM,
                values={"name": name, "npwp": npwp},
                event="Pendirian", event_reason="Seed: struktur awal perusahaan",
                created_by=admin.id,
            )
            _audit(db, tenant.id, admin.id, "insert", "legal_entity_info", ver.id,
                   {"name": name}, "Seed: legal entity demo")
            return le

        def add_location(name, timezone="Asia/Jakarta"):
            loc = Location(tenant_id=tenant.id)
            db.add(loc)
            db.flush()
            ver = ed.insert_record(
                db=db, tenant_id=tenant.id, model=LocationInfo,
                identity_field="location_id", identity_value=loc.id,
                valid_from=ORG_VALID_FROM,
                values={"name": name, "timezone": timezone},
                event="Pembukaan", event_reason="Seed: lokasi awal perusahaan",
                created_by=admin.id,
            )
            _audit(db, tenant.id, admin.id, "insert", "location_info", ver.id,
                   {"name": name}, "Seed: lokasi demo")
            return loc

        def add_unit(name, legal_entity, parent=None):
            unit = OrgUnit(tenant_id=tenant.id)
            db.add(unit)
            db.flush()
            ver = ed.insert_record(
                db=db, tenant_id=tenant.id, model=OrgUnitInfo,
                identity_field="org_unit_id", identity_value=unit.id,
                valid_from=ORG_VALID_FROM,
                values={"name": name,
                        "parent_id": parent.id if parent else None,
                        "legal_entity_id": legal_entity.id,
                        "is_active": True},
                event="Pembentukan", event_reason="Seed: struktur awal organisasi",
                created_by=admin.id,
            )
            _audit(db, tenant.id, admin.id, "insert", "org_unit_info", ver.id,
                   {"name": name}, "Seed: unit organisasi demo")
            return unit

        le1 = add_le("PT Hashiru Teknologi", "01.234.567.8-901.234")
        le2 = add_le("PT Hashiru Distribusi", "02.345.678.9-012.345")

        loc_jkt = add_location("Kantor Pusat Jakarta")
        loc_bks = add_location("Gudang Bekasi")

        dit_tech = add_unit("Direktorat Teknologi", le1)
        dit_ops = add_unit("Direktorat Operasi", le2)
        dept_eng = add_unit("Departemen Engineering", le1, parent=dit_tech)
        dept_log = add_unit("Departemen Logistik", le2, parent=dit_ops)
        tim_be = add_unit("Tim Backend", le1, parent=dept_eng)

        # ---- Cost center demo ----
        cc_eng = CostCenter(tenant_id=tenant.id)
        db.add(cc_eng)
        db.flush()
        cc_ver = ed.insert_record(
            db=db, tenant_id=tenant.id, model=CostCenterInfo,
            identity_field="cost_center_id", identity_value=cc_eng.id,
            valid_from=ORG_VALID_FROM,
            values={"code": "CC-ENG-01", "name": "Pusat Biaya Engineering",
                    "org_unit_id": dept_eng.id, "is_active": True},
            event="Pembentukan", event_reason="Seed: cost center demo",
            created_by=admin.id,
        )
        _audit(db, tenant.id, admin.id, "insert", "cost_center_info", cc_ver.id,
               {"code": "CC-ENG-01"}, "Seed: cost center demo")

        job_staff = Job(tenant_id=tenant.id, code="STF", title="Staff")
        job_spv = Job(tenant_id=tenant.id, code="SPV", title="Supervisor")
        job_mgr = Job(tenant_id=tenant.id, code="MGR", title="Manager")
        db.add_all([job_staff, job_spv, job_mgr])
        db.flush()

        pos_be = Position(tenant_id=tenant.id, job_id=job_staff.id,
                          org_unit_id=tim_be.id, name="Backend Engineer")
        pos_em = Position(tenant_id=tenant.id, job_id=job_mgr.id,
                          org_unit_id=dept_eng.id, name="Engineering Manager")
        pos_gud = Position(tenant_id=tenant.id, job_id=job_staff.id,
                           org_unit_id=dept_log.id, name="Staff Gudang")
        db.add_all([pos_be, pos_em, pos_gud])
        db.flush()

        # ---- Karyawan ----
        people = [
            # (nik, nama, legal_entity, start, end, status)
            ("3174010101900001", "Budi Santoso", le1, date(2024, 3, 1), None, "active"),
            ("3174010202920002", "Sari Wijaya", le1, date(2025, 6, 1), None, "active"),
            ("3174010303930003", "Andi Pratama", le2, date(2023, 1, 15), None, "active"),
            ("3174010404940004", "Dewi Lestari", le1, date(2022, 8, 1), None, "active"),
            ("3174010505950005", "Rina Kartika", le2, date(2026, 1, 10),
             date(2026, 12, 31), "contract"),
        ]
        persons, employments = {}, {}
        for nik, nama, le, start, end, status in people:
            p = Person(tenant_id=tenant.id, nik=nik, full_name=nama)
            db.add(p)
            db.flush()
            e = Employment(tenant_id=tenant.id, person_id=p.id,
                           legal_entity_id=le.id, start_date=start,
                           end_date=end, status=status)
            db.add(e)
            db.flush()
            persons[nama] = p
            employments[nama] = e
            _audit(db, tenant.id, admin.id, "create", "person", p.id,
                   {"nik": nik, "full_name": nama}, "Seed: data karyawan demo")
            _audit(db, tenant.id, admin.id, "create", "employment", e.id,
                   {"person_id": str(p.id), "start_date": start.isoformat()},
                   "Seed: data employment demo")

        # ---- Riwayat JobInfo ----
        def add_job(nama, valid_from, job, org_unit, location, event, event_reason,
                    manager_nama=None):
            emp = employments[nama]
            rec = ed.insert_record(
                db=db, tenant_id=tenant.id, model=JobInfo,
                identity_field="employment_id", identity_value=emp.id,
                valid_from=valid_from,
                values={"job_id": job.id, "org_unit_id": org_unit.id,
                        "location_id": location.id,
                        "manager_employment_id": (
                            employments[manager_nama].id if manager_nama else None)},
                event=event, event_reason=event_reason, created_by=admin.id,
            )
            _audit(db, tenant.id, admin.id, "insert", "job_info", rec.id,
                   {"employment": nama, "job": job.title,
                    "valid_from": valid_from.isoformat(), "event": event},
                   f"Seed: {event} — {event_reason}")
            return rec

        add_job("Budi Santoso", date(2024, 3, 1), job_staff, tim_be, loc_jkt,
                "Hire", "Rekrutmen karyawan baru", manager_nama="Dewi Lestari")
        # Skenario PRD 9.3: promosi bertanggal masa depan.
        add_job("Budi Santoso", date(2026, 11, 1), job_spv, tim_be, loc_jkt,
                "Promosi", "Kenaikan jabatan reguler", manager_nama="Dewi Lestari")
        add_job("Sari Wijaya", date(2025, 6, 1), job_staff, tim_be, loc_jkt,
                "Hire", "Rekrutmen karyawan baru", manager_nama="Dewi Lestari")
        add_job("Sari Wijaya", date(2026, 7, 1), job_spv, tim_be, loc_jkt,
                "Promosi", "Kenaikan jabatan reguler", manager_nama="Dewi Lestari")
        add_job("Andi Pratama", date(2023, 1, 15), job_staff, dept_log, loc_bks,
                "Hire", "Rekrutmen karyawan baru")
        add_job("Dewi Lestari", date(2022, 8, 1), job_mgr, dept_eng, loc_jkt,
                "Hire", "Rekrutmen karyawan baru")
        add_job("Rina Kartika", date(2026, 1, 10), job_staff, dept_log, loc_bks,
                "Hire", "Kontrak PKWT 12 bulan")

        # ---- Riwayat CompInfo (nominal integer rupiah) ----
        def add_comp(nama, valid_from, components, event, event_reason):
            emp = employments[nama]
            rec = ed.insert_record(
                db=db, tenant_id=tenant.id, model=CompInfo,
                identity_field="employment_id", identity_value=emp.id,
                valid_from=valid_from,
                values={"pay_group": "Bulanan", "components": components},
                event=event, event_reason=event_reason, created_by=admin.id,
            )
            _audit(db, tenant.id, admin.id, "insert", "comp_info", rec.id,
                   {"employment": nama, "valid_from": valid_from.isoformat(),
                    "event": event}, f"Seed: {event} — {event_reason}")
            return rec

        add_comp("Budi Santoso", date(2024, 3, 1),
                 {"gaji_pokok": 8000000, "tunjangan_tetap": 2000000},
                 "Hire", "Penetapan gaji awal")
        add_comp("Budi Santoso", date(2026, 11, 1),
                 {"gaji_pokok": 11000000, "tunjangan_tetap": 2500000},
                 "Promosi", "Penyesuaian gaji promosi")
        add_comp("Sari Wijaya", date(2025, 6, 1),
                 {"gaji_pokok": 7500000, "tunjangan_tetap": 1500000},
                 "Hire", "Penetapan gaji awal")
        add_comp("Sari Wijaya", date(2026, 7, 1),
                 {"gaji_pokok": 10000000, "tunjangan_tetap": 2000000},
                 "Promosi", "Penyesuaian gaji promosi")
        add_comp("Andi Pratama", date(2023, 1, 15),
                 {"gaji_pokok": 5500000, "tunjangan_tetap": 1000000},
                 "Hire", "Penetapan gaji awal")
        add_comp("Dewi Lestari", date(2022, 8, 1),
                 {"gaji_pokok": 18000000, "tunjangan_tetap": 4000000},
                 "Hire", "Penetapan gaji awal")
        add_comp("Rina Kartika", date(2026, 1, 10),
                 {"gaji_pokok": 5000000, "tunjangan_tetap": 500000},
                 "Hire", "Penetapan gaji awal")

        # ---- RBP: role, group, assignment, field permission ----
        group_all = PermissionGroup(
            tenant_id=tenant.id, name="Semua Karyawan",
            population_rule={"type": "all"})
        db.add(group_all)
        db.flush()

        role_admin = PermissionRole(tenant_id=tenant.id, name="HR Admin",
                                    description="Akses penuh HR")
        role_mgr = PermissionRole(tenant_id=tenant.id, name="Manajer",
                                  description="Melihat data tim")
        role_emp = PermissionRole(tenant_id=tenant.id, name="Karyawan",
                                  description="Akses data sendiri (scoping per-user = S2)")
        db.add_all([role_admin, role_mgr, role_emp])
        db.flush()
        # "Semua Karyawan" hanya membawa role Karyawan. Role HR Admin
        # sengaja tidak di-assign ke grup mana pun di seed (admin memakai
        # jalur superadmin); assignment dilakukan via API bila dibutuhkan.
        # target_population "self": karyawan hanya melihat datanya sendiri
        # (Sprint 2, PRD 15.5).
        db.add(RoleAssignment(tenant_id=tenant.id, role_id=role_emp.id,
                              group_id=group_all.id,
                              target_population={"type": "self"}))
        db.flush()

        def grant(role, object_name, **flags):
            db.add(FieldPermission(tenant_id=tenant.id, role_id=role.id,
                                   object_name=object_name, field_name="*",
                                   **flags))
        # HR Admin: semua objek, semua aksi.
        grant(role_admin, "*",
              can_view=True, can_view_history=True, can_insert=True,
              can_correct=True, can_delete=True)
        # Manajer: baca data + riwayat, tanpa ubah.
        for obj in ("person", "employment", "job_info", "comp_info", "org",
                    "audit_log", "cost_center", "custom_field"):
            grant(role_mgr, obj, can_view=True, can_view_history=True)
        # Karyawan: baca data kini (tanpa riwayat gaji).
        for obj in ("person", "employment", "job_info", "comp_info", "org",
                    "custom_field"):
            grant(role_emp, obj, can_view=True)
        db.flush()

        # ---- User tambahan terikat ke Person ----
        dewi_user = User(
            tenant_id=tenant.id, email="dewi@hashiru.id",
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name="Dewi Lestari", person_id=persons["Dewi Lestari"].id)
        budi_user = User(
            tenant_id=tenant.id, email="budi@hashiru.id",
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name="Budi Santoso", person_id=persons["Budi Santoso"].id)
        db.add_all([dewi_user, budi_user])
        db.flush()
        # Grup dinamis: Manajer = user yang job-nya MGR hari ini.
        # Dewi (Manager) otomatis anggota; Budi (Staff) bukan.
        # target_population "team": manajer melihat direct report-nya
        # (Sprint 2, PRD 15.5).
        mgr_group = PermissionGroup(
            tenant_id=tenant.id, name="Grup Manajer",
            population_rule={"field": "job_id", "op": "=",
                             "value": str(job_mgr.id)})
        db.add(mgr_group)
        db.flush()
        db.add(RoleAssignment(tenant_id=tenant.id, role_id=role_mgr.id,
                              group_id=mgr_group.id,
                              target_population={"type": "team"}))
        db.flush()

        # ---- Definisi custom field demo (Sprint 2, CHR-009) ----
        ukuran_seragam = CustomFieldDefinition(
            tenant_id=tenant.id, object_name="person",
            field_key="ukuran_seragam", label_id="Ukuran Seragam",
            label_en="Uniform Size", field_type="select",
            options=[
                {"value": "S", "label_id": "S", "label_en": "Small", "active": True},
                {"value": "M", "label_id": "M", "label_en": "Medium", "active": True},
                {"value": "L", "label_id": "L", "label_en": "Large", "active": True},
                {"value": "XL", "label_id": "XL", "label_en": "Extra Large",
                 "active": True},
            ],
            created_by_user_id=admin.id,
        )
        db.add(ukuran_seragam)
        db.flush()
        _audit(db, tenant.id, admin.id, "create", "custom_field_definition",
               ukuran_seragam.id, {"field_key": "ukuran_seragam"},
               "Seed: custom field demo")

        db.commit()
        print("Seed selesai:")
        print(f"  tenant : hashiru (id={tenant.id})")
        print(f"  admin  : {ADMIN_EMAIL} / {ADMIN_PASSWORD}  (superadmin)")
        print("  user   : dewi@hashiru.id (Manajer via grup dinamis), budi@hashiru.id (Karyawan)")
        print("  Catatan: role 'HR Admin' belum di-assign ke grup; kelola via API /roles.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
