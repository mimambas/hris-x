"""Uji audit trail: 100% mutasi tercatat (old/new, reason, channel, actor)."""

from __future__ import annotations

from datetime import date

from tests.conftest import login_headers


def test_create_person_mencatat_audit(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    r = client.post(
        "/api/v1/persons",
        json={"nik": "6666666666666666", "full_name": "Audit Me",
              "reason": "Pendaftaran karyawan baru"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    person_id = r.json()["id"]

    logs = client.get("/api/v1/audit-logs",
                      params={"object_type": "person",
                              "object_id": person_id},
                      headers=h).json()
    assert len(logs) == 1
    log = logs[0]
    assert log["action"] == "create"
    assert log["old_values"] is None
    assert log["new_values"]["nik"] == "6666666666666666"
    assert log["new_values"]["full_name"] == "Audit Me"
    assert log["reason"] == "Pendaftaran karyawan baru"
    assert log["channel"] == "api"
    assert log["actor_user_id"]
    assert log["ip"]  # IP pencatat


def test_insert_dan_correct_tercatat_dengan_old_new(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    emp = ctx["e_staff"].id
    payload = {
        "employment_id": str(emp),
        "valid_from": "2026-03-01",
        "job_id": str(ctx["job_stf"].id),
        "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id),
        "event": "Mutasi",
        "event_reason": "Uji audit",
        "reason": "Mutasi awal",
    }
    record_id = client.post("/api/v1/job-info", json=payload,
                            headers=h).json()["record"]["id"]
    client.patch(f"/api/v1/job-info/{record_id}/correct",
                 json={"location_id": str(ctx["loc_c"].id),
                       "reason": "Betulkan lokasi salah input"},
                 headers=h)

    logs = client.get("/api/v1/audit-logs",
                      params={"object_type": "job_info",
                              "object_id": record_id},
                      headers=h).json()
    by_action = {l["action"]: l for l in logs}
    assert set(by_action) == {"insert", "correct"}
    assert by_action["insert"]["reason"] == "Mutasi awal"
    correct = by_action["correct"]
    assert correct["reason"] == "Betulkan lokasi salah input"
    assert correct["old_values"]["location_id"] == str(ctx["loc_b"].id)
    assert correct["new_values"]["location_id"] == str(ctx["loc_c"].id)


def test_filter_audit_per_employment_dan_tanggal(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    emp = ctx["e_staff"].id
    r = client.get("/api/v1/audit-logs",
                   params={"employment_id": str(emp),
                           "date_from": date.today().isoformat(),
                           "date_to": date.today().isoformat()},
                   headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_audit_log_tanpa_endpoint_ubah_hapus(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    logs = client.get("/api/v1/audit-logs", headers=h).json()
    assert logs, "butuh minimal 1 entri (dari login)"
    log_id = logs[0]["id"]
    # Tidak ada endpoint ubah/hapus audit: 404 (tak ada route) atau 405.
    assert client.put(f"/api/v1/audit-logs/{log_id}", json={},
                      headers=h).status_code in (404, 405)
    assert client.delete(f"/api/v1/audit-logs/{log_id}",
                         headers=h).status_code in (404, 405)


def test_login_juga_diaudit(client, ctx):
    h = login_headers(client, "hashiru", "u_full@x.id")
    logs = client.get("/api/v1/audit-logs",
                      params={"object_type": "user"}, headers=h).json()
    assert any(l["action"] == "login" for l in logs)
