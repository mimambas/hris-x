"""Uji isolasi tenant: data tenant B tak terlihat dari tenant A."""

from __future__ import annotations

from tests.conftest import login_headers


def test_list_hanya_data_tenant_sendiri(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    r = client.get("/api/v1/persons", headers=h)
    assert r.status_code == 200
    niks = {p["nik"] for p in r.json()}
    assert "9999999999999999" not in niks  # milik tenant acme
    assert "1111111111111111" in niks


def test_baca_person_tenant_lain_404(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    r = client.get(f"/api/v1/persons/{ctx['p_b'].id}", headers=h)
    assert r.status_code == 404


def test_tulis_ke_employment_tenant_lain_404(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    r = client.post(
        "/api/v1/job-info",
        json={
            "employment_id": str(ctx["e_b"].id),
            "valid_from": "2026-02-01",
            "job_id": str(ctx["job_stf"].id),
            "org_unit_id": str(ctx["ou"].id),
            "location_id": str(ctx["loc_b"].id),
            "event": "Mutasi",
            "event_reason": "Uji isolasi",
            "reason": "Uji isolasi",
        },
        headers=h,
    )
    assert r.status_code == 404


def test_admin_tenant_b_tak_bisa_akses_tenant_a(client, ctx):
    h = login_headers(client, "acme", "admin_b@x.id")
    # admin_b superadmin di tenantnya, tapi person tenant A tetap 404.
    from sqlalchemy import select
    from app.models import Person
    db = ctx["db"]
    p_a = db.execute(
        select(Person).where(Person.nik == "1111111111111111")
    ).scalars().first()
    r = client.get(f"/api/v1/persons/{p_a.id}", headers=h)
    assert r.status_code == 404
