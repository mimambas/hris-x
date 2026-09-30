"""Demo Sprint 7 (PRD 24.2 S7): penilaian kinerja & pelatihan.

Siklus "Penilaian Tahunan 2026": goal_setting (5 karyawan buat + submit
goal, bobot 100) → approve HR → mid_year → year_end (self-assessment +
manager score) → calibration (potential + final score) → matriks 9-box →
rekomendasi pelatihan rule-based → enrollment + complete.

Hasil: demo/demo_nine_box.json (matriks per kotak + daftar nama).

Jalankan dari direktori backend:
    ../.venv/bin/python scripts/demo_performance_flow.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DB_PATH = "/tmp/demo_hrisx_sprint7.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Employment, Person, User  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

# (nama, email, self_score, manager_score, potential) — final = manager
# score karena tiap karyawan punya 1 goal berbobot 100.
PEOPLE = [
    ("Dewi Lestari", "dewi@hashiru.id", 5, 5, 5),    # star
    ("Budi Santoso", "budi@hashiru.id", 4, 3, 5),    # high_potential
    ("Sari Wijaya", "sari@hashiru.id", 4, 4, 3),      # high_performer
    ("Andi Pratama", "andi@hashiru.id", 3, 2, 4),     # rough_diamond
    ("Rina Kartika", "rina@hashiru.id", 3, 3, 3),     # key_player
]

GOAL_TITLES = {
    "Dewi Lestari": "Memimpin transformasi digital engineering",
    "Budi Santoso": "Menyelesaikan 12 fitur backend tepat waktu",
    "Sari Wijaya": "Meningkatkan test coverage ke 80%",
    "Andi Pratama": "Menurunkan incident logistik 30%",
    "Rina Kartika": "Akurasi data kontrak 99%",
}


def login(client, email):
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": email,
        "password": seed.ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    seed.main()
    client = TestClient(create_app(os.environ["DATABASE_URL"]))

    # Akun user untuk 3 karyawan yang belum punya (dewi & budi ada di seed).
    db = new_session()
    tenant_id = db.execute(
        select(User.tenant_id).where(User.email == "admin@hashiru.id")
    ).scalar_one()
    for name, email, *_ in PEOPLE:
        if db.execute(select(User).where(User.email == email)
                      ).scalar_one_or_none() is None:
            person = db.execute(
                select(Person).where(Person.full_name == name)).scalar_one()
            db.add(User(tenant_id=tenant_id, email=email,
                        password_hash=hash_password(seed.ADMIN_PASSWORD),
                        full_name=name, person_id=person.id))
    db.commit()
    employments = {}
    for name, *_ in PEOPLE:
        person = db.execute(
            select(Person).where(Person.full_name == name)).scalar_one()
        emp = db.execute(
            select(Employment).where(Employment.person_id == person.id)
        ).scalar_one()
        employments[name] = str(emp.id)
    db.close()

    h_admin = login(client, "admin@hashiru.id")
    logins = {name: login(client, email) for name, email, *_ in PEOPLE}
    trail = {"alur": []}

    # 1. Siklus baru (draft) → goal_setting.
    r = client.post("/api/v1/performance/cycles", headers=h_admin, json={
        "name": "Penilaian Tahunan 2026", "year": 2026,
        "start_date": "2026-01-01", "end_date": "2026-12-31"})
    assert r.status_code == 201, r.text
    cycle = r.json()
    assert cycle["status"] == "draft"
    for to in ("goal_setting",):
        r = client.post(
            f"/api/v1/performance/cycles/{cycle['id']}/transition",
            headers=h_admin, json={"to_status": to})
        assert r.status_code == 200, r.text
    cycle = r.json()
    trail["alur"].append({"aktor": "HR", "aksi": "buat siklus",
                          "nama": cycle["name"], "fase": cycle["status"]})

    # 2. Tiap karyawan buat goal (bobot 100) + submit.
    goals = {}
    for name, _, *_ in PEOPLE:
        h = logins[name]
        r = client.post(
            f"/api/v1/performance/cycles/{cycle['id']}/goals", headers=h,
            json={"employment_id": employments[name],
                  "title": GOAL_TITLES[name],
                  "description": f"Target kinerja {name} tahun 2026.",
                  "weight": 100,
                  "target_text": "Tercapai 100% akhir tahun"})
        assert r.status_code == 201, r.text
        goal = r.json()
        r = client.post(f"/api/v1/performance/goals/{goal['id']}/submit",
                        headers=h)
        assert r.status_code == 200, r.text
        goals[name] = r.json()["id"]
    trail["alur"].append({"aktor": "5 karyawan",
                          "aksi": "buat + submit goal (bobot 100)",
                          "jumlah": len(goals)})

    # 3. HR approve semua goal (total bobot approved = 100 → lolos).
    for name, *_ in PEOPLE:
        r = client.post(f"/api/v1/performance/goals/{goals[name]}/approve",
                        headers=h_admin, json={"note": "Disetujui"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
    trail["alur"].append({"aktor": "HR", "aksi": "approve 5 goal"})

    # 4. Fase → mid_year → year_end; tiap karyawan buat appraisal +
    #    self-assessment.
    for to in ("mid_year", "year_end"):
        r = client.post(
            f"/api/v1/performance/cycles/{cycle['id']}/transition",
            headers=h_admin, json={"to_status": to})
        assert r.status_code == 200, r.text
    appraisals = {}
    for name, _, self_score, *_ in PEOPLE:
        h = logins[name]
        r = client.post("/api/v1/performance/appraisals", headers=h, json={
            "employment_id": employments[name], "cycle_id": cycle["id"]})
        assert r.status_code == 201, r.text
        appr = r.json()
        r = client.post(
            f"/api/v1/performance/appraisals/{appr['id']}/self-assessment",
            headers=h, json={"scores": [
                {"goal_id": goals[name], "score": self_score,
                 "comment": "Penilaian diri sendiri"}]})
        assert r.status_code == 200, r.text
        appraisals[name] = appr["id"]
    trail["alur"].append({"aktor": "5 karyawan",
                          "aksi": "self-assessment di fase year_end"})

    # 5. Manager score: Dewi menilai timnya (Budi & Sari), HR menilai
    #    sisanya.
    h_dewi = logins["Dewi Lestari"]
    for name, _, _, mgr_score, _ in PEOPLE:
        h = h_dewi if name in ("Budi Santoso", "Sari Wijaya") else h_admin
        r = client.post(
            f"/api/v1/performance/appraisals/{appraisals[name]}/manager-score",
            headers=h, json={"scores": [
                {"goal_id": goals[name], "score": mgr_score}]})
        assert r.status_code == 200, (name, r.text)
    trail["alur"].append({"aktor": "Dewi (manajer) + HR",
                          "aksi": "manager score 5 appraisal"})

    # 6. Fase → calibration; HR isi potential → final_score terhitung.
    r = client.post(
        f"/api/v1/performance/cycles/{cycle['id']}/transition",
        headers=h_admin, json={"to_status": "calibration"})
    assert r.status_code == 200, r.text
    for name, _, _, _, pot in PEOPLE:
        r = client.post(
            f"/api/v1/performance/appraisals/{appraisals[name]}/calibrate",
            headers=h_admin, json={"potential_score": pot})
        assert r.status_code == 200, r.text
        assert r.json()["final_score"] is not None
    trail["alur"].append({"aktor": "HR",
                          "aksi": "kalibrasi potensial 5 appraisal"})

    # 7. Matriks 9-box → demo_nine_box.json.
    r = client.get(f"/api/v1/performance/cycles/{cycle['id']}/nine-box",
                   headers=h_admin)
    assert r.status_code == 200, r.text
    matrix = r.json()
    nine_box = {"siklus": matrix["cycle_name"], "kotak": {}}
    for box_key, entries in matrix["boxes"].items():
        if not entries:
            continue
        e0 = entries[0]
        nine_box["kotak"][box_key] = {
            "label_id": e0["label_id"], "label_en": e0["label_en"],
            "anggota": [{"nama": e["person_name"],
                         "skor_kinerja": e["final_score"],
                         "skor_potensi": e["potential_score"]}
                        for e in entries]}
    out_path = (Path(__file__).resolve().parent.parent.parent / "demo"
                / "demo_nine_box.json")
    out_path.write_text(json.dumps(nine_box, indent=2, ensure_ascii=False))
    print("Matriks 9-box:")
    for box_key, box in nine_box["kotak"].items():
        names = ", ".join(m["nama"] for m in box["anggota"])
        print(f"  {box['label_id']} ({box_key}): {names}")

    # 8. Rekomendasi pelatihan (rule-based) untuk Budi (high_potential):
    #    buat kursus → enroll → complete.
    for code, name in (("LD-01", "Leadership Development"),
                       ("MT-01", "Mentoring"),
                       ("KD-01", "Kepemimpinan Dasar"),
                       ("KE-01", "Komunikasi Efektif")):
        r = client.post("/api/v1/performance/courses", headers=h_admin,
                        json={"code": code, "name": name,
                              "provider": "Hashiru Academy",
                              "duration_hours": 16, "cost": 2500000})
        assert r.status_code == 201, r.text
    r = client.get(
        f"/api/v1/performance/cycles/{cycle['id']}/training-recommendations",
        headers=h_admin, params={"employment_id": employments["Budi Santoso"]})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["box_key"] == "high_potential", rec
    print(f"Rekomendasi untuk Budi Santoso ({rec['label_id']}): "
          f"{rec['recommended_categories']}")
    ld = next(c for c in rec["courses"] if c["code"] == "LD-01")
    r = client.post("/api/v1/performance/enrollments", headers=h_admin, json={
        "employment_id": employments["Budi Santoso"], "course_id": ld["id"],
        "cycle_id": cycle["id"]})
    assert r.status_code == 201, r.text
    enr = r.json()
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete",
        headers=h_admin, json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    trail["alur"].append(
        {"aktor": "HR", "aksi": "enroll + complete pelatihan",
         "karyawan": "Budi Santoso", "kursus": "Leadership Development",
         "rekomendasi": rec["recommended_categories"]})

    # 9. Jejak audit siklus.
    r = client.get("/api/v1/audit-logs", headers=h_admin, params={
        "object_type": "review_cycle", "object_id": cycle["id"], "limit": 50})
    assert r.status_code == 200, r.text
    trail["audit_transisi_siklus"] = [
        {"aksi": a["action"],
         "dari": (a.get("old_values") or {}).get("status"),
         "ke": (a.get("new_values") or {}).get("status"),
         "waktu": str(a.get("created_at"))}
        for a in r.json()]
    print(f"Demo OK: 9-box terisi {len(nine_box['kotak'])} kotak -> {out_path}")
    print(f"Transisi siklus tercatat: {len(trail['audit_transisi_siklus'])} entri")


if __name__ == "__main__":
    main()
