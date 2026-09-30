"""Demo Sprint 9 (PRD 24.2 S9, ANL-001/ANL-003).

Demo goal PRD: "Direktur melihat headcount dan turnover real-time."

Alur: seed data demo -> buat 1 karyawan baru (Joko Prasetyo, PKWT) ->
terminasi di bulan berjalan -> tarik headcount & turnover real-time
sebagai admin (Direktur) -> tulis demo/demo_dashboard.json.

Jalankan dari direktori backend:
    ../.venv/bin/python scripts/demo_dashboard.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

DB_PATH = "/tmp/demo_hrisx_sprint9.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def login(client, email):
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": email,
        "password": seed.ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    seed.main()
    client = TestClient(create_app(os.environ["DATABASE_URL"]))
    h = login(client, "admin@hashiru.id")

    # --- Karyawan baru: Joko Prasetyo (PKWT, Tim Backend) ---
    p = client.post("/api/v1/persons", headers=h, json={
        "nik": "3174010606960006", "full_name": "Joko Prasetyo",
        "gender": "L", "birth_date": "1996-06-06",
        "reason": "demo sprint 9"}).json()
    assert "id" in p, p
    le = client.get("/api/v1/org/legal-entities", headers=h).json()[0]["id"]
    e = client.post("/api/v1/employments", headers=h, json={
        "person_id": p["id"], "legal_entity_id": le,
        "start_date": "2024-01-01", "status": "active",
        "reason": "demo sprint 9"}).json()
    ou = next(u for u in client.get("/api/v1/org/units", headers=h).json()
              if u["name"] == "Tim Backend")
    loc = client.get("/api/v1/org/locations", headers=h).json()[0]["id"]
    job = next(j for j in client.get("/api/v1/org/jobs", headers=h).json()
               if j["code"] == "STF")
    r = client.post("/api/v1/job-info", headers=h, json={
        "employment_id": e["id"], "valid_from": "2024-01-01",
        "job_id": job["id"], "org_unit_id": ou["id"], "location_id": loc,
        "event": "hire", "event_reason": "Rekrutmen reguler",
        "reason": "demo sprint 9"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/contracts", headers=h, json={
        "employment_id": e["id"], "contract_type": "PKWT",
        "contract_number": "PKWT/2024/009", "start_date": "2024-01-01",
        "end_date": TODAY.isoformat(), "event": "hire",
        "event_reason": "Rekrutmen reguler", "reason": "demo sprint 9"})
    assert r.status_code == 201, r.text
    # --- Terminasi di bulan berjalan (kontrak berakhir) ---
    r = client.post("/api/v1/job-info", headers=h, json={
        "employment_id": e["id"], "valid_from": TODAY.isoformat(),
        "job_id": job["id"], "org_unit_id": ou["id"], "location_id": loc,
        "event": "termination", "event_reason": "Kontrak berakhir",
        "reason": "demo sprint 9"})
    assert r.status_code == 201, r.text

    # --- Direktur melihat dasbor real-time ---
    hc = client.get("/api/v1/dashboard/headcount",
                    params={"as_of": TODAY.isoformat()}, headers=h).json()
    to = client.get("/api/v1/dashboard/turnover",
                    params={"period": PERIOD}, headers=h).json()
    dg = client.get("/api/v1/dashboard/demographics",
                    params={"as_of": TODAY.isoformat()}, headers=h).json()
    assert hc["total"] > 0 and to["terminated"] == 1

    top_unit = max(hc["by_org_unit"].items(), key=lambda kv: kv[1])
    result = {
        "generated_at": TODAY.isoformat(),
        "period": PERIOD,
        "as_of": TODAY.isoformat(),
        "headcount_total": hc["total"],
        "headcount": hc,
        "turnover_bulan_berjalan": {
            "period": to["period"],
            "terminated": to["terminated"],
            "rate_pct": to["rate_pct"],
            "by_org_unit": to["by_org_unit"],
        },
        "top_unit": {"name": top_unit[0], "headcount": top_unit[1]},
        "demografi_ringkas": {
            "by_gender": dg["by_gender"],
            "by_age": dg["by_age"],
        },
    }
    out = Path(__file__).resolve().parent.parent.parent / "demo" / \
        "demo_dashboard.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Ditulis: {out}")
    print(f"Headcount {TODAY}: {hc['total']} | "
          f"Turnover {PERIOD}: {to['rate_pct']}% "
          f"({to['terminated']} keluar) | "
          f"Top unit: {top_unit[0]} ({top_unit[1]})")


if __name__ == "__main__":
    main()
