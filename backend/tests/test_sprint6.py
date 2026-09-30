"""Sprint 6 (PRD 24.2 S6): rekrutmen — requisition, lowongan, lamaran,
pipeline, wawancara, e-offer, hire.

Mengikuti pola tests/conftest.py (fixture ctx, login_headers).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.models import (
    FieldPermission,
    JobInfo,
    OrgUnit,
    OrgUnitInfo,
    PermissionRole,
    User,
)
from app.services import effective_dating as ed
from app.services import lifecycle as lc_service

from .conftest import PASSWORD, login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


_NIK_SEQ = [500]


def _nik():
    _NIK_SEQ[0] += 1
    return f"9000{_NIK_SEQ[0]:012d}"


def _admin_id(ctx):
    return ctx["db"].execute(
        select(User.id).where(User.email == "admin_a@x.id")).scalar_one()


def _grant_mgr_recruitment(ctx):
    """Grant view+correct requisition & job_application ke role MgrRole
    (pola hiring manager Sprint 6)."""
    db, ta = ctx["db"], ctx["ta"]
    r_mgr = db.execute(select(PermissionRole).where(
        PermissionRole.tenant_id == ta.id,
        PermissionRole.name == "MgrRole")).scalar_one()
    db.add_all([
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="requisition", field_name="*",
                        can_view=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="job_application", field_name="*",
                        can_view=True, can_correct=True),
    ])
    db.commit()


def _mk_requisition(client, h, ou_id, title="UI/UX Designer"):
    r = client.post("/api/v1/recruitment/requisitions", headers=h, json={
        "org_unit_id": str(ou_id), "job_title": title, "headcount": 1,
        "reason": "uji"})
    assert r.status_code == 201, r.text
    return r.json()


def _approve_requisition(client, h, req_id):
    r = client.post(f"/api/v1/recruitment/requisitions/{req_id}/submit",
                    headers=h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/recruitment/requisitions/{req_id}/approve",
                    headers=h, json={"note": "ok"})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_published_posting(client, h, req_id):
    r = client.post("/api/v1/recruitment/postings", headers=h, json={
        "requisition_id": req_id, "title": "UI/UX Designer",
        "description": "desc", "requirements": "req",
        "employment_type": "tetap", "location": "Jakarta"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = client.post(f"/api/v1/recruitment/postings/{pid}/publish", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_candidate(client, h, name="Ayu Lestari", email="ayu@example.id"):
    r = client.post("/api/v1/recruitment/candidates", headers=h, json={
        "name": name, "email": email, "phone": "081234567890",
        "source": "website"})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_application(client, h, posting_id, candidate_id):
    r = client.post("/api/v1/recruitment/applications", headers=h, json={
        "posting_id": posting_id, "candidate_id": candidate_id})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_full_flow(client, h, ctx, candidate_email="ayu@example.id"):
    """Requisition approved → posting published → kandidat → lamaran."""
    req = _mk_requisition(client, h, ctx["ou"].id)
    _approve_requisition(client, h, req["id"])
    posting = _mk_published_posting(client, h, req["id"])
    cand = _mk_candidate(client, h, email=candidate_email)
    app = _mk_application(client, h, posting["id"], cand["id"])
    return {"req": req, "posting": posting, "cand": cand, "app": app}


def _move(client, h, app_id, to_stage, note=None):
    return client.post(f"/api/v1/recruitment/applications/{app_id}/move",
                       headers=h,
                       json={"to_stage": to_stage, "note": note})


def _mk_offering(client, h, ctx):
    flow = _mk_full_flow(client, h, ctx)
    for to_stage, note in (("screening", "ok"), ("interview", "ok"),
                           ("offering", "siap")):
        r = _move(client, h, flow["app"]["id"], to_stage, note)
        assert r.status_code == 200, r.text
    flow["app"] = r.json()
    return flow


def _mk_sent_offer(client, h, ctx, days_valid=30):
    flow = _mk_offering(client, h, ctx)
    expires = (datetime.now(timezone.utc)
               + timedelta(days=days_valid)).isoformat()
    r = client.post("/api/v1/recruitment/offers", headers=h, json={
        "application_id": flow["app"]["id"], "salary": 9000000,
        "start_date": "2026-11-01", "contract_type": "PKWTT",
        "expires_at": expires,
        "job_id": str(ctx["job_stf"].id),
        "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id),
        "legal_entity_id": str(ctx["le"].id)})
    assert r.status_code == 201, r.text
    offer = r.json()
    r = client.post(f"/api/v1/recruitment/offers/{offer['id']}/send",
                    headers=h)
    assert r.status_code == 200, r.text
    flow["offer"] = r.json()
    assert flow["offer"]["offer_token"]
    return flow


# ------------------------------------------------------------------ Test
def test_publish_without_approved_requisition_422(client, ctx):
    h = ah(client)
    req = _mk_requisition(client, h, ctx["ou"].id)
    r = client.post("/api/v1/recruitment/postings", headers=h, json={
        "requisition_id": req["id"], "title": "UI/UX Designer"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    # Requisition masih draft → publish ditolak.
    r = client.post(f"/api/v1/recruitment/postings/{pid}/publish", headers=h)
    assert r.status_code == 422, r.text
    # Setelah approve → publish lolos.
    _approve_requisition(client, h, req["id"])
    r = client.post(f"/api/v1/recruitment/postings/{pid}/publish", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"


def test_duplicate_application_422(client, ctx):
    h = ah(client)
    flow = _mk_full_flow(client, h, ctx)
    r = client.post("/api/v1/recruitment/applications", headers=h, json={
        "posting_id": flow["posting"]["id"],
        "candidate_id": flow["cand"]["id"]})
    assert r.status_code == 422, r.text


def test_stage_transitions_audited(client, ctx):
    h = ah(client)
    flow = _mk_full_flow(client, h, ctx)
    app_id = flow["app"]["id"]
    r = _move(client, h, app_id, "screening", "CV cocok")
    assert r.status_code == 200, r.text
    # Jejak audit: action move_stage, actor + timestamp + note.
    r = client.get("/api/v1/audit-logs", headers=h, params={
        "object_type": "job_application", "object_id": app_id, "limit": 50})
    assert r.status_code == 200, r.text
    moves = [a for a in r.json() if a["action"] == "move_stage"]
    assert moves, r.json()
    m = moves[0]
    assert m["old_values"]["status"] == "applied"
    assert m["new_values"]["status"] == "screening"
    assert m["reason"] == "CV cocok"
    assert m["created_at"]  # timestamp tercatat


def test_backward_move_requires_note_422(client, ctx):
    h = ah(client)
    flow = _mk_full_flow(client, h, ctx)
    app_id = flow["app"]["id"]
    r = _move(client, h, app_id, "screening", "ok")
    assert r.status_code == 200, r.text
    # Mundur tanpa note → 422.
    r = _move(client, h, app_id, "applied")
    assert r.status_code == 422, r.text
    # Mundur dengan note → lolos.
    r = _move(client, h, app_id, "applied", "Salah stage, kembalikan")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"
    # Lompat maju (applied → interview) → 422.
    r = _move(client, h, app_id, "interview", "lompat")
    assert r.status_code == 422, r.text


def test_interview_feedback_saved(client, ctx):
    h = ah(client)
    flow = _mk_full_flow(client, h, ctx)
    app_id = flow["app"]["id"]
    for to_stage in ("screening", "interview"):
        r = _move(client, h, app_id, to_stage, "ok")
        assert r.status_code == 200, r.text
    admin_id = str(_admin_id(ctx))
    r = client.post("/api/v1/recruitment/interviews", headers=h, json={
        "application_id": app_id,
        "scheduled_at": "2026-10-05T10:00:00+07:00",
        "interviewer_ids": [admin_id],
        "location": "Jakarta", "mode": "onsite"})
    assert r.status_code == 201, r.text
    iv = r.json()
    r = client.post(f"/api/v1/recruitment/interviews/{iv['id']}/feedback",
                    headers=h, json={
                        "interviewer_id": admin_id, "score": 4,
                        "notes": "Bagus", "recommendation": "hire"})
    assert r.status_code == 201, r.text
    fb = r.json()
    assert fb["score"] == 4 and fb["recommendation"] == "hire"
    r = client.get(f"/api/v1/recruitment/interviews/{iv['id']}/feedback",
                   headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    # Feedback ganda interviewer yang sama → 422.
    r = client.post(f"/api/v1/recruitment/interviews/{iv['id']}/feedback",
                    headers=h, json={
                        "interviewer_id": admin_id, "score": 5,
                        "recommendation": "hire"})
    assert r.status_code == 422, r.text


def test_expired_offer_cannot_accept(client, ctx):
    h = ah(client)
    flow = _mk_sent_offer(client, h, ctx)
    offer = flow["offer"]
    # Paksa kedaluwarsa lewat DB.
    import uuid as _uuid

    from app.models import Offer
    db = ctx["db"]
    row = db.get(Offer, _uuid.UUID(offer["id"]))
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    r = client.post(f"/api/v1/public/offers/{offer['offer_token']}/accept",
                    json={"nik": _nik(), "full_name": "Kandidat X"})
    assert r.status_code == 422, r.text
    # Status offer otomatis menjadi expired.
    r = client.get(f"/api/v1/recruitment/offers/{offer['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "expired"


def test_accept_creates_person_employment(client, ctx):
    h = ah(client)
    flow = _mk_sent_offer(client, h, ctx)
    token = flow["offer"]["offer_token"]
    nik = _nik()
    r = client.post(f"/api/v1/public/offers/{token}/accept", json={
        "nik": nik, "full_name": "Ayu Lestari", "birth_place": "Bandung",
        "birth_date": "1998-05-20", "email": "ayu.hired@example.id",
        "phone": "081234567890", "bank_name": "BCA",
        "bank_account_no": "1234567890"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["nik"] == nik
    # Person tercipta dengan NIK benar.
    r = client.get(f"/api/v1/persons/{out['person_id']}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["nik"] == nik
    assert r.json()["phone"] == "081234567890"
    # JobInfo hire tercatat (event + reason).
    r = client.get("/api/v1/job-info/timeline", headers=h, params={
        "employment_id": out["employment_id"]})
    assert r.status_code == 200, r.text
    hires = [j for j in r.json() if j["event"] == "hire"]
    assert hires, r.json()
    assert hires[0]["event_reason"] == "Rekrutmen reguler"
    assert hires[0]["valid_from"] == "2026-11-01"
    # Lamaran menjadi hired.
    r = client.get(f"/api/v1/recruitment/applications/{flow['app']['id']}",
                   headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "hired"


def test_public_jobs_no_auth(client, ctx):
    h = ah(client)
    flow = _mk_full_flow(client, h, ctx)
    # Tanpa header auth → 200, hanya lowongan published & field publik.
    r = client.get("/api/v1/public/jobs", params={"tenant": "hashiru"})
    assert r.status_code == 200, r.text
    pub = [j for j in r.json() if j["id"] == flow["posting"]["id"]]
    assert len(pub) == 1
    assert set(pub[0]) == {"id", "title", "description", "requirements",
                           "employment_type", "location", "published_at"}
    # Tanpa param tenant → 422; tenant tak dikenal → 404.
    r = client.get("/api/v1/public/jobs")
    assert r.status_code == 422, r.text
    r = client.get("/api/v1/public/jobs", params={"tenant": "tidak-ada"})
    assert r.status_code == 404, r.text


def _mk_second_unit(ctx):
    """Unit organisasi kedua (di luar unit kerja u_mgr) via DB langsung."""
    from app.models import LegalEntity
    db = ctx["db"]
    admin_id = _admin_id(ctx)
    unit = OrgUnit(tenant_id=ctx["ta"].id)
    db.add(unit)
    db.flush()
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=OrgUnitInfo,
        identity_field="org_unit_id", identity_value=unit.id,
        valid_from=date(2020, 1, 1),
        values={"name": "Unit Lain", "parent_id": None,
                "legal_entity_id": ctx["le"].id, "is_active": True},
        event="org_unit_created", event_reason="Lainnya",
        created_by=admin_id, event_applies_to="org")
    db.commit()
    return unit


def test_manager_scope_limited_to_own_unit(client, ctx):
    _grant_mgr_recruitment(ctx)
    h_admin, h_mgr = ah(client), mh(client)
    other = _mk_second_unit(ctx)
    # u_mgr employment-nya di ctx["ou"]; requisition di unit lain → 403.
    req_out = _mk_requisition(client, h_admin, other.id, "Staff Gudang")
    r = client.get(f"/api/v1/recruitment/requisitions/{req_out['id']}",
                   headers=h_mgr)
    assert r.status_code == 403, r.text
    r = client.post(f"/api/v1/recruitment/requisitions/{req_out['id']}/approve",
                    headers=h_mgr, json={"note": "coba"})
    assert r.status_code == 403, r.text
    # Requisition di unit sendiri → boleh dilihat & diputuskan.
    req_own = _mk_requisition(client, h_admin, ctx["ou"].id, "Staff Admin")
    r = client.get(f"/api/v1/recruitment/requisitions/{req_own['id']}",
                   headers=h_mgr)
    assert r.status_code == 200, r.text
    # Daftar tersaring: hanya unit sendiri.
    r = client.get("/api/v1/recruitment/requisitions", headers=h_mgr)
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()]
    assert req_own["id"] in ids
    assert req_out["id"] not in ids
