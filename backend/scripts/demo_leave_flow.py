"""Demo Sprint 5 (PRD 24.2 S5): alur cuti multi-level end-to-end.

Budi Santoso (budi@hashiru.id) mengajukan cuti tahunan lewat API dengan
?source=mobile (simulasi aplikasi HP) → Dewi Lestari (dewi@hashiru.id,
atasannya) menyetujui L1 → admin menyetujui L2 (final, saldo terpotong).

Jejak audit lengkap ditulis ke demo/demo_leave_trail.json.

Jalankan dari direktori backend:
    ../.venv/bin/python scripts/demo_leave_flow.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DB_PATH = "/tmp/demo_hrisx_sprint5.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Employment, Person  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

START, END = "2026-11-09", "2026-11-11"  # Senin–Rabu → 3 hari kerja


def login(client, email):
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": email,
        "password": seed.ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    seed.main()
    client = TestClient(create_app(os.environ["DATABASE_URL"]))

    db = new_session()
    budi_emp = db.execute(
        select(Employment).join(Person,
                                Employment.person_id == Person.id)
        .where(Person.full_name == "Budi Santoso")).scalar_one()
    budi_emp_id = str(budi_emp.id)
    db.close()

    h_budi = login(client, "budi@hashiru.id")
    h_dewi = login(client, "dewi@hashiru.id")
    h_admin = login(client, "admin@hashiru.id")

    types = {t["code"]: t["id"]
             for t in client.get("/api/v1/leave/types",
                                 headers=h_budi).json()}
    bal_before = {b["leave_type_code"]: b["remaining"]
                  for b in client.get(
                      "/api/v1/leave/balances", headers=h_admin,
                      params={"employment_id": budi_emp_id,
                              "year": 2026}).json()}

    trail = {"alur": [], "saldo_sebelum": bal_before}

    # 1. Budi mengajukan cuti via aplikasi HP (source=mobile).
    r = client.post("/api/v1/leave/requests?source=mobile", headers=h_budi,
                    json={"employment_id": budi_emp_id,
                          "leave_type_id": types["cuti_tahunan"],
                          "start_date": START, "end_date": END,
                          "reason": "Liburan keluarga"})
    assert r.status_code == 201, r.text
    req = r.json()
    trail["alur"].append({"aktor": "Budi Santoso (HP)",
                          "aksi": "buat pengajuan", "status": req["status"],
                          "hari": req["days"]})

    r = client.post(f"/api/v1/leave/requests/{req['id']}/submit",
                    headers=h_budi)
    assert r.status_code == 200, r.text
    trail["alur"].append({"aktor": "Budi Santoso (HP)", "aksi": "submit",
                          "status": r.json()["status"]})

    # 2. Dewi (atasan langsung) approve L1.
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l1",
                    headers=h_dewi, json={"reason": "Disetujui"})
    assert r.status_code == 200, r.text
    trail["alur"].append({"aktor": "Dewi Lestari (atasan langsung)",
                          "aksi": "approve L1",
                          "status": r.json()["status"]})

    # 3. Admin (HR) approve final L2 → saldo terpotong.
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l2",
                    headers=h_admin, json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    req = r.json()
    trail["alur"].append({"aktor": "Administrator (HR)", "aksi": "approve L2",
                          "status": req["status"]})

    bal_after = {b["leave_type_code"]: b["remaining"]
                 for b in client.get(
                     "/api/v1/leave/balances", headers=h_admin,
                     params={"employment_id": budi_emp_id,
                             "year": 2026}).json()}
    trail["saldo_sesudah"] = bal_after
    trail["selisih_cuti_tahunan"] = (bal_before["cuti_tahunan"]
                                     - bal_after["cuti_tahunan"])

    # 4. Jejak audit lengkap pengajuan ini.
    r = client.get("/api/v1/audit-logs", headers=h_admin, params={
        "object_type": "leave_request", "object_id": req["id"], "limit": 50})
    assert r.status_code == 200, r.text
    trail["audit"] = [
        {"aksi": a["action"], "aktor_user_id": a.get("actor_user_id"),
         "waktu": str(a.get("created_at")), "alasan": a.get("reason"),
         "channel": a.get("channel")}
        for a in r.json()
    ]

    out_path = (Path(__file__).resolve().parent.parent.parent
                / "demo" / "demo_leave_trail.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trail, indent=2, ensure_ascii=False))
    print(f"Demo OK: cuti {START}–{END} ({req['days']} hari) "
          f"status={req['status']}")
    print(f"Saldo cuti tahunan Budi: {bal_before['cuti_tahunan']} → "
          f"{bal_after['cuti_tahunan']}")
    print(f"Jejak audit ({len(trail['audit'])} entri) → {out_path}")


if __name__ == "__main__":
    main()
