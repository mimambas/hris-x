"""Learning lanjutan (LRN, PRD 12.5): konten & progres (LRN-001),
penugasan wajib + tenggat (LRN-002), nilai lulus + sertifikat otomatis +
masa berlaku sertifikasi (LRN-003).

Pola fixture mengikuti tests/test_sprint7.py (ctx conftest, admin
superadmin). Penyederhanaan jujur: pengingat kedaluwarsa = daftar
endpoint/UI, belum ada kanal email/push.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.models import Document

from .conftest import login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def _mk_course(client, h, **over):
    body = {"code": "K3-01", "name": "Keselamatan Kerja Dasar",
            "provider": "Lembaga K3", "duration_hours": 8, "cost": 500000}
    body.update(over)
    r = client.post("/api/v1/performance/courses", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _enroll(client, h, emp_id, course_id, **over):
    body = {"employment_id": str(emp_id), "course_id": course_id}
    body.update(over)
    r = client.post("/api/v1/performance/enrollments", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_course_learning_fields_round_trip(client, ctx):
    h = ah(client)
    c = _mk_course(client, h, content_type="video",
                   content_url="https://example.com/k3.mp4",
                   passing_score=70, cert_validity_months=12)
    assert c["content_type"] == "video"
    assert c["content_url"] == "https://example.com/k3.mp4"
    assert c["passing_score"] == 70
    assert c["cert_validity_months"] == 12
    r = client.post("/api/v1/performance/courses", headers=h, json={
        "code": "BAD-01", "name": "Konten tidak valid",
        "content_type": "scorm"})
    assert r.status_code == 422, r.text


def test_progress_tracked_and_status_flow(client, ctx):
    h = ah(client)
    c = _mk_course(client, h)
    enr = _enroll(client, h, ctx["e_full"].id, c["id"])
    assert enr["progress_percent"] == 0
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/progress",
        headers=h, json={"progress_percent": 40, "pre_score": 55})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["progress_percent"] == 40
    assert body["pre_score"] == 55
    assert body["status"] == "in_progress"
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete",
        headers=h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["progress_percent"] == 100
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/progress",
        headers=h, json={"progress_percent": 10})
    assert r.status_code == 422, r.text


def test_passing_gate_and_auto_certificate(client, ctx):
    h = ah(client)
    c = _mk_course(client, h, passing_score=70, cert_validity_months=12)
    enr = _enroll(client, h, ctx["e_full"].id, c["id"])
    # Tanpa skor -> ditolak; skor di bawah ambang -> ditolak.
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete",
        headers=h, json={})
    assert r.status_code == 422, r.text
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete",
        headers=h, json={"post_score": 60})
    assert r.status_code == 422, r.text
    # Skor lulus tercatat lewat progres, lalu selesai tanpa body skor.
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/progress",
        headers=h, json={"progress_percent": 100, "post_score": 85})
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete",
        headers=h, json={})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "completed"
    assert done["post_score"] == 85
    assert done["certificate_document_id"] is not None
    # Masa berlaku sertifikasi = selesai + 12 bulan.
    selesai = date.fromisoformat(done["completed_at"][:10])
    assert done["cert_expires_at"] == (selesai.replace(
        year=selesai.year + 1)).isoformat()
    # Dokumen sertifikat benar-benar terbit sebagai dokumen resmi.
    db = ctx["db"]
    doc = db.execute(select(Document).where(
        Document.id == uuid.UUID(done["certificate_document_id"]))).scalar_one()
    assert doc.doc_type == "sertifikat"
    assert doc.mime_type == "application/pdf"
    assert doc.employment_id == ctx["e_full"].id


def test_assignment_materializes_mandatory_enrollments(client, ctx):
    h = ah(client)
    c = _mk_course(client, h)
    r = client.post("/api/v1/performance/assignments", headers=h, json={
        "course_id": c["id"], "target_type": "job",
        "job_id": str(ctx["job_stf"].id), "due_days": 14})
    assert r.status_code == 201, r.text
    asg = r.json()
    assert asg["enrollments_created"] >= 2  # e_full + e_staff (STF)
    r = client.get("/api/v1/performance/enrollments", headers=h,
                   params={"employment_id": str(ctx["e_full"].id)})
    mine = [e for e in r.json() if e["course_id"] == c["id"]]
    assert len(mine) == 1
    assert mine[0]["is_mandatory"] is True
    expect_due = (date.today() + timedelta(days=14)).isoformat()
    assert mine[0]["due_date"] == expect_due
    # Penugasan kedua untuk kursus sama: enrollment aktif tidak digandakan.
    r = client.post("/api/v1/performance/assignments", headers=h, json={
        "course_id": c["id"], "target_type": "job",
        "job_id": str(ctx["job_stf"].id), "due_days": 14})
    assert r.status_code == 201, r.text
    assert r.json()["enrollments_created"] == 0
    # Daftar penugasan terbaca.
    r = client.get("/api/v1/performance/assignments", headers=h)
    assert r.status_code == 200 and len(r.json()) == 2


def test_overdue_report(client, ctx):
    h = ah(client)
    c = _mk_course(client, h)
    kemarin = (date.today() - timedelta(days=1)).isoformat()
    enr = _enroll(client, h, ctx["e_staff"].id, c["id"], due_date=kemarin,
                  is_mandatory=True)
    r = client.get("/api/v1/performance/learning/overdue", headers=h)
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()]
    assert enr["id"] in ids
    row = [x for x in r.json() if x["id"] == enr["id"]][0]
    assert row["is_overdue"] is True
    # Setelah selesai, tidak lagi terlambat.
    client.post(f"/api/v1/performance/enrollments/{enr['id']}/complete",
                headers=h, json={})
    r = client.get("/api/v1/performance/learning/overdue", headers=h)
    assert enr["id"] not in [row["id"] for row in r.json()]
    # Tanpa izin training_enrollment -> 403.
    hs = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get("/api/v1/performance/learning/overdue", headers=hs)
    assert r.status_code == 403, r.text


def test_expiring_certifications_window(client, ctx):
    h = ah(client)
    c = _mk_course(client, h, cert_validity_months=11)
    enr = _enroll(client, h, ctx["e_mgr"].id, c["id"])
    client.post(f"/api/v1/performance/enrollments/{enr['id']}/complete",
                headers=h, json={})
    r = client.get("/api/v1/performance/learning/certifications/expiring",
                   headers=h, params={"within_days": 365})
    assert r.status_code == 200, r.text
    rows = [x for x in r.json() if x["enrollment_id"] == enr["id"]]
    assert len(rows) == 1
    assert 300 <= rows[0]["days_remaining"] <= 340
    r = client.get("/api/v1/performance/learning/certifications/expiring",
                   headers=h, params={"within_days": 30})
    assert enr["id"] not in [x["enrollment_id"] for x in r.json()]


def test_learning_tenant_isolation(client, ctx):
    h = ah(client)
    c = _mk_course(client, h)
    _enroll(client, h, ctx["e_full"].id, c["id"],
            due_date=(date.today() - timedelta(days=2)).isoformat(),
            is_mandatory=True)
    hb = login_headers(client, "acme", "admin_b@x.id")
    r = client.get("/api/v1/performance/learning/overdue", headers=hb)
    assert r.status_code == 200 and r.json() == []
    r = client.get("/api/v1/performance/courses", headers=hb)
    assert r.status_code == 200 and r.json() == []
