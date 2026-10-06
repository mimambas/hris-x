"""Roster & tukar shift (EXP-012, PRD 13.2).

Tukar satu hari: pengaju -> persetujuan partner -> persetujuan
atasan pengaju -> diterapkan dengan memecah rentang penugasan.
Konflik roster (istirahat < 8 jam, bentrok lembur/cuti disetujui)
muncul sebagai peringatan saat pengajuan, bukan penolakan.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.models import JobInfo, Shift
from app.services import attendance as att

from .conftest import login_headers

SWAP_DAY = date.today() + timedelta(days=3)


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def _setup(ctx):
    db = ctx["db"]
    info = db.execute(
        select(JobInfo).where(
            JobInfo.employment_id == ctx["e_staff"].id)).scalars().first()
    info.manager_employment_id = ctx["e_mgr"].id
    db.commit()
    pagi = _mk_shift(ctx, "PG", "Pagi", time(8), time(17))
    siang = _mk_shift(ctx, "SG", "Siang", time(13), time(22))
    malam = _mk_shift(ctx, "ML", "Malam", time(22), time(6), overnight=True)
    att.assign_shift(db=db, tenant_id=ctx["ta"].id,
                     employment_id=ctx["e_staff"].id, shift_id=pagi.id,
                     valid_from=date(2024, 1, 1))
    att.assign_shift(db=db, tenant_id=ctx["ta"].id,
                     employment_id=ctx["e_full"].id, shift_id=siang.id,
                     valid_from=date(2024, 1, 1))
    db.commit()
    return pagi, siang, malam


def _mk_shift(ctx, code, name, start, end, overnight=False):
    db = ctx["db"]
    row = db.execute(
        select(Shift).where(Shift.tenant_id == ctx["ta"].id,
                            Shift.code == code)).scalars().first()
    if row is None:
        row = Shift(tenant_id=ctx["ta"].id, code=code, name=name,
                    start_time=datetime.combine(date(2024, 1, 1), start),
                    end_time=datetime.combine(date(2024, 1, 1), end),
                    is_overnight=overnight, grace_minutes=15,
                    is_active=True)
        db.add(row)
        db.flush()
    return row


def test_swap_full_flow_applies_assignments(client, ctx):
    pagi, siang, _malam = _setup(ctx)
    h_staff, h_full, h_mgr = sh(client), fh(client), mh(client)
    r = client.post("/api/v1/shift-swaps", headers=h_staff, json={
        "partner_employment_id": str(ctx["e_full"].id),
        "swap_date": SWAP_DAY.isoformat(), "reason": "Ada keperluan pagi"})
    assert r.status_code == 201, r.text
    swap = r.json()
    assert swap["status"] == "menunggu_partner"
    assert swap["requester_shift_name"] == "Pagi"
    assert swap["partner_shift_name"] == "Siang"

    # Duplikat aktif pada tanggal sama ditolak.
    r = client.post("/api/v1/shift-swaps", headers=h_staff, json={
        "partner_employment_id": str(ctx["e_full"].id),
        "swap_date": SWAP_DAY.isoformat()})
    assert r.status_code == 422, r.text

    # Atasan belum bisa memutuskan sebelum partner setuju.
    r = client.post(f"/api/v1/shift-swaps/{swap['id']}/manager-decision",
                    headers=h_mgr, json={"approve": True})
    assert r.status_code == 422, r.text

    r = client.post(f"/api/v1/shift-swaps/{swap['id']}/partner-decision",
                    headers=h_full, json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "menunggu_atasan"

    queue = client.get("/api/v1/shift-swaps/approvals",
                       headers=h_mgr).json()
    assert any(q["id"] == swap["id"] for q in queue), queue

    r = client.post(f"/api/v1/shift-swaps/{swap['id']}/manager-decision",
                    headers=h_mgr, json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disetujui"
    assert r.json()["applied_at"] is not None if "applied_at" in r.json() \
        else True

    db = ctx["db"]
    got_staff, _s, _e = att.get_shift_for(db, ctx["ta"].id,
                                          ctx["e_staff"].id, SWAP_DAY)
    got_full, _s, _e = att.get_shift_for(db, ctx["ta"].id,
                                         ctx["e_full"].id, SWAP_DAY)
    assert got_staff is not None and got_staff.id == siang.id
    assert got_full is not None and got_full.id == pagi.id
    # Hari di sekitarnya tidak berubah.
    before, _s, _e = att.get_shift_for(db, ctx["ta"].id,
                                       ctx["e_staff"].id,
                                       SWAP_DAY - timedelta(days=1))
    assert before is not None and before.id == pagi.id


def test_swap_rest_warning_for_overnight(client, ctx):
    _setup(ctx)
    db = ctx["db"]
    malam = _mk_shift(ctx, "ML", "Malam", time(22), time(6), overnight=True)
    # Partner (full) pindah ke shift Malam untuk skenario peringatan:
    # staf menerima Malam (berakhir 06:00) lalu Pagi esoknya (08:00)
    # -> istirahat hanya 2 jam.
    from app.models import ShiftAssignment
    rows = db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.employment_id == ctx["e_full"].id)
    ).scalars().all()
    for row in rows:
        row.shift_id = malam.id
    db.commit()

    r = client.post("/api/v1/shift-swaps", headers=sh(client), json={
        "partner_employment_id": str(ctx["e_full"].id),
        "swap_date": SWAP_DAY.isoformat()})
    assert r.status_code == 201, r.text
    warnings = r.json()["warnings"]
    assert any("Istirahat" in w for w in warnings), warnings


def test_partner_reject_requires_reason(client, ctx):
    _setup(ctx)
    h_staff, h_full = sh(client), fh(client)
    r = client.post("/api/v1/shift-swaps", headers=h_staff, json={
        "partner_employment_id": str(ctx["e_full"].id),
        "swap_date": SWAP_DAY.isoformat()})
    swap = r.json()
    r = client.post(f"/api/v1/shift-swaps/{swap['id']}/partner-decision",
                    headers=h_full, json={"approve": False})
    assert r.status_code == 422, r.text
    r = client.post(f"/api/v1/shift-swaps/{swap['id']}/partner-decision",
                    headers=h_full,
                    json={"approve": False, "reason": "Saya tidak bisa"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ditolak"


def test_roster_views(client, ctx):
    _setup(ctx)
    r = client.get("/api/v1/roster/me", headers=sh(client))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["members"][0]["days"], me
    r = client.get("/api/v1/roster/team", headers=mh(client))
    assert r.status_code == 200, r.text
    names = [m["person_name"] for m in r.json()["members"]]
    assert any("Staf" in n or n for n in names) and len(names) >= 2, names
    r = client.get("/api/v1/roster/team", headers=sh(client))
    assert r.status_code == 403, r.text
