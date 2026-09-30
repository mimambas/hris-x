"""Fixture Sprint 1: DB in-memory per test + data dasar 2 tenant.

Tenant A (hashiru):
  lokasi: loc_a, loc_b, loc_c | job: STF, MGR
  grup dinamis:
    g_all  {"type":"all"}                          -> role Empty (tanpa izin)
    g_hr   {"field":"location_id","=":loc_a}        -> role HR (semua izin)
    g_ins  {"field":"location_id","=":loc_b}        -> role Inserter (job_info: insert+view)
    g_mgr  {"field":"job_id","=":MGR}               -> role MgrRole (person: view+history)
  user:
    admin_a  superadmin (tanpa person)
    u_full   person loc_a/STF  -> HR penuh
    u_mgr    person loc_b/MGR  -> Inserter + MgrRole
    u_staff  person loc_b/STF  -> Inserter saja
    u_none   person loc_c/STF  -> Empty saja (default DENY)

Tenant B (acme): admin_b superadmin + 1 person/employment (uji isolasi).
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.db import new_session
from app.core.security import hash_password
from app.main import create_app
from app.models import (
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
    RoleAssignment,
    Tenant,
    User,
)
from app.services import effective_dating as ed

PASSWORD = "Password123!"


@pytest.fixture()
def app():
    return create_app("sqlite://")


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _mkuser(db, tenant_id, email, person_id=None, superadmin=False):
    u = User(
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(PASSWORD),
        full_name=email.split("@")[0],
        person_id=person_id,
        is_superadmin=superadmin,
    )
    db.add(u)
    db.flush()
    return u


def _mkperson_emp_job(db, tenant_id, nik, name, le_id, loc_id, job_id, org_id,
                      created_by, start=date(2024, 1, 1)):
    p = Person(tenant_id=tenant_id, nik=nik, full_name=name)
    db.add(p)
    db.flush()
    e = Employment(tenant_id=tenant_id, person_id=p.id, legal_entity_id=le_id,
                   start_date=start, status="active")
    db.add(e)
    db.flush()
    j = ed.insert_record(
        db=db, tenant_id=tenant_id, model=JobInfo,
        identity_field="employment_id", identity_value=e.id,
        valid_from=start,
        values={"job_id": job_id, "org_unit_id": org_id, "location_id": loc_id,
                "manager_employment_id": None},
        event="Hire", event_reason="Fixture", created_by=created_by,
    )
    return p, e, j


@pytest.fixture()
def ctx(app):
    db = new_session()
    try:
        # ---- Tenant A ----
        ta = Tenant(name="Hashiru", slug="hashiru")
        db.add(ta)
        db.flush()
        # Admin dibuat di awal agar bisa menjadi created_by record fixture.
        admin_a = _mkuser(db, ta.id, "admin_a@x.id", superadmin=True)

        # ---- Struktur organisasi S2: identitas + info berversi ----
        org_from = date(2020, 1, 1)

        def _mk_le(name, npwp):
            row = LegalEntity(tenant_id=ta.id)
            db.add(row)
            db.flush()
            ed.insert_record(
                db=db, tenant_id=ta.id, model=LegalEntityInfo,
                identity_field="legal_entity_id", identity_value=row.id,
                valid_from=org_from,
                values={"name": name, "npwp": npwp},
                event="Pendirian", event_reason="Fixture", created_by=admin_a.id)
            return row

        def _mk_loc(name):
            row = Location(tenant_id=ta.id)
            db.add(row)
            db.flush()
            ed.insert_record(
                db=db, tenant_id=ta.id, model=LocationInfo,
                identity_field="location_id", identity_value=row.id,
                valid_from=org_from,
                values={"name": name, "timezone": "Asia/Jakarta"},
                event="Pembukaan", event_reason="Fixture", created_by=admin_a.id)
            return row

        def _mk_ou(name, le_row, parent=None):
            row = OrgUnit(tenant_id=ta.id)
            db.add(row)
            db.flush()
            ed.insert_record(
                db=db, tenant_id=ta.id, model=OrgUnitInfo,
                identity_field="org_unit_id", identity_value=row.id,
                valid_from=org_from,
                values={"name": name, "parent_id": parent.id if parent else None,
                        "legal_entity_id": le_row.id, "is_active": True},
                event="Pembentukan", event_reason="Fixture", created_by=admin_a.id)
            return row

        le = _mk_le("PT Hashiru", "01")
        loc_a = _mk_loc("Loc A")
        loc_b = _mk_loc("Loc B")
        loc_c = _mk_loc("Loc C")
        ou = _mk_ou("Eng", le)
        job_stf = Job(tenant_id=ta.id, code="STF", title="Staff")
        job_mgr = Job(tenant_id=ta.id, code="MGR", title="Manager")
        db.add_all([job_stf, job_mgr])
        db.flush()

        # ---- Role & grup ----
        def role(name):
            r = PermissionRole(tenant_id=ta.id, name=name)
            db.add(r)
            db.flush()
            return r

        def group(name, rule):
            g = PermissionGroup(tenant_id=ta.id, name=name, population_rule=rule)
            db.add(g)
            db.flush()
            return g

        def grant(r, obj, **flags):
            db.add(FieldPermission(tenant_id=ta.id, role_id=r.id,
                                   object_name=obj, field_name="*", **flags))

        r_empty = role("Empty")
        r_hr = role("HR")
        r_ins = role("Inserter")
        r_mgr = role("MgrRole")

        g_all = group("g_all", {"type": "all"})
        g_hr = group("g_hr", {"field": "location_id", "op": "=",
                              "value": str(loc_a.id)})
        g_ins = group("g_ins", {"field": "location_id", "op": "=",
                                "value": str(loc_b.id)})
        g_mgr = group("g_mgr", {"field": "job_id", "op": "=",
                                "value": str(job_mgr.id)})

        db.add_all([
            RoleAssignment(tenant_id=ta.id, role_id=r_empty.id, group_id=g_all.id),
            RoleAssignment(tenant_id=ta.id, role_id=r_hr.id, group_id=g_hr.id),
            RoleAssignment(tenant_id=ta.id, role_id=r_ins.id, group_id=g_ins.id),
            # Sprint 2: manajer hanya melihat direct report-nya (PRD 15.5).
            RoleAssignment(tenant_id=ta.id, role_id=r_mgr.id, group_id=g_mgr.id,
                           target_population={"type": "team"}),
        ])
        grant(r_hr, "*", can_view=True, can_view_history=True, can_insert=True,
              can_correct=True, can_delete=True)
        grant(r_ins, "job_info", can_view=True, can_insert=True)
        grant(r_ins, "employment", can_view=True)
        grant(r_mgr, "person", can_view=True, can_view_history=True)

        # ---- User + person/employment/job ----
        p_full, e_full, _ = _mkperson_emp_job(
            db, ta.id, "1111111111111111", "Full", le.id, loc_a.id,
            job_stf.id, ou.id, admin_a.id)
        p_mgr, e_mgr, _ = _mkperson_emp_job(
            db, ta.id, "2222222222222222", "Mgr", le.id, loc_b.id,
            job_mgr.id, ou.id, admin_a.id)
        p_staff, e_staff, _ = _mkperson_emp_job(
            db, ta.id, "3333333333333333", "Staff", le.id, loc_b.id,
            job_stf.id, ou.id, admin_a.id)
        p_none, e_none, _ = _mkperson_emp_job(
            db, ta.id, "4444444444444444", "None", le.id, loc_c.id,
            job_stf.id, ou.id, admin_a.id)
        u_full = _mkuser(db, ta.id, "u_full@x.id", person_id=p_full.id)
        u_mgr = _mkuser(db, ta.id, "u_mgr@x.id", person_id=p_mgr.id)
        u_staff = _mkuser(db, ta.id, "u_staff@x.id", person_id=p_staff.id)
        u_none = _mkuser(db, ta.id, "u_none@x.id", person_id=p_none.id)

        # ---- Tenant B ----
        tb = Tenant(name="Acme", slug="acme")
        db.add(tb)
        db.flush()
        admin_b = _mkuser(db, tb.id, "admin_b@x.id", superadmin=True)
        p_b = Person(tenant_id=tb.id, nik="9999999999999999", full_name="Orang B")
        db.add(p_b)
        db.flush()
        le_b = LegalEntity(tenant_id=tb.id)
        db.add(le_b)
        db.flush()
        e_b = Employment(tenant_id=tb.id, person_id=p_b.id,
                         legal_entity_id=le_b.id, start_date=date(2024, 1, 1),
                         status="active")
        db.add(e_b)
        db.flush()

        db.commit()
        yield {
            "db": db,
            "ta": ta, "tb": tb,
            "loc_a": loc_a, "loc_b": loc_b, "loc_c": loc_c,
            "job_stf": job_stf, "job_mgr": job_mgr,
            "ou": ou, "le": le,
            "e_full": e_full, "e_mgr": e_mgr, "e_staff": e_staff,
            "p_b": p_b, "e_b": e_b,
        }
    finally:
        db.close()


def login_headers(client, slug, email, password=PASSWORD):
    r = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": slug, "email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
