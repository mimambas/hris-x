"""Test modul Onboarding & Offboarding (ONB, PRD 12.2 F2).

- Template milik HR + butir tugas per tim dengan offset tenggat.
- Proses per karyawan: tugas dibuat otomatis (due = start + offset).
- Tugas terlambat terflag is_overdue (eskalasi visual ONB-002).
- Syarat dokumen per tugas diekspos (ONB-001).
- Otorisasi: template hanya HR; proses/tugas ikut scope populasi.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import login_headers


def _admin(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def _buat_template(client, h, kind="onboarding"):
    r = client.post(
        "/api/v1/onboarding/templates",
        json={"name": "Orientasi Karyawan Baru", "kind": kind},
        headers=h,
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    for i, (title, team, offset, doc) in enumerate([
        ("Siapkan laptop & akun", "it", -3, None),
        ("Verifikasi KTP & ijazah", "hr", 0, "ktp"),
        ("Jadwalkan 1-on-1 dengan atasan", "manager", 1, None),
    ]):
        rt = client.post(
            f"/api/v1/onboarding/templates/{tid}/tasks",
            json={"title": title, "team": team, "due_offset_days": offset,
                  "sort_order": i, "required_doc_type": doc},
            headers=h,
        )
        assert rt.status_code == 201, rt.text
    return tid


def test_template_crud_hr(client, ctx):
    h = _admin(client)
    tid = _buat_template(client, h)
    r = client.get(f"/api/v1/onboarding/templates/{tid}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["template"]["task_count"] == 3
    assert len(body["tasks"]) == 3
    teams = {t["team"] for t in body["tasks"]}
    assert teams == {"it", "hr", "manager"}


def test_template_non_hr_ditolak(client, ctx):
    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.post(
        "/api/v1/onboarding/templates",
        json={"name": "X", "kind": "onboarding"},
        headers=h_staff,
    )
    assert r.status_code == 403


def test_start_process_buat_tugas_dengan_tenggat(client, ctx):
    h = _admin(client)
    tid = _buat_template(client, h)
    db = ctx["db"]
    person_id = ctx["e_staff"].person_id
    start = date.today() + timedelta(days=7)
    r = client.post(
        "/api/v1/onboarding/processes",
        json={
            "person_id": str(person_id),
            "employment_id": str(ctx["e_staff"].id),
            "template_id": tid,
            "start_date": start.isoformat(),
            "notes": "Uji",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    proc = r.json()
    assert proc["total_tasks"] == 3
    assert proc["done_tasks"] == 0

    d = client.get(f"/api/v1/onboarding/processes/{proc['id']}", headers=h)
    assert d.status_code == 200
    tasks = d.json()["tasks"]
    by_title = {t["title"]: t for t in tasks}
    # due_date = start_date + offset.
    assert by_title["Siapkan laptop & akun"]["due_date"] == (
        start + timedelta(days=-3)).isoformat()
    # Syarat dokumen diekspos (ONB-001).
    verif = by_title["Verifikasi KTP & ijazah"]
    assert verif["required_doc_type"] == "ktp"
    assert verif["doc_ready"] is False


def test_update_task_dan_complete_process(client, ctx):
    h = _admin(client)
    tid = _buat_template(client, h)
    person_id = ctx["e_staff"].person_id
    r = client.post(
        "/api/v1/onboarding/processes",
        json={"person_id": str(person_id), "template_id": tid,
              "start_date": date.today().isoformat()},
        headers=h,
    )
    pid = r.json()["id"]
    tasks = client.get(f"/api/v1/onboarding/processes/{pid}",
                       headers=h).json()["tasks"]

    # Complete ditolak bila masih ada tugas terbuka.
    rc = client.post(f"/api/v1/onboarding/processes/{pid}/complete",
                     headers=h)
    assert rc.status_code == 422

    for t in tasks:
        ru = client.patch(
            f"/api/v1/onboarding/tasks/{t['id']}",
            json={"status": "done"},
            headers=h,
        )
        assert ru.status_code == 200, ru.text
    rc = client.post(f"/api/v1/onboarding/processes/{pid}/complete",
                     headers=h)
    assert rc.status_code == 200, rc.text
    assert rc.json()["status"] == "completed"
    assert rc.json()["done_tasks"] == 3


def test_tugas_terlambat_terflag_overdue(client, ctx):
    h = _admin(client)
    tid = _buat_template(client, h)
    person_id = ctx["e_staff"].person_id
    # Mulai 10 hari lalu: tugas offset -3/+1 sudah lewat tenggat.
    r = client.post(
        "/api/v1/onboarding/processes",
        json={"person_id": str(person_id), "template_id": tid,
              "start_date": (date.today() - timedelta(days=10)).isoformat()},
        headers=h,
    )
    pid = r.json()["id"]
    d = client.get(f"/api/v1/onboarding/processes/{pid}", headers=h)
    assert d.json()["process"]["overdue_tasks"] >= 1
    assert any(t["is_overdue"] for t in d.json()["tasks"])


def test_isolasi_tenant(client, ctx):
    h_a = _admin(client)
    tid = _buat_template(client, h_a)
    person_id = ctx["e_staff"].person_id
    r = client.post(
        "/api/v1/onboarding/processes",
        json={"person_id": str(person_id), "template_id": tid,
              "start_date": date.today().isoformat()},
        headers=h_a,
    )
    pid = r.json()["id"]
    # Admin tenant B tidak boleh melihat proses tenant A.
    h_b = login_headers(client, "acme", "admin_b@x.id")
    assert client.get(f"/api/v1/onboarding/processes/{pid}",
                      headers=h_b).status_code == 404
    assert client.get("/api/v1/onboarding/processes",
                      headers=h_b).json() == []


def test_offboarding_template_dan_cancel(client, ctx):
    h = _admin(client)
    tid = _buat_template(client, h, kind="offboarding")
    person_id = ctx["e_staff"].person_id
    r = client.post(
        "/api/v1/onboarding/processes",
        json={"person_id": str(person_id), "template_id": tid,
              "start_date": date.today().isoformat()},
        headers=h,
    )
    assert r.json()["kind"] == "offboarding"
    pid = r.json()["id"]
    rc = client.post(f"/api/v1/onboarding/processes/{pid}/cancel", headers=h)
    assert rc.status_code == 200
    assert rc.json()["status"] == "cancelled"
    # Tugas proses yang dibatalkan tidak bisa diubah.
    tasks = client.get(f"/api/v1/onboarding/processes/{pid}",
                       headers=h).json()["tasks"]
    ru = client.patch(f"/api/v1/onboarding/tasks/{tasks[0]['id']}",
                      json={"status": "done"}, headers=h)
    assert ru.status_code == 422
