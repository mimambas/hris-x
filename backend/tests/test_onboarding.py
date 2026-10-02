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


def test_assignable_users_dan_assign_ke_my_tasks(client, ctx):
    """Penugasan orang: HR memilih dari daftar user tenant; tugas muncul
    di Tugas Saya milik penerima dan dapat diselesaikan olehnya."""
    from app.models import FieldPermission, PermissionRole

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
    task = tasks[0]

    # Samakan grant dengan seed: peran karyawan/manajer boleh correct tugas.
    db = ctx["db"]
    r_ins = db.query(PermissionRole).filter_by(
        tenant_id=ctx["ta"].id, name="Inserter").one()
    for obj in ("onboarding_process", "onboarding_task"):
        db.add(FieldPermission(tenant_id=ctx["ta"].id, role_id=r_ins.id,
                               object_name=obj, field_name="*",
                               can_view=True, can_correct=True))
    db.commit()

    # Daftar pilihan penugasan memuat user aktif tenant ini.
    ru = client.get("/api/v1/onboarding/assignable-users", headers=h)
    assert ru.status_code == 200, ru.text
    staff = next(u for u in ru.json() if u["email"] == "u_staff@x.id")

    # Tugaskan: pending berubah in_progress, penerima tercatat.
    ra = client.post(f"/api/v1/onboarding/tasks/{task['id']}/assign",
                     json={"assignee_user_id": staff["id"]}, headers=h)
    assert ra.status_code == 200, ra.text
    assert ra.json()["assignee_user_id"] == staff["id"]
    assert ra.json()["assignee_name"] == staff["full_name"]
    assert ra.json()["status"] == "in_progress"

    # Muncul di Tugas Saya penerima dan bisa diselesaikan olehnya.
    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    mine = client.get("/api/v1/onboarding/my-tasks", headers=h_staff)
    assert mine.status_code == 200
    assert any(t["id"] == task["id"] for t in mine.json())
    rd = client.patch(f"/api/v1/onboarding/tasks/{task['id']}",
                      json={"status": "done"}, headers=h_staff)
    assert rd.status_code == 200, rd.text
    assert rd.json()["status"] == "done"
