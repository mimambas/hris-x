"""Engagement & layanan HR (PRD 13.3): pengumuman EXP-020, survei
anonim EXP-021, kudos EXP-022, helpdesk EXP-023.

Fixture mengikuti tests/conftest.py: admin_a superadmin; u_full = HR
(wildcard); u_mgr = manajer; u_staff = staf.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.models import (
    Employment,
    FieldPermission,
    OrgUnit,
    PermissionRole,
    Person,
    User,
)

from .conftest import PASSWORD, login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def _grant(ctx, role_name, obj, **flags):
    db = ctx["db"]
    role = db.execute(
        select(PermissionRole).where(
            PermissionRole.tenant_id == ctx["ta"].id,
            PermissionRole.name == role_name)).scalar_one()
    db.add(FieldPermission(tenant_id=ctx["ta"].id, role_id=role.id,
                           object_name=obj, field_name="*", **flags))
    db.commit()


def _setup(ctx):
    for role in ("MgrRole", "Inserter"):
        _grant(ctx, role, "announcement", can_view=True)
        _grant(ctx, role, "survey", can_view=True)
        _grant(ctx, role, "kudos", can_view=True, can_insert=True,
               can_correct=True)
        _grant(ctx, role, "helpdesk", can_view=True, can_insert=True)


def _mk_user_emp(ctx, nik, name, email):
    db = ctx["db"]
    p = Person(tenant_id=ctx["ta"].id, nik=nik, full_name=name)
    db.add(p)
    db.flush()
    e = Employment(tenant_id=ctx["ta"].id, person_id=p.id,
                   legal_entity_id=ctx["le"].id,
                   start_date=date(2024, 1, 1), status="active")
    db.add(e)
    db.flush()
    creator = db.execute(
        select(User).where(User.tenant_id == ctx["ta"].id,
                           User.email == "u_mgr@x.id")).scalar_one()
    # JobInfo menempatkan user ini ke grup berbasis lokasi (peran
    # Inserter) seperti fixture conftest.
    from app.models import JobInfo
    from app.services import effective_dating as ed
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=JobInfo,
        identity_field="employment_id", identity_value=e.id,
        valid_from=date(2024, 1, 1),
        values={"job_id": ctx["job_stf"].id, "org_unit_id": ctx["ou"].id,
                "location_id": ctx["loc_b"].id,
                "manager_employment_id": None},
        event="hire", event_reason="Lainnya", created_by=creator.id,
        event_applies_to="lifecycle")
    u = User(tenant_id=ctx["ta"].id, email=email,
             password_hash=hash_password(PASSWORD), full_name=name,
             person_id=p.id, is_superadmin=False)
    db.add(u)
    db.commit()
    return e, u


# ------------------------------------------------------------ EXP-020
def test_announcement_read_flow(client, ctx):
    _setup(ctx)
    h_hr, h_staff = fh(client), sh(client)
    r = client.post("/api/v1/announcements", headers=h_hr, json={
        "title": "Libur bersama", "body": "Kantor tutup Jumat."})
    assert r.status_code == 201, r.text
    ann = r.json()
    assert ann["read_by_me"] is False
    assert ann["target_count"] >= 3

    r = client.get("/api/v1/announcements", headers=h_staff)
    mine = [a for a in r.json() if a["id"] == ann["id"]]
    assert len(mine) == 1 and mine[0]["read_by_me"] is False

    r = client.post(f"/api/v1/announcements/{ann['id']}/read",
                    headers=h_staff)
    assert r.status_code == 200 and r.json()["read_by_me"] is True
    # Idempoten: tandai lagi tidak error.
    r = client.post(f"/api/v1/announcements/{ann['id']}/read",
                    headers=h_staff)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/v1/announcements/{ann['id']}/readers",
                   headers=h_hr)
    readers = {x["person_name"]: x["read_at"] for x in r.json()}
    assert any(v is not None for v in readers.values())

    # Staf tidak boleh membuat pengumuman.
    r = client.post("/api/v1/announcements", headers=h_staff, json={
        "title": "Dari staf", "body": "Tidak boleh."})
    assert r.status_code == 403, r.text


def test_announcement_org_targeting(client, ctx):
    _setup(ctx)
    h_hr, h_staff = fh(client), sh(client)
    db = ctx["db"]
    other = OrgUnit(tenant_id=ctx["ta"].id)
    db.add(other)
    db.commit()
    db.refresh(other)

    r = client.post("/api/v1/announcements", headers=h_hr, json={
        "title": "Khusus unit lain", "body": "Rahasia unit.",
        "target_type": "org_unit", "target_org_unit_id": str(other.id)})
    assert r.status_code == 201, r.text
    ids = {a["id"] for a in client.get(
        "/api/v1/announcements", headers=h_staff).json()}
    assert r.json()["id"] not in ids  # staf bukan anggota unit itu

    r = client.post("/api/v1/announcements", headers=h_hr, json={
        "title": "Unit staf", "body": "Untuk unit Anda.",
        "target_type": "org_unit",
        "target_org_unit_id": str(ctx["ou"].id)})
    assert r.status_code == 201, r.text
    ids = {a["id"] for a in client.get(
        "/api/v1/announcements", headers=h_staff).json()}
    assert r.json()["id"] in ids


# ------------------------------------------------------------ EXP-021
def test_survey_anonymity_and_threshold(client, ctx):
    _setup(ctx)
    h_hr, h_staff, h_mgr = fh(client), sh(client), mh(client)
    r = client.post("/api/v1/surveys", headers=h_hr, json={
        "kind": "enps", "title": "eNPS Q3",
        "question": "Seberapa besar kemungkinan Anda merekomendasikan "
                    "perusahaan ini sebagai tempat bekerja?"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    # Skor di luar rentang 0-10 ditolak.
    r = client.post(f"/api/v1/surveys/{sid}/answer", headers=h_staff,
                    json={"score": 11})
    assert r.status_code == 422, r.text

    r = client.post(f"/api/v1/surveys/{sid}/answer", headers=h_staff,
                    json={"score": 9, "comment": "Bagus"})
    assert r.status_code == 201, r.text
    # Suara ganda dicegah (tanpa identitas tersimpan).
    r = client.post(f"/api/v1/surveys/{sid}/answer", headers=h_staff,
                    json={"score": 5})
    assert r.status_code == 422, r.text
    client.post(f"/api/v1/surveys/{sid}/answer", headers=h_mgr,
                json={"score": 3})

    # Baru 2 responden: agregat disembunyikan (aturan >= 5).
    r = client.get(f"/api/v1/surveys/{sid}/results", headers=h_hr)
    body = r.json()
    assert body["response_count"] == 2
    assert body["enough_responses"] is False
    assert body["average"] is None and body["enps"] is None

    for i, score in enumerate((10, 9, 0)):
        _mk_user_emp(ctx, f"88880000111100{i:02d}", f"Responden {i}",
                     f"resp{i}@x.id")
        h = login_headers(client, "hashiru", f"resp{i}@x.id")
        r = client.post(f"/api/v1/surveys/{sid}/answer", headers=h,
                        json={"score": score})
        assert r.status_code == 201, r.text

    r = client.get(f"/api/v1/surveys/{sid}/results", headers=h_hr)
    body = r.json()
    assert body["enough_responses"] is True
    assert body["response_count"] == 5
    # Skor: 9,3,10,9,0 -> promotor 3, detraktor 2 -> eNPS 20.
    assert body["enps"] == 20
    assert body["average"] == 6.2

    # Hasil hanya untuk HR.
    r = client.get(f"/api/v1/surveys/{sid}/results", headers=h_staff)
    assert r.status_code == 403, r.text


# ------------------------------------------------------------ EXP-022
def test_kudos_flow_and_visibility(client, ctx):
    _setup(ctx)
    h_staff, h_mgr = sh(client), mh(client)
    r = client.post("/api/v1/kudos", headers=h_staff, json={
        "to_employment_id": str(ctx["e_mgr"].id),
        "category": "kolaborasi",
        "message": "Terima kasih sudah membantu deploy!"})
    assert r.status_code == 201, r.text
    kid = r.json()["id"]

    r = client.post("/api/v1/kudos", headers=h_staff, json={
        "to_employment_id": str(ctx["e_staff"].id), "message": "Untukku"})
    assert r.status_code == 422, r.text  # ke diri sendiri

    feed = client.get("/api/v1/kudos/feed", headers=h_mgr).json()
    assert any(k["id"] == kid for k in feed)
    mine = client.get("/api/v1/kudos/mine", headers=h_mgr).json()
    assert len(mine) == 1 and mine[0]["from_name"] is not None

    # Kandidat penerima: memuat orang lain, bukan diri sendiri.
    cands = client.get("/api/v1/kudos/candidates", headers=h_staff).json()
    names = {c["person_name"] for c in cands}
    assert any("Mgr" in n or "Manajer" in n or "Manager" in n
               for n in names) or len(cands) >= 1
    assert all(c["employment_id"] != str(ctx["e_staff"].id)
               for c in cands)

    prof = client.get(f"/api/v1/kudos/profile/{ctx['e_mgr'].id}",
                      headers=h_staff).json()
    assert len(prof) == 1
    r = client.patch(f"/api/v1/kudos/{kid}/visibility", headers=h_mgr,
                     json={"visible_on_profile": False})
    assert r.status_code == 200, r.text
    prof = client.get(f"/api/v1/kudos/profile/{ctx['e_mgr'].id}",
                      headers=h_staff).json()
    assert prof == []
    # Pemilik tetap melihatnya di daftar miliknya.
    mine = client.get("/api/v1/kudos/mine", headers=h_mgr).json()
    assert len(mine) == 1


# ------------------------------------------------------------ EXP-023
def test_helpdesk_ticket_lifecycle(client, ctx):
    _setup(ctx)
    h_hr, h_staff, h_mgr = fh(client), sh(client), mh(client)

    r = client.post("/api/v1/kb/articles", headers=h_hr, json={
        "category": "akun", "title": "Lupa kata sandi",
        "body": "Klik lupa kata sandi di halaman masuk.",
        "keywords": "password sandi lupa"})
    assert r.status_code == 201, r.text
    found = client.get("/api/v1/kb/articles?q=sandi",
                       headers=h_staff).json()
    assert len(found) == 1

    r = client.post("/api/v1/tickets", headers=h_staff, json={
        "category": "akun", "subject": "Tidak bisa masuk aplikasi",
        "description": "Sejak pagi selalu gagal masuk."})
    assert r.status_code == 201, r.text
    ticket = r.json()
    assert ticket["status"] == "baru" and ticket["sla_due_at"]

    # Orang lain tidak bisa membaca tiket staf.
    r = client.get(f"/api/v1/tickets/{ticket['id']}", headers=h_mgr)
    assert r.status_code == 404, r.text

    # HR membalas -> status diproses.
    r = client.post(f"/api/v1/tickets/{ticket['id']}/messages",
                    headers=h_hr, json={"body": "Sudah kami reset, coba lagi."})
    assert r.status_code == 201, r.text
    t = client.get(f"/api/v1/tickets/{ticket['id']}", headers=h_hr).json()
    assert t["status"] == "diproses" and t["message_count"] == 1

    r = client.patch(f"/api/v1/tickets/{ticket['id']}/status",
                     headers=h_hr, json={"status": "selesai"})
    assert r.status_code == 200, r.text
    assert r.json()["resolved_at"] is not None

    # Tiket selesai tidak bisa dibalas lagi.
    r = client.post(f"/api/v1/tickets/{ticket['id']}/messages",
                    headers=h_staff, json={"body": "Masih gagal"})
    assert r.status_code == 422, r.text

    mine = client.get("/api/v1/tickets/mine", headers=h_staff).json()
    assert len(mine) == 1 and mine[0]["status"] == "selesai"
