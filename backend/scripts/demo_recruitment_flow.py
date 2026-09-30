"""Demo Sprint 6 (PRD 24.2 S6): alur rekrutmen end-to-end.

Requisition (Departemen Engineering) → approve HR → publish lowongan →
kandidat "Ayu Lestari" melamar + upload CV → screening → wawancara +
feedback (skor 4) → offer (PDF) → kandidat accept via tautan publik →
Person + Employment + JobInfo (event 'hire') tercipta.

Jejak audit lengkap ditulis ke demo/demo_recruitment_trail.json.

Jalankan dari direktori backend:
    ../.venv/bin/python scripts/demo_recruitment_flow.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DB_PATH = "/tmp/demo_hrisx_sprint6.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed  # noqa: E402
from app.core.db import new_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    Employment,
    Job,
    JobInfo,
    LegalEntity,
    LegalEntityInfo,
    Location,
    LocationInfo,
    OrgUnit,
    OrgUnitInfo,
    User,
)
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402


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
    unit_id = str(db.execute(
        select(OrgUnit.id).join(OrgUnitInfo,
                                OrgUnitInfo.org_unit_id == OrgUnit.id)
        .where(OrgUnitInfo.name == "Departemen Engineering")
    ).scalar_one())
    job_id = str(db.execute(
        select(Job.id).where(Job.code == "STF")).scalar_one())
    loc_id = str(db.execute(
        select(Location.id).join(LocationInfo,
                                  LocationInfo.location_id == Location.id)
        .where(LocationInfo.name == "Kantor Pusat Jakarta")
    ).scalar_one())
    le_id = str(db.execute(
        select(LegalEntity.id).join(LegalEntityInfo,
                                    LegalEntityInfo.legal_entity_id
                                    == LegalEntity.id)
        .where(LegalEntityInfo.name == "PT Hashiru Teknologi")
    ).scalar_one())
    dewi_id = str(db.execute(
        select(User.id).where(User.email == "dewi@hashiru.id")).scalar_one())
    db.close()

    h_admin = login(client, "admin@hashiru.id")
    trail = {"alur": []}

    # 1. Requisition → submit → approve (HR).
    r = client.post("/api/v1/recruitment/requisitions", headers=h_admin,
                    json={"org_unit_id": unit_id, "job_title": "UI/UX Designer",
                          "headcount": 2,
                          "reason": "Butuh 2 desainer untuk proyek baru"})
    assert r.status_code == 201, r.text
    req = r.json()
    trail["alur"].append({"aktor": "Administrator (HR)", "aksi": "buat requisition",
                          "jabatan": req["job_title"], "status": req["status"]})
    r = client.post(f"/api/v1/recruitment/requisitions/{req['id']}/submit",
                    headers=h_admin)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/recruitment/requisitions/{req['id']}/approve",
                    headers=h_admin, json={"note": "Disetujui, urgent"})
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] == "approved"
    trail["alur"].append({"aktor": "Administrator (HR)", "aksi": "approve requisition",
                          "status": req["status"]})

    # 2. Buat + publish lowongan.
    r = client.post("/api/v1/recruitment/postings", headers=h_admin,
                    json={"requisition_id": req["id"],
                          "title": "UI/UX Designer",
                          "description": "Merancang antarmuka web & mobile.",
                          "requirements": "2+ tahun pengalaman Figma.",
                          "employment_type": "tetap",
                          "location": "Jakarta"})
    assert r.status_code == 201, r.text
    posting = r.json()
    r = client.post(f"/api/v1/recruitment/postings/{posting['id']}/publish",
                    headers=h_admin)
    assert r.status_code == 200, r.text
    posting = r.json()
    trail["alur"].append({"aktor": "Administrator (HR)", "aksi": "publish lowongan",
                          "judul": posting["title"], "status": posting["status"]})

    # 3. Lowongan terlihat publik (tanpa auth, hanya field publik).
    r = client.get("/api/v1/public/jobs", params={"tenant": "hashiru"})
    assert r.status_code == 200, r.text
    jobs = r.json()
    assert any(j["id"] == posting["id"] for j in jobs), jobs
    pub = [j for j in jobs if j["id"] == posting["id"]][0]
    assert set(pub) == {"id", "title", "description", "requirements",
                        "employment_type", "location", "published_at"}, set(pub)
    trail["alur"].append({"aktor": "Publik (tanpa login)",
                          "aksi": "lihat daftar lowongan",
                          "jumlah_published": len(jobs)})

    # 4. Kandidat Ayu Lestari dibuat + CV diunggah.
    r = client.post("/api/v1/recruitment/candidates", headers=h_admin,
                    json={"name": "Ayu Lestari",
                          "email": "ayu.lestari@example.com",
                          "phone": "081234567890", "source": "website"})
    assert r.status_code == 201, r.text
    cand = r.json()
    cv_path = Path("/tmp/cv_ayu_lestari.pdf")
    cv_path.write_bytes(b"%PDF-1.4\n%CV dummy Ayu Lestari\n%%EOF\n")
    with cv_path.open("rb") as fh:
        r = client.post(f"/api/v1/recruitment/candidates/{cand['id']}/cv",
                        headers=h_admin,
                        files={"file": ("cv_ayu_lestari.pdf", fh,
                                        "application/pdf")})
    assert r.status_code == 200, r.text
    cand = r.json()
    assert cand["cv_file_path"], cand
    trail["alur"].append({"aktor": "Ayu Lestari (kandidat)", "aksi": "kirim CV",
                          "cv_tersimpan": bool(cand["cv_file_path"])})

    # 5. Lamaran → screening → interview.
    r = client.post("/api/v1/recruitment/applications", headers=h_admin,
                    json={"posting_id": posting["id"],
                          "candidate_id": cand["id"]})
    assert r.status_code == 201, r.text
    app = r.json()
    for to_stage, note in (("screening", "CV cocok"),
                           ("interview", "Lanjut wawancara")):
        r = client.post(f"/api/v1/recruitment/applications/{app['id']}/move",
                        headers=h_admin,
                        json={"to_stage": to_stage, "note": note})
        assert r.status_code == 200, r.text
        app = r.json()
    trail["alur"].append({"aktor": "Administrator (HR)",
                          "aksi": "pipeline applied→screening→interview",
                          "status": app["status"]})

    # 6. Wawancara + feedback skor 4 (Dewi sebagai interviewer).
    r = client.post("/api/v1/recruitment/interviews", headers=h_admin,
                    json={"application_id": app["id"],
                          "scheduled_at": "2026-10-05T10:00:00+07:00",
                          "interviewer_ids": [dewi_id],
                          "location": "Kantor Pusat Jakarta",
                          "mode": "onsite"})
    assert r.status_code == 201, r.text
    iv = r.json()
    r = client.post(f"/api/v1/recruitment/interviews/{iv['id']}/complete",
                    headers=h_admin)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/recruitment/interviews/{iv['id']}/feedback",
                    headers=h_admin,
                    json={"interviewer_id": dewi_id, "score": 4,
                          "notes": "Portofolio kuat, komunikasi baik",
                          "recommendation": "hire"})
    assert r.status_code == 201, r.text
    fb = r.json()
    assert fb["score"] == 4 and fb["recommendation"] == "hire"
    trail["alur"].append({"aktor": "Dewi Lestari (interviewer)",
                          "aksi": "feedback wawancara",
                          "skor": fb["score"],
                          "rekomendasi": fb["recommendation"]})

    # 7. Offering → buat offer → kirim (token) → PDF.
    r = client.post(f"/api/v1/recruitment/applications/{app['id']}/move",
                    headers=h_admin,
                    json={"to_stage": "offering", "note": "Siap offering"})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/recruitment/offers", headers=h_admin,
                    json={"application_id": app["id"], "salary": 9000000,
                          "start_date": "2026-11-01",
                          "contract_type": "PKWTT",
                          "expires_at": "2026-10-15T17:00:00+07:00",
                          "job_id": job_id, "org_unit_id": unit_id,
                          "location_id": loc_id, "legal_entity_id": le_id})
    assert r.status_code == 201, r.text
    offer = r.json()
    r = client.post(f"/api/v1/recruitment/offers/{offer['id']}/send",
                    headers=h_admin)
    assert r.status_code == 200, r.text
    offer = r.json()
    assert offer["offer_token"], offer
    r = client.get(f"/api/v1/recruitment/offers/{offer['id']}/pdf",
                   headers=h_admin)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF", r.content[:20]
    pdf_path = (Path(__file__).resolve().parent.parent.parent / "demo"
                / "demo_offer_ayu_lestari.pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(r.content)
    trail["alur"].append({"aktor": "Administrator (HR)",
                          "aksi": "kirim e-offer",
                          "gaji": "Rp9.000.000",
                          "pdf_bytes": len(r.content),
                          "token_terbit": True})

    # 8. Kandidat accept via tautan publik (tanpa auth).
    r = client.post(f"/api/v1/public/offers/{offer['offer_token']}/accept",
                    json={"nik": "3174050101900001",
                          "full_name": "Ayu Lestari",
                          "birth_place": "Bandung",
                          "birth_date": "1998-05-20",
                          "email": "ayu.lestari@example.com",
                          "phone": "081234567890",
                          "bank_name": "BCA",
                          "bank_account_no": "1234567890"})
    assert r.status_code == 200, r.text
    hired = r.json()
    assert hired["nik"] == "3174050101900001"
    trail["alur"].append({"aktor": "Ayu Lestari (kandidat)",
                          "aksi": "accept offer via tautan publik",
                          "nik": hired["nik"]})

    # 9. Verifikasi employment tercipta.
    import uuid as _uuid

    db = new_session()
    emp = db.execute(
        select(Employment).where(
            Employment.id == _uuid.UUID(hired["employment_id"]))).scalar_one()
    ji = db.execute(
        select(JobInfo).where(
            JobInfo.employment_id == emp.id,
            JobInfo.valid_from == emp.start_date)).scalar_one()
    assert ji.event == "hire" and ji.event_reason == "Rekrutmen reguler"
    db.close()
    trail["employment"] = {"employment_id": hired["employment_id"],
                           "start_date": str(emp.start_date),
                           "status": emp.status,
                           "job_info_event": ji.event}

    # 10. Jejak audit lamaran.
    r = client.get("/api/v1/audit-logs", headers=h_admin, params={
        "object_type": "job_application", "object_id": app["id"], "limit": 50})
    assert r.status_code == 200, r.text
    trail["audit"] = [
        {"aksi": a["action"], "status_lama": (a.get("old_values") or {}).get("status"),
         "status_baru": (a.get("new_values") or {}).get("status"),
         "waktu": str(a.get("created_at")), "channel": a.get("channel"),
         "alasan": a.get("reason")}
        for a in r.json()
    ]

    out_path = (Path(__file__).resolve().parent.parent.parent / "demo"
                / "demo_recruitment_trail.json")
    out_path.write_text(json.dumps(trail, indent=2, ensure_ascii=False))
    print(f"Demo OK: Ayu Lestari hired (NIK {hired['nik']}, "
          f"mulai {emp.start_date})")
    print(f"PDF offer tersimpan -> {pdf_path}")
    print(f"Jejak audit lamaran ({len(trail['audit'])} entri) -> {out_path}")


if __name__ == "__main__":
    main()
