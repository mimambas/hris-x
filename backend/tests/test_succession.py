"""Suksesi & karier (SUC, PRD 12.6): profil talent (SUC-001), posisi
kunci & nominasi suksesor (SUC-002), talent pool dari 9-box (SUC-003),
jalur karier & IDP (SUC-004), marketplace internal + privasi atasan
(SUC-005), governance skill (SUC-006, tanpa inferensi AI).

Fixture mengikuti tests/conftest.py: admin_a superadmin; u_full = HR
(wildcard, is_hr via payroll:correct); u_mgr = manajer; u_staff = staf.
Grant objek "talent" untuk peran non-HR dipasang per test lewat DB.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    Appraisal,
    FieldPermission,
    JobInfo,
    PermissionRole,
    Position,
    ReviewCycle,
    RoleAssignment,
)

from .conftest import login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def _grant(ctx, role_name, **flags):
    db = ctx["db"]
    role = db.execute(
        select(PermissionRole).where(
            PermissionRole.tenant_id == ctx["ta"].id,
            PermissionRole.name == role_name)).scalar_one()
    db.add(FieldPermission(tenant_id=ctx["ta"].id, role_id=role.id,
                           object_name="talent", field_name="*", **flags))
    db.commit()


def _mk_self_talent_role(client, h_admin, name="SelfTalent"):
    """Peran talent (view/insert/correct) berpopulasi 'self' via API RBAC
    — pola yang sama seperti test populasi Sprint 2."""
    r = client.post("/api/v1/roles", headers=h_admin,
                    json={"name": name, "reason": "test"})
    assert r.status_code == 201, r.text
    role_id = r.json()["id"]
    r = client.post(
        f"/api/v1/roles/{role_id}/field-permissions", headers=h_admin,
        json={"object_name": "talent", "can_view": True,
              "can_insert": True, "can_correct": True, "reason": "test"})
    assert r.status_code == 201, r.text
    # Populasi target dihitung dari izin objek "person" (population.py),
    # jadi peran pembatas wajib juga memegang person:view.
    r = client.post(
        f"/api/v1/roles/{role_id}/field-permissions", headers=h_admin,
        json={"object_name": "person", "can_view": True, "reason": "test"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/groups", headers=h_admin,
                    json={"name": f"G-{name}",
                          "population_rule": {"type": "all"},
                          "reason": "test"})
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/v1/roles/{role_id}/assign", headers=h_admin,
        json={"group_id": r.json()["id"],
              "target_population": {"type": "self"}, "reason": "test"})
    assert r.status_code == 201, r.text


def _setup_staff_mgr(ctx):
    """Staf dapat talent view/insert/update; manajer view+correct; dan
    e_staff menjadi bawahan langsung e_mgr (populasi team)."""
    _grant(ctx, "Inserter", can_view=True, can_insert=True, can_correct=True)
    _grant(ctx, "MgrRole", can_view=True, can_correct=True)
    db = ctx["db"]
    info = db.execute(
        select(JobInfo).where(
            JobInfo.employment_id == ctx["e_staff"].id)).scalars().first()
    info.manager_employment_id = ctx["e_mgr"].id
    db.commit()


def _mk_position(ctx, name="Kepala Gudang", is_key=False):
    db = ctx["db"]
    pos = Position(tenant_id=ctx["ta"].id, job_id=ctx["job_stf"].id,
                   org_unit_id=ctx["ou"].id, name=name, is_key=is_key)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


# ------------------------------------------------------------ SUC-006/001
def test_skill_governance_flow(client, ctx):
    _setup_staff_mgr(ctx)
    h_staff, h_hr = sh(client), fh(client)
    # Staf mengusulkan skill -> status "usulan".
    r = client.post("/api/v1/talent/skills", headers=h_staff,
                    json={"name": "Figma", "category": "Desain"})
    assert r.status_code == 201, r.text
    skill = r.json()
    assert skill["status"] == "usulan"
    # Staf menempelkan skill usulan ke profilnya.
    r = client.post(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/skills",
        headers=h_staff,
        json={"skill_id": skill["id"], "proficiency": 4})
    assert r.status_code == 201, r.text
    assert r.json()["skill_status"] == "usulan"
    # Profil: skill usulan BELUM terhitung resmi.
    r = client.get(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/profile",
        headers=h_staff)
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["skills"] == []
    assert [s["skill_name"] for s in prof["pending_skills"]] == ["Figma"]
    # Non-HR tidak boleh memutuskan governance.
    r = client.post(f"/api/v1/talent/skills/{skill['id']}/decision",
                    headers=h_staff, json={"decision": "setujui"})
    assert r.status_code == 403, r.text
    # HR menyetujui -> kini terhitung resmi; keputusan kedua ditolak.
    r = client.post(f"/api/v1/talent/skills/{skill['id']}/decision",
                    headers=h_hr, json={"decision": "setujui"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disetujui"
    r = client.post(f"/api/v1/talent/skills/{skill['id']}/decision",
                    headers=h_hr, json={"decision": "tolak"})
    assert r.status_code == 422, r.text
    r = client.get(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/profile",
        headers=h_staff)
    assert [s["skill_name"] for s in r.json()["skills"]] == ["Figma"]
    assert r.json()["pending_skills"] == []
    # Nama skill duplikat di katalog ditolak.
    r = client.post("/api/v1/talent/skills", headers=h_hr,
                    json={"name": "Figma"})
    assert r.status_code == 422, r.text


def test_profile_aggregation_and_mobility(client, ctx):
    _setup_staff_mgr(ctx)
    h_admin, h_staff = ah(client), sh(client)
    # Kursus selesai (via Learning) -> sertifikasi tampil di profil.
    r = client.post("/api/v1/performance/courses", headers=h_admin, json={
        "code": "K3-01", "name": "Keselamatan Kerja", "duration_hours": 8,
        "cert_validity_months": 12})
    assert r.status_code == 201, r.text
    course = r.json()
    r = client.post("/api/v1/performance/enrollments", headers=h_admin,
                    json={"employment_id": str(ctx["e_staff"].id),
                          "course_id": course["id"]})
    assert r.status_code == 201, r.text
    enr = r.json()
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete",
        headers=h_admin, json={})
    assert r.status_code == 200, r.text
    # Staf memperbarui preferensi mobilitas & aspirasi miliknya.
    r = client.put(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/profile",
        headers=h_staff,
        json={"mobility_preference": "luar_kota",
              "career_aspiration": "Menjadi supervisor gudang"})
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["person_name"] == "Staff"
    assert prof["job_title"] == "Staff"
    assert prof["mobility_preference"] == "luar_kota"
    assert prof["career_aspiration"] == "Menjadi supervisor gudang"
    assert [c["course_name"] for c in prof["certifications"]] == [
        "Keselamatan Kerja"]
    assert prof["certifications"][0]["cert_expires_at"] is not None


def test_profile_scope_and_tenant_isolation(client, ctx):
    h_admin = ah(client)
    h_none = login_headers(client, "hashiru", "u_none@x.id")
    # Tanpa izin talent sama sekali -> 403 di gerbang izin.
    r = client.get(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/profile",
        headers=h_none)
    assert r.status_code == 403, r.text
    # Beri peran talent berpopulasi "self": hanya profil sendiri.
    _mk_self_talent_role(client, h_admin)
    r = client.get(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/profile",
        headers=h_none)
    assert r.status_code == 404, r.text  # orang lain -> 404
    db = ctx["db"]
    # ctx tidak mengekspos employment u_none; cari lewat DB.
    from app.models import Employment, Person
    p_none = db.execute(
        select(Person).where(Person.full_name == "None")).scalar_one()
    e_none = db.execute(
        select(Employment).where(
            Employment.person_id == p_none.id)).scalar_one()
    r = client.get(
        f"/api/v1/talent/employments/{e_none.id}/profile",
        headers=h_none)
    assert r.status_code == 200, r.text
    assert r.json()["person_name"] == "None"
    # Tenant lain -> 404 walau superadmin tenant sendiri.
    r = client.get(
        f"/api/v1/talent/employments/{ctx['e_b'].id}/profile",
        headers=h_admin)
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------- SUC-002
def test_key_positions_and_gaps(client, ctx):
    h_hr, h_mgr = fh(client), mh(client)
    pos = _mk_position(ctx)
    # Manajer tidak boleh mengakses perencanaan suksesi.
    r = client.get("/api/v1/talent/key-positions", headers=h_mgr)
    assert r.status_code == 403, r.text
    # Nominasi sebelum posisi ditandai kunci -> ditolak.
    r = client.post(
        f"/api/v1/talent/positions/{pos.id}/nominations",
        headers=h_hr,
        json={"employment_id": str(ctx["e_full"].id),
              "readiness": "siap_sekarang"})
    assert r.status_code == 422, r.text
    # Tandai kunci -> langsung tercatat sebagai gap (belum ada suksesor).
    r = client.patch(f"/api/v1/talent/positions/{pos.id}/key",
                     headers=h_hr, json={"is_key": True})
    assert r.status_code == 200, r.text
    assert r.json()["has_ready_successor"] is False
    r = client.get("/api/v1/talent/key-positions/gaps", headers=h_hr)
    assert [g["position_id"] for g in r.json()] == [str(pos.id)]
    # Suksesor belum siap -> tetap gap.
    r = client.post(
        f"/api/v1/talent/positions/{pos.id}/nominations",
        headers=h_hr,
        json={"employment_id": str(ctx["e_full"].id),
              "readiness": "siap_2_tahun"})
    assert r.status_code == 201, r.text
    r = client.get("/api/v1/talent/key-positions/gaps", headers=h_hr)
    assert len(r.json()) == 1
    # Nominasi duplikat ditolak.
    r = client.post(
        f"/api/v1/talent/positions/{pos.id}/nominations",
        headers=h_hr,
        json={"employment_id": str(ctx["e_full"].id),
              "readiness": "siap_sekarang"})
    assert r.status_code == 422, r.text
    # Suksesor siap sekarang -> gap tertutup.
    r = client.post(
        f"/api/v1/talent/positions/{pos.id}/nominations",
        headers=h_hr,
        json={"employment_id": str(ctx["e_mgr"].id),
              "readiness": "siap_sekarang"})
    assert r.status_code == 201, r.text
    r = client.get("/api/v1/talent/key-positions/gaps", headers=h_hr)
    assert r.json() == []
    r = client.get("/api/v1/talent/key-positions", headers=h_hr)
    assert r.json()[0]["has_ready_successor"] is True
    assert {n["person_name"] for n in r.json()[0]["nominations"]} == {
        "Full", "Mgr"}


# ---------------------------------------------------------------- SUC-003
def test_talent_pool_from_nine_box(client, ctx):
    h_hr, h_staff = fh(client), sh(client)
    db = ctx["db"]
    cycle = ReviewCycle(tenant_id=ctx["ta"].id, name="Siklus 2026",
                        year=2026, status="closed",
                        start_date=date(2026, 1, 1),
                        end_date=date(2026, 12, 31))
    db.add(cycle)
    db.flush()
    # Full: kinerja tinggi + potensi tinggi -> "star".
    db.add(Appraisal(tenant_id=ctx["ta"].id,
                     employment_id=ctx["e_full"].id, cycle_id=cycle.id,
                     final_score=Decimal("4.50"), potential_score=5))
    # Staff: kinerja rendah + potensi rendah -> "low_performer".
    db.add(Appraisal(tenant_id=ctx["ta"].id,
                     employment_id=ctx["e_staff"].id, cycle_id=cycle.id,
                     final_score=Decimal("1.50"), potential_score=1))
    db.commit()
    r = client.post("/api/v1/talent/pools", headers=h_hr, json={
        "name": "Pool Bintang 2026", "cycle_id": str(cycle.id),
        "box_keys": ["star", "high_potential"]})
    assert r.status_code == 201, r.text
    pool = r.json()
    assert [(m["person_name"], m["box_key"]) for m in pool["members"]] == [
        ("Full", "star")]
    # Kunci kotak tak dikenal ditolak; non-HR ditolak.
    r = client.post("/api/v1/talent/pools", headers=h_hr, json={
        "name": "Pool Aneh", "cycle_id": str(cycle.id),
        "box_keys": ["kotak_ngawur"]})
    assert r.status_code == 422, r.text
    r = client.post("/api/v1/talent/pools", headers=h_staff, json={
        "name": "Pool Staf", "cycle_id": str(cycle.id),
        "box_keys": ["star"]})
    assert r.status_code == 403, r.text
    # Daftar pool memuat snapshot yang sama.
    r = client.get("/api/v1/talent/pools", headers=h_hr)
    assert len(r.json()) == 1
    assert r.json()[0]["members"][0]["box_key"] == "star"


# ---------------------------------------------------------------- SUC-004
def test_career_path_and_idp(client, ctx):
    _setup_staff_mgr(ctx)
    h_hr, h_staff = fh(client), sh(client)
    r = client.post("/api/v1/talent/career-paths", headers=h_hr, json={
        "from_job_id": str(ctx["job_stf"].id),
        "to_job_id": str(ctx["job_mgr"].id),
        "notes": "Promosi berbasis kinerja"})
    assert r.status_code == 201, r.text
    assert r.json()["from_job_title"] == "Staff"
    assert r.json()["to_job_title"] == "Manager"
    r = client.post("/api/v1/talent/career-paths", headers=h_hr, json={
        "from_job_id": str(ctx["job_stf"].id),
        "to_job_id": str(ctx["job_mgr"].id)})
    assert r.status_code == 422, r.text  # duplikat
    # Staf membuat IDP untuk dirinya, menargetkan jabatan Manager.
    r = client.post("/api/v1/talent/idps", headers=h_staff, json={
        "employment_id": str(ctx["e_staff"].id),
        "target_job_id": str(ctx["job_mgr"].id), "year": 2027})
    assert r.status_code == 201, r.text
    idp = r.json()
    assert idp["target_job_title"] == "Manager"
    r = client.post("/api/v1/talent/idps", headers=h_staff, json={
        "employment_id": str(ctx["e_staff"].id), "year": 2027})
    assert r.status_code == 422, r.text  # tahun yang sama
    # IDP untuk orang lain oleh yang berpopulasi "self" -> 403.
    _mk_self_talent_role(client, ah(client), name="SelfTalentIdp")
    h_none = login_headers(client, "hashiru", "u_none@x.id")
    r = client.post("/api/v1/talent/idps", headers=h_none, json={
        "employment_id": str(ctx["e_full"].id), "year": 2027})
    assert r.status_code == 403, r.text
    # Item IDP terhubung ke kursus Learning (SUC-004).
    r = client.post("/api/v1/performance/courses", headers=ah(client),
                    json={"code": "LDR-01", "name": "Kepemimpinan Dasar",
                          "duration_hours": 16})
    assert r.status_code == 201, r.text
    course = r.json()
    r = client.post(f"/api/v1/talent/idps/{idp['id']}/items",
                    headers=h_staff,
                    json={"title": "Selesaikan kursus kepemimpinan",
                          "course_id": course["id"],
                          "target_date": "2027-06-30"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["course_name"] == "Kepemimpinan Dasar"
    assert item["status"] == "belum"
    r = client.patch(f"/api/v1/talent/idp-items/{item['id']}",
                     headers=h_staff, json={"status": "selesai"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "selesai"
    # Daftar IDP staf memuat item yang sudah selesai.
    r = client.get(
        f"/api/v1/talent/employments/{ctx['e_staff'].id}/idps",
        headers=h_staff)
    assert r.status_code == 200, r.text
    assert r.json()[0]["items"][0]["status"] == "selesai"


# ---------------------------------------------------------------- SUC-005
def test_internal_marketplace_privacy(client, ctx):
    _setup_staff_mgr(ctx)
    h_hr, h_mgr, h_staff = fh(client), mh(client), sh(client)
    r = client.post("/api/v1/talent/opportunities", headers=h_hr, json={
        "kind": "proyek", "title": "Proyek Digitalisasi Arsip",
        "description": "Migrasi arsip fisik ke digital"})
    assert r.status_code == 201, r.text
    opp = r.json()
    # Staf melamar.
    r = client.post(f"/api/v1/talent/opportunities/{opp['id']}/apply",
                    headers=h_staff,
                    json={"cover_note": "Saya tertarik dan siap belajar"})
    assert r.status_code == 201, r.text
    app_row = r.json()
    assert app_row["status"] == "diajukan"
    # Lamaran ganda ditolak.
    r = client.post(f"/api/v1/talent/opportunities/{opp['id']}/apply",
                    headers=h_staff, json={})
    assert r.status_code == 422, r.text
    # PRIVASI PRD: atasan pelamar TIDAK melihat lamaran tahap "diajukan".
    r = client.get(
        f"/api/v1/talent/opportunities/{opp['id']}/applications",
        headers=h_mgr)
    assert r.status_code == 200, r.text
    assert r.json() == []
    # HR tidak boleh langsung menerima tanpa tahap seleksi.
    r = client.post(
        f"/api/v1/talent/applications/{app_row['id']}/decision",
        headers=h_hr, json={"status": "diterima"})
    assert r.status_code == 422, r.text
    r = client.post(
        f"/api/v1/talent/applications/{app_row['id']}/decision",
        headers=h_hr, json={"status": "seleksi"})
    assert r.status_code == 200, r.text
    # Setelah seleksi, atasan boleh melihatnya.
    r = client.get(
        f"/api/v1/talent/opportunities/{opp['id']}/applications",
        headers=h_mgr)
    assert [a["person_name"] for a in r.json()] == ["Staff"]
    # Manajer tidak berhak memutuskan lamaran.
    r = client.post(
        f"/api/v1/talent/applications/{app_row['id']}/decision",
        headers=h_mgr, json={"status": "diterima"})
    assert r.status_code == 403, r.text
    # HR menerima -> final; keputusan berikutnya ditolak.
    r = client.post(
        f"/api/v1/talent/applications/{app_row['id']}/decision",
        headers=h_hr, json={"status": "diterima"})
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/talent/applications/{app_row['id']}/decision",
        headers=h_hr, json={"status": "ditolak"})
    assert r.status_code == 422, r.text
    # Pelamar melihat lamarannya sendiri.
    r = client.get("/api/v1/talent/applications/mine", headers=h_staff)
    assert [a["status"] for a in r.json()] == ["diterima"]


def test_opportunity_visibility_and_close(client, ctx):
    _setup_staff_mgr(ctx)
    h_hr, h_staff = fh(client), sh(client)
    r = client.post("/api/v1/talent/opportunities", headers=h_hr, json={
        "kind": "gig", "title": "Gig Dokumentasi SOP"})
    assert r.status_code == 201, r.text
    opp = r.json()
    r = client.get("/api/v1/talent/opportunities", headers=h_staff)
    assert [o["id"] for o in r.json()] == [opp["id"]]
    # Ditutup oleh HR -> hilang dari daftar staf, tetap terlihat HR.
    r = client.post(f"/api/v1/talent/opportunities/{opp['id']}/close",
                    headers=h_hr, json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ditutup"
    r = client.get("/api/v1/talent/opportunities", headers=h_staff)
    assert r.json() == []
    r = client.get("/api/v1/talent/opportunities", headers=h_hr)
    assert len(r.json()) == 1
    # Melamar peluang tertutup ditolak.
    r = client.post(f"/api/v1/talent/opportunities/{opp['id']}/apply",
                    headers=h_staff, json={})
    assert r.status_code == 422, r.text


def test_candidates_resolve_nama_untuk_non_hr(client, ctx):
    """Dropdown suksesi: nama ter-resolve server untuk non-HR."""
    _grant(ctx, "Inserter", can_view=True)
    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get("/api/v1/talent/candidates", headers=h_staff)
    assert r.status_code == 200, r.text
    names = {c["person_name"] for c in r.json()}
    assert "Staff" in names and "Full" in names, names
    mine = next(c for c in r.json() if c["person_name"] == "Staff")
    assert mine["employment_id"] == str(ctx["e_staff"].id)

    r = client.get("/api/v1/talent/candidates", headers=fh(client))
    assert r.status_code == 200, r.text
    assert {c["person_name"] for c in r.json()} >= {"Full", "Mgr",
                                                    "Staff"}

    # Tanpa izin talent: default deny.
    r = client.get("/api/v1/talent/candidates",
                   headers=login_headers(client, "hashiru",
                                         "u_none@x.id"))
    assert r.status_code == 403, r.text
