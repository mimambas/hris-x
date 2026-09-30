"""Skenario penerimaan PRD 9.3 (level API): promosi bertanggal masa depan.

Given karyawan A Staff sejak 2026-01-05.
When HR menyimpan promosi ke Supervisor berlaku H+30 dengan event "Promosi".
Then profil A per H+29 masih Staff, per H+30 menjadi Supervisor,
      dan audit mencatat pembuat, waktu, nilai lama & baru.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import login_headers


def _job_payload(ctx, emp_id, valid_from, job_id, event="Promosi",
                 reason="Kenaikan jabatan reguler"):
    return {
        "employment_id": str(emp_id),
        "valid_from": valid_from.isoformat(),
        "job_id": str(job_id),
        "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id),
        "event": event,
        "event_reason": reason,
        "reason": "Uji skenario PRD 9.3",
    }


def _comp_payload(ctx, emp_id, valid_from, gaji_pokok, event="Promosi"):
    return {
        "employment_id": str(emp_id),
        "valid_from": valid_from.isoformat(),
        "pay_group": "Bulanan",
        "components": {"gaji_pokok": gaji_pokok, "tunjangan_tetap": 1000000},
        "event": event,
        "event_reason": "Penyesuaian gaji promosi",
        "reason": "Uji skenario PRD 9.3",
    }


def _get_as_of(client, headers, path, emp_id, d):
    r = client.get(f"/api/v1/{path}",
                   params={"employment_id": str(emp_id), "as_of": d.isoformat()},
                   headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_prd93_promosi_masa_depan(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    emp = ctx["e_staff"].id
    hire = date(2026, 1, 5)
    promo = date.today() + timedelta(days=30)

    # Given: Staff sejak hire.
    r = client.post("/api/v1/job-info",
                    json=_job_payload(ctx, emp, hire, ctx["job_stf"].id,
                                      event="Hire", reason="Rekrutmen"),
                    headers=h)
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/comp-info",
                    json=_comp_payload(ctx, emp, hire, 8000000, event="Hire"),
                    headers=h)
    assert r.status_code == 201, r.text

    # When: promosi berlaku masa depan.
    r = client.post("/api/v1/job-info",
                    json=_job_payload(ctx, emp, promo, ctx["job_mgr"].id),
                    headers=h)
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/comp-info",
                    json=_comp_payload(ctx, emp, promo, 11000000),
                    headers=h)
    assert r.status_code == 201, r.text

    # Then: sebelum tanggal efektif masih Staff & gaji lama...
    job_kmrn = _get_as_of(client, h, "job-info", emp, promo - timedelta(days=1))
    assert job_kmrn["job_id"] == str(ctx["job_stf"].id)
    comp_kmrn = _get_as_of(client, h, "comp-info", emp, promo - timedelta(days=1))
    assert comp_kmrn["components"]["gaji_pokok"] == 8000000

    # ...tepat pada tanggal efektif menjadi Supervisor & gaji baru.
    job_nanti = _get_as_of(client, h, "job-info", emp, promo)
    assert job_nanti["job_id"] == str(ctx["job_mgr"].id)
    assert job_nanti["event"] == "Promosi"
    comp_nanti = _get_as_of(client, h, "comp-info", emp, promo)
    assert comp_nanti["components"]["gaji_pokok"] == 11000000

    # Timeline memuat riwayat lengkap dengan event reason & pembuat.
    tl = client.get("/api/v1/job-info/timeline",
                    params={"employment_id": str(emp)}, headers=h)
    assert tl.status_code == 200
    events = [x["event"] for x in tl.json()]
    assert events[-2:] == ["Hire", "Promosi"]  # dua terakhir: hire uji + promosi
    assert tl.json()[-1]["event_reason"] == "Kenaikan jabatan reguler"

    # Audit mencatat promosi dengan nilai lama & baru.
    logs = client.get("/api/v1/audit-logs",
                      params={"employment_id": str(emp)}, headers=h)
    assert logs.status_code == 200
    inserts = [l for l in logs.json()
               if l["action"] == "insert" and l["object_type"] == "job_info"]
    assert len(inserts) == 2
    promo_log = next(l for l in inserts if l["new_values"]["event"] == "Promosi")
    assert promo_log["reason"] == "Uji skenario PRD 9.3"
    assert promo_log["actor_user_id"]
    assert promo_log["channel"] == "api"


def test_event_reason_wajib_di_api(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    payload = _job_payload(ctx, ctx["e_staff"].id, date(2026, 1, 5),
                           ctx["job_stf"].id, event="", reason="")
    payload["event_reason"] = ""
    r = client.post("/api/v1/job-info", json=payload, headers=h)
    assert r.status_code == 422  # min_length=1 pada skema


def test_comp_info_menolak_nominal_non_integer(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    payload = _comp_payload(ctx, ctx["e_staff"].id, date(2026, 1, 5), 8000000.5)
    r = client.post("/api/v1/comp-info", json=payload, headers=h)
    assert r.status_code == 422
