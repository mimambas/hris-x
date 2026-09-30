"""Uji RBP: default DENY, grup dinamis, beda izin insert vs correct."""

from __future__ import annotations

from datetime import date

from tests.conftest import login_headers


def test_tanpa_izin_efektif_ditolak(client, ctx):
    # u_none hanya punya role Empty (tanpa field permission).
    h = login_headers(client, "hashiru", "u_none@x.id")
    assert client.get("/api/v1/persons", headers=h).status_code == 403
    r = client.post(
        "/api/v1/persons",
        json={"nik": "5555555555555555", "full_name": "X",
              "reason": "uji"},
        headers=h,
    )
    assert r.status_code == 403


def test_grup_dinamis_berdasar_job(client, ctx):
    # u_mgr (job=MGR) anggota g_mgr -> boleh view person.
    h_mgr = login_headers(client, "hashiru", "u_mgr@x.id")
    assert client.get("/api/v1/persons", headers=h_mgr).status_code == 200
    # u_staff (job=STF, lokasi sama) bukan anggota g_mgr -> ditolak.
    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    assert client.get("/api/v1/persons", headers=h_staff).status_code == 403


def test_insert_boleh_correct_ditolak(client, ctx):
    # u_staff: Inserter -> can_insert job_info, tanpa can_correct.
    h = login_headers(client, "hashiru", "u_staff@x.id")
    emp = ctx["e_staff"].id
    r = client.post(
        "/api/v1/job-info",
        json={
            "employment_id": str(emp),
            "valid_from": "2026-02-01",
            "job_id": str(ctx["job_stf"].id),
            "org_unit_id": str(ctx["ou"].id),
            "location_id": str(ctx["loc_b"].id),
            "event": "Mutasi",
            "event_reason": "Uji izin",
            "reason": "Uji insert",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    record_id = r.json()["record"]["id"]

    # Correct ditolak: izin berbeda.
    r = client.patch(
        f"/api/v1/job-info/{record_id}/correct",
        json={"location_id": str(ctx["loc_c"].id), "reason": "Uji correct"},
        headers=h,
    )
    assert r.status_code == 403

    # Riwayat pun tak bisa dibaca tanpa can_view_history.
    r = client.get("/api/v1/job-info/timeline",
                   params={"employment_id": str(emp)}, headers=h)
    assert r.status_code == 403


def test_correct_dengan_izin_penuh(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    emp = ctx["e_staff"].id
    r = client.post(
        "/api/v1/job-info",
        json={
            "employment_id": str(emp),
            "valid_from": "2026-02-01",
            "job_id": str(ctx["job_stf"].id),
            "org_unit_id": str(ctx["ou"].id),
            "location_id": str(ctx["loc_b"].id),
            "event": "Mutasi",
            "event_reason": "Uji izin",
            "reason": "Uji correct",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    record_id = r.json()["record"]["id"]
    r = client.patch(
        f"/api/v1/job-info/{record_id}/correct",
        json={"location_id": str(ctx["loc_c"].id), "reason": "Betulkan lokasi"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["location_id"] == str(ctx["loc_c"].id)


def test_rbac_hanya_untuk_berizin(client, ctx):
    h_none = login_headers(client, "hashiru", "u_none@x.id")
    assert client.get("/api/v1/roles", headers=h_none).status_code == 403
    h_full = login_headers(client, "hashiru", "u_full@x.id")
    r = client.get("/api/v1/roles", headers=h_full)
    assert r.status_code == 200
    assert {x["name"] for x in r.json()} >= {"HR", "Inserter", "MgrRole"}


def test_tenants_khusus_superadmin(client, ctx):
    h_full = login_headers(client, "hashiru", "u_full@x.id")
    assert client.get("/api/v1/tenants", headers=h_full).status_code == 403
    h_admin = login_headers(client, "hashiru", "admin_a@x.id")
    r = client.get("/api/v1/tenants", headers=h_admin)
    assert r.status_code == 200
    assert {t["slug"] for t in r.json()} == {"hashiru", "acme"}
