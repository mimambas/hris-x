"""Demo Sprint 8 (PRD 24.2 S8, BEN-001/BEN-003): klaim & pinjaman karyawan.

Budi Santoso (budi@hashiru.id) mengajukan klaim kesehatan Rp1.500.000
(struk terlampir) -> Dewi Lestari (dewi@hashiru.id, atasannya) approve L1
-> admin approve final -> reimbursement tercatat di payroll run 2026-09
(non-pajak). Budi juga mengajukan pinjaman Rp12jt/12 bulan; cicilan Rp1jt
otomatis dipotong dari run yang sama. Run dikunci -> angsuran paid, sisa
pinjaman berkurang.

Jejak audit lengkap ditulis ke demo/demo_claim_loan_trail.json.

Jalankan dari direktori backend:
    ../.venv/bin/python scripts/demo_claim_loan_trail.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

DB_PATH = "/tmp/demo_hrisx_sprint8.db"
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

CLAIM_DATE = "2026-09-15"
PERIOD = "2026-09"


def login(client, email):
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": email,
        "password": seed.ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def rp(n):
    return f"Rp{n:,}".replace(",", ".")


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

    trail = {"alur": []}

    # 1. Budi mengajukan klaim kesehatan Rp1,5jt (struk terlampir).
    types = {t["code"]: t["id"]
             for t in client.get("/api/v1/claims/types",
                                 headers=h_budi).json()}
    r = client.post("/api/v1/claims", headers=h_budi, json={
        "employment_id": budi_emp_id,
        "claim_type_id": types["klaim_kesehatan"],
        "amount": 1_500_000, "claim_date": CLAIM_DATE,
        "description": "Biaya berobat rawat jalan",
        "receipt_document_id": str(uuid.uuid4())})
    assert r.status_code == 201, r.text
    claim = r.json()
    r = client.post(f"/api/v1/claims/{claim['id']}/submit", headers=h_budi)
    assert r.status_code == 200, r.text
    trail["alur"].append({"aktor": "Budi Santoso",
                         "aksi": "ajukan klaim kesehatan",
                         "nominal": rp(1_500_000),
                         "status": r.json()["status"]})
    print(f"1. Budi mengajukan klaim kesehatan {rp(1_500_000)} -> submitted")

    # 2. Dewi (atasan) approve L1.
    r = client.post(f"/api/v1/claims/{claim['id']}/approve-l1",
                    headers=h_dewi, json={"reason": "Struk valid"})
    assert r.status_code == 200, r.text
    trail["alur"].append({"aktor": "Dewi Lestari (atasan)",
                         "aksi": "approve L1",
                         "status": r.json()["status"]})
    print("2. Dewi approve L1 -> approved_l1")

    # 3. Admin approve final.
    r = client.post(f"/api/v1/claims/{claim['id']}/approve", headers=h_admin,
                    json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    trail["alur"].append({"aktor": "Admin HR",
                         "aksi": "approve final",
                         "status": r.json()["status"]})
    print("3. Admin approve final -> approved")

    # 4. Budi mengajukan pinjaman Rp12jt tenor 12 bulan.
    r = client.post("/api/v1/loans", headers=h_budi, json={
        "employment_id": budi_emp_id, "amount": 12_000_000,
        "tenor_months": 12, "purpose": "Biaya pendidikan"})
    assert r.status_code == 201, r.text
    loan = r.json()
    r = client.post(f"/api/v1/loans/{loan['id']}/submit", headers=h_budi)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h_admin,
                    json={"reason": "Sesuai kebijakan 3x gaji"})
    assert r.status_code == 200, r.text
    loan = r.json()
    trail["alur"].append({"aktor": "Budi Santoso",
                         "aksi": "pinjaman disetujui",
                         "nominal": rp(loan["principal_amount"]),
                         "angsuran_per_bulan": rp(loan["monthly_installment"]),
                         "status": loan["status"]})
    print(f"4. Pinjaman {rp(12_000_000)}/12 bln disetujui -> "
          f"angsuran {rp(loan['monthly_installment'])}/bln")

    # 5. Payroll run 2026-09: reimbursement & cicilan otomatis masuk.
    r = client.post("/api/v1/payroll/runs", headers=h_admin,
                    json={"period": PERIOD})
    assert r.status_code == 201, r.text
    run = r.json()
    r = client.get(f"/api/v1/payroll/runs/{run['id']}/lines",
                   headers=h_admin)
    assert r.status_code == 200, r.text
    line = next(l for l in r.json()
                if l["employment_id"] == budi_emp_id)
    trail["payroll_run"] = {
        "periode": PERIOD,
        "gross": line["gross"],
        "reimbursement": line["reimbursement_amount"],
        "cicilan_pinjaman": line["breakdown"].get("cicilan_pinjaman"),
        "pph21": line["pph21"],
        "take_home_pay": line["take_home_pay"],
    }
    print(f"5. Run {PERIOD}: gross {rp(line['gross'])}, "
          f"reimbursement {rp(line['reimbursement_amount'])} (non-pajak), "
          f"cicilan {rp(line['breakdown']['cicilan_pinjaman'])}, "
          f"PPh21 {rp(line['pph21'])}, "
          f"take-home {rp(line['take_home_pay'])}")

    # 6. Kunci run: angsuran menjadi paid, sisa pinjaman berkurang.
    r = client.post(f"/api/v1/payroll/runs/{run['id']}/lock",
                    headers=h_admin)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/loans/{loan['id']}", headers=h_admin)
    loan_after = r.json()
    trail["pinjaman_setelah_lock"] = {
        "sisa": loan_after["remaining_total"],
        "status": loan_after["status"],
    }
    print(f"6. Run dikunci -> angsuran paid, "
          f"sisa pinjaman {rp(loan_after['remaining_total'])}")

    # 7. Klaim ditandai dibayar (reimbursement tercatat via payroll).
    r = client.post(f"/api/v1/claims/{claim['id']}/mark-paid",
                    headers=h_admin,
                    json={"payment_ref": f"PAYROLL-{PERIOD}"})
    assert r.status_code == 200, r.text
    trail["alur"].append({"aktor": "Admin HR", "aksi": "mark-paid",
                         "payment_ref": f"PAYROLL-{PERIOD}",
                         "status": r.json()["status"]})
    print(f"7. Klaim ditandai dibayar via payroll {PERIOD}")

    # 8. Jejak audit klaim & pinjaman.
    audit = []
    for otype, oid in (("claim", claim["id"]), ("loan", loan["id"])):
        r = client.get("/api/v1/audit-logs", headers=h_admin,
                       params={"object_type": otype, "object_id": oid,
                               "limit": 50})
        assert r.status_code == 200, r.text
        for a in r.json():
            audit.append({"objek": otype, "aksi": a["action"],
                          "aktor_user_id": a.get("actor_user_id"),
                          "waktu": str(a.get("created_at")),
                          "alasan": a.get("reason"),
                          "channel": a.get("channel")})
    trail["audit"] = audit

    out_path = (Path(__file__).resolve().parent.parent.parent
                / "demo" / "demo_claim_loan_trail.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trail, indent=2, ensure_ascii=False))
    print(f"\nDemo OK: klaim kesehatan Budi -> reimbursement tercatat "
          f"di payroll {PERIOD}")
    print(f"Jejak audit ({len(audit)} entri) -> {out_path}")


if __name__ == "__main__":
    main()
