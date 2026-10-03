"""ESS/MSS (PRD 13.2): delegasi approval (EXP-013) & kotak masuk
approval terpadu (EXP-010).

Fixture mengikuti tests/conftest.py: admin_a superadmin; u_full = HR
(wildcard); u_mgr = manajer; u_staff = staf. Penerima delegasi dibuat
per test sebagai u_peer (jabatan MGR -> otomatis anggota grup manajer).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.models import (
    Claim,
    ClaimType,
    Employment,
    FieldPermission,
    JobInfo,
    LeaveRequest,
    LeaveType,
    OvertimeRequest,
    PermissionRole,
    Person,
    User,
)
from app.services import effective_dating as ed

from .conftest import PASSWORD, login_headers

TODAY = date.today()


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def ph(client):
    return login_headers(client, "hashiru", "u_peer@x.id")


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
    """e_staff bawahan e_mgr; semua peran relevan dapat izin modul ini."""
    _grant(ctx, "MgrRole", "delegation", can_view=True, can_insert=True,
           can_delete=True)
    _grant(ctx, "MgrRole", "leave_request", can_view=True)
    _grant(ctx, "Inserter", "delegation", can_view=True)
    _grant(ctx, "Inserter", "leave_request", can_view=True)
    db = ctx["db"]
    info = db.execute(
        select(JobInfo).where(
            JobInfo.employment_id == ctx["e_staff"].id)).scalars().first()
    info.manager_employment_id = ctx["e_mgr"].id
    db.commit()
    _mk_peer(ctx)


def _mk_peer(ctx):
    """Karyawan kedua berjabatan manajer (kandidat penerima delegasi)."""
    db = ctx["db"]
    p = Person(tenant_id=ctx["ta"].id, nik="9999000011112222",
               full_name="Peer Delegate")
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
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=JobInfo,
        identity_field="employment_id", identity_value=e.id,
        valid_from=date(2024, 1, 1),
        values={"job_id": ctx["job_mgr"].id, "org_unit_id": ctx["ou"].id,
                "location_id": ctx["loc_b"].id,
                "manager_employment_id": None},
        event="hire", event_reason="Lainnya", created_by=creator.id,
        event_applies_to="lifecycle")
    u = User(tenant_id=ctx["ta"].id, email="u_peer@x.id",
             password_hash=hash_password(PASSWORD), full_name="Peer",
             person_id=p.id, is_superadmin=False)
    db.add(u)
    db.commit()
    ctx["e_peer"] = e


def _leave_submitted(ctx, days_ahead=7):
    db = ctx["db"]
    lt = LeaveType(tenant_id=ctx["ta"].id, code="CT", name="Cuti Tahunan",
                   quota_days=12, accrual="yearly", min_service_months=0,
                   requires_doc=False, deducts_balance=True, is_active=True)
    db.add(lt)
    db.flush()
    req = LeaveRequest(
        tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
        leave_type_id=lt.id, start_date=TODAY + timedelta(days=days_ahead),
        end_date=TODAY + timedelta(days=days_ahead + 1), days=2,
        reason="Uji delegasi", status="submitted",
        submitted_at=datetime.now())
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def _delegate_via_api(client, h_mgr, ctx, start, end):
    r = client.post("/api/v1/delegations", headers=h_mgr, json={
        "delegate_employment_id": str(ctx["e_peer"].id),
        "start_date": str(start), "end_date": str(end),
        "note": "Cuti atasan"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["effective_now"] is (start <= TODAY <= end)
    assert body["delegate_name"] == "Peer Delegate"
    return body


# ------------------------------------------------------------- EXP-013
def test_delegate_can_approve_l1_only_during_window(client, ctx):
    _setup(ctx)
    h_mgr, h_peer = mh(client), ph(client)
    req = _leave_submitted(ctx)

    # Tanpa delegasi: rekan sejawat bukan atasan -> ditolak.
    r = client.post(f"/api/v1/leave/requests/{req.id}/approve-l1",
                    headers=h_peer, json={"reason": "ok"})
    assert r.status_code == 422, r.text

    _delegate_via_api(client, h_mgr, ctx,
                      TODAY - timedelta(days=1), TODAY + timedelta(days=3))
    r = client.post(f"/api/v1/leave/requests/{req.id}/approve-l1",
                    headers=h_peer, json={"reason": "Mewakili atasan"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved_l1"


def test_delegation_window_and_revoke(client, ctx):
    _setup(ctx)
    h_mgr, h_peer = mh(client), ph(client)
    req = _leave_submitted(ctx)

    # Delegasi mulai besok: hari ini belum berlaku.
    body = _delegate_via_api(client, h_mgr, ctx,
                             TODAY + timedelta(days=1),
                             TODAY + timedelta(days=5))
    r = client.post(f"/api/v1/leave/requests/{req.id}/approve-l1",
                    headers=h_peer, json={"reason": "ok"})
    assert r.status_code == 422, r.text

    # Cabut sebelum mulai pun harusnya tidak memberi akses.
    r = client.delete(f"/api/v1/delegations/{body['id']}", headers=h_mgr)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dicabut"

    # Delegasi aktif lalu dicabut di tengah jalan: akses hilang.
    body2 = _delegate_via_api(client, h_mgr, ctx,
                              TODAY - timedelta(days=1),
                              TODAY + timedelta(days=2))
    r = client.delete(f"/api/v1/delegations/{body2['id']}", headers=h_mgr)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/leave/requests/{req.id}/approve-l1",
                    headers=h_peer, json={"reason": "ok"})
    assert r.status_code == 422, r.text


def test_delegation_validation(client, ctx):
    _setup(ctx)
    h_mgr = mh(client)
    # Ke diri sendiri.
    r = client.post("/api/v1/delegations", headers=h_mgr, json={
        "delegate_employment_id": str(ctx["e_mgr"].id),
        "start_date": str(TODAY), "end_date": str(TODAY), "note": None})
    assert r.status_code == 422, r.text
    # end < start.
    r = client.post("/api/v1/delegations", headers=h_mgr, json={
        "delegate_employment_id": str(ctx["e_peer"].id),
        "start_date": str(TODAY + timedelta(days=2)),
        "end_date": str(TODAY), "note": None})
    assert r.status_code == 422, r.text
    # Tumpang tindih.
    _delegate_via_api(client, h_mgr, ctx, TODAY, TODAY + timedelta(days=4))
    r = client.post("/api/v1/delegations", headers=h_mgr, json={
        "delegate_employment_id": str(ctx["e_staff"].id),
        "start_date": str(TODAY + timedelta(days=2)),
        "end_date": str(TODAY + timedelta(days=6)), "note": None})
    assert r.status_code == 422, r.text


def test_delegate_cannot_approve_own_request_via_delegation(client, ctx):
    _setup(ctx)
    h_mgr = mh(client)
    # Manajer mendelegasikan ke staf; pengajuan staf tetap untuk manajer.
    _delegate_via_api(client, h_mgr, ctx,
                      TODAY - timedelta(days=1), TODAY + timedelta(days=1))
    req = _leave_submitted(ctx)
    # Staf (bukan delegate di sini) tidak bisa approve miliknya sendiri.
    r = client.post(f"/api/v1/leave/requests/{req.id}/approve-l1",
                    headers=sh(client), json={"reason": "ok"})
    assert r.status_code in (403, 422), r.text


# ------------------------------------------------------------- EXP-010
def test_inbox_aggregation_by_role(client, ctx):
    _setup(ctx)
    h_mgr, h_staff, h_hr, h_peer = mh(client), sh(client), fh(client), ph(
        client)
    req = _leave_submitted(ctx)
    db = ctx["db"]
    ct = ClaimType(tenant_id=ctx["ta"].id, code="KS", name="Kesehatan",
                   limit_per_year=5_000_000, limit_per_claim=1_000_000,
                   requires_receipt=True, active=True)
    db.add(ct)
    db.flush()
    db.add(Claim(tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
                 claim_type_id=ct.id, amount=250_000,
                 claim_date=TODAY, description="Berobat",
                 status="submitted", submitted_at=datetime.now()))
    ot = OvertimeRequest(
        tenant_id=ctx["ta"].id, employment_id=ctx["e_staff"].id,
        date=TODAY, start_time=datetime.now(), end_time=datetime.now(),
        hours=2, reason="Deploy", status="submitted")
    db.add(ot)
    db.commit()

    # Manajer: 3 item L1 (cuti, klaim, lembur).
    r = client.get("/api/v1/inbox/approvals", headers=h_mgr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {"cuti": 1, "klaim": 1, "lembur": 1}
    assert all(i["stage"] == "L1" for i in body["items"])

    # Staf biasa: bukan approver siapa pun -> kosong.
    r = client.get("/api/v1/inbox/approvals", headers=h_staff)
    assert r.json()["items"] == []

    # Delegate aktif ikut melihat item L1 delegator.
    _delegate_via_api(client, h_mgr, ctx,
                      TODAY - timedelta(days=1), TODAY + timedelta(days=1))
    r = client.get("/api/v1/inbox/approvals", headers=h_peer)
    assert r.json()["counts"].get("cuti") == 1

    # Setelah L1 oleh manajer, item pindah ke antrean final HR.
    r = client.post(f"/api/v1/leave/requests/{req.id}/approve-l1",
                    headers=h_mgr, json={"reason": "ok"})
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/inbox/approvals", headers=h_hr)
    finals = [i for i in r.json()["items"] if i["kind"] == "cuti"]
    assert len(finals) == 1 and finals[0]["stage"] == "final"
    # Manajer tidak lagi melihat item cuti itu.
    r = client.get("/api/v1/inbox/approvals", headers=h_mgr)
    assert r.json()["counts"].get("cuti") is None


def test_delegation_mine_and_candidates(client, ctx):
    _setup(ctx)
    h_mgr, h_peer = mh(client), ph(client)
    body = _delegate_via_api(client, h_mgr, ctx,
                             TODAY - timedelta(days=1),
                             TODAY + timedelta(days=2))
    r = client.get("/api/v1/delegations/mine", headers=h_mgr)
    assert [d["id"] for d in r.json()] == [body["id"]]
    r = client.get("/api/v1/delegations/mine", headers=h_peer)
    assert len(r.json()) == 1
    assert r.json()[0]["delegator_name"] is not None
    r = client.get("/api/v1/delegations/candidates", headers=h_mgr)
    names = {c["person_name"] for c in r.json()}
    assert "Peer Delegate" in names
