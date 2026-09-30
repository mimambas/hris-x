"""Sprint 7 (PRD 24.2 S7): penilaian kinerja, matriks 9-box, pelatihan.

Mengikuti pola tests/conftest.py (fixture ctx, login_headers) dan
tests/test_sprint6.py (helper + grant RBP via db).
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import (
    FieldPermission,
    JobInfo,
    PermissionRole,
)
from app.services import performance as perf_service

from .conftest import login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def _grant_mgr_perf(ctx):
    """Grant goal/appraisal view+correct ke role MgrRole (pola Sprint 6)."""
    db, ta = ctx["db"], ctx["ta"]
    r_mgr = db.execute(select(PermissionRole).where(
        PermissionRole.tenant_id == ta.id,
        PermissionRole.name == "MgrRole")).scalar_one()
    db.add_all([
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="goal", field_name="*",
                        can_view=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="appraisal", field_name="*",
                        can_view=True, can_correct=True),
    ])
    db.commit()


def _make_staff_report_to_mgr(ctx):
    """Jadikan e_staff direct report dari e_mgr (untuk scope tim)."""
    db = ctx["db"]
    ji = db.execute(select(JobInfo).where(
        JobInfo.employment_id == ctx["e_staff"].id)).scalar_one()
    ji.manager_employment_id = ctx["e_mgr"].id
    db.commit()


def _mk_cycle(client, h, name="Penilaian Tahunan 2026"):
    r = client.post("/api/v1/performance/cycles", headers=h, json={
        "name": name, "year": 2026,
        "start_date": "2026-01-01", "end_date": "2026-12-31"})
    assert r.status_code == 201, r.text
    return r.json()


def _transition(client, h, cycle_id, to):
    r = client.post(f"/api/v1/performance/cycles/{cycle_id}/transition",
                    headers=h, json={"to_status": to})
    return r


def _mk_goal(client, h, cycle_id, emp_id, weight=100, title="Goal uji"):
    r = client.post(f"/api/v1/performance/cycles/{cycle_id}/goals",
                    headers=h, json={
                        "employment_id": str(emp_id), "title": title,
                        "description": "desc", "weight": weight,
                        "target_text": "target"})
    assert r.status_code == 201, r.text
    return r.json()


def _submit_goal(client, h, goal_id):
    r = client.post(f"/api/v1/performance/goals/{goal_id}/submit", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _approve_goal(client, h, goal_id, note="ok"):
    return client.post(f"/api/v1/performance/goals/{goal_id}/approve",
                       headers=h, json={"note": note})


def _mk_appraisal(client, h, emp_id, cycle_id):
    r = client.post("/api/v1/performance/appraisals", headers=h, json={
        "employment_id": str(emp_id), "cycle_id": str(cycle_id)})
    assert r.status_code == 201, r.text
    return r.json()


def _self_assess(client, h, appr_id, goal_id, score):
    return client.post(
        f"/api/v1/performance/appraisals/{appr_id}/self-assessment",
        headers=h, json={"scores": [{"goal_id": str(goal_id), "score": score,
                                     "comment": "mandiri"}]})


def _mgr_score(client, h, appr_id, goal_id, score):
    return client.post(
        f"/api/v1/performance/appraisals/{appr_id}/manager-score",
        headers=h, json={"scores": [{"goal_id": str(goal_id),
                                     "score": score}]})


def _calibrate(client, h, appr_id, potential):
    return client.post(
        f"/api/v1/performance/appraisals/{appr_id}/calibrate",
        headers=h, json={"potential_score": potential})


def _flow_to_year_end(client, h, ctx, emp_id, weight=100):
    """Siklus → goal_setting → goal approved → mid_year → year_end +
    appraisal dibuat. Kembalikan (cycle_id, goal_id, appr_id)."""
    c = _mk_cycle(client, h)
    assert _transition(client, h, c["id"], "goal_setting").status_code == 200
    g = _mk_goal(client, h, c["id"], emp_id, weight=weight)
    _submit_goal(client, h, g["id"])
    r = _approve_goal(client, h, g["id"])
    assert r.status_code == 200, r.text
    assert _transition(client, h, c["id"], "mid_year").status_code == 200
    assert _transition(client, h, c["id"], "year_end").status_code == 200
    a = _mk_appraisal(client, h, emp_id, c["id"])
    return c["id"], g["id"], a["id"]


# ------------------------------------------------------------------ 1. bobot
def test_weight_not_100_rejected_on_approve(client, ctx):
    h = ah(client)
    c = _mk_cycle(client, h)
    assert _transition(client, h, c["id"], "goal_setting").status_code == 200
    g = _mk_goal(client, h, c["id"], ctx["e_full"].id, weight=50)
    _submit_goal(client, h, g["id"])
    r = _approve_goal(client, h, g["id"])
    assert r.status_code == 422, r.text
    assert "100%" in r.text


def test_self_assessment_requires_weight_100(client, ctx):
    h = ah(client)
    c = _mk_cycle(client, h)
    assert _transition(client, h, c["id"], "goal_setting").status_code == 200
    g = _mk_goal(client, h, c["id"], ctx["e_full"].id, weight=100)
    _submit_goal(client, h, g["id"])
    # Belum di-approve → total approved 0 → self-assessment ditolak.
    a = _mk_appraisal(client, h, ctx["e_full"].id, c["id"])
    for to in ("mid_year", "year_end"):
        assert _transition(client, h, c["id"], to).status_code == 200
    r = _self_assess(client, h, a["id"], g["id"], 4)
    assert r.status_code == 422, r.text


# ------------------------------------------------------------------ 2. fase
def test_cycle_skip_phase_rejected(client, ctx):
    h = ah(client)
    c = _mk_cycle(client, h)
    r = _transition(client, h, c["id"], "year_end")
    assert r.status_code == 422, r.text
    r = _transition(client, h, c["id"], "closed")
    assert r.status_code == 422, r.text
    r = _transition(client, h, c["id"], "goal_setting")
    assert r.status_code == 200, r.text
    # Mundur juga ditolak.
    r = _transition(client, h, c["id"], "draft")
    assert r.status_code == 422, r.text


# ------------------------------------------------------------------ 3. mapping
def test_nine_box_mapping_star():
    policy = {"perf_low_max": 2.5, "perf_med_max": 3.75,
              "pot_low_max": 2.5, "pot_med_max": 3.5}
    box = perf_service.nine_box(4.5, 5, policy)
    assert box["box_key"] == "star"
    assert box["label_id"] == "Bintang"
    assert box["label_en"] == "Star"
    assert box["perf_category"] == "High" and box["pot_category"] == "High"
    box = perf_service.nine_box(2.0, 4, policy)
    assert box["box_key"] == "rough_diamond"
    box = perf_service.nine_box(3.0, 3, policy)
    assert box["box_key"] == "key_player"
    box = perf_service.nine_box(1.5, 2, policy)
    assert box["box_key"] == "low_performer"


# ------------------------------------------------------------------ 4. closed
def test_closed_cycle_immutable(client, ctx):
    h = ah(client)
    c = _mk_cycle(client, h)
    for to in ("goal_setting", "mid_year", "year_end", "calibration",
               "closed"):
        r = _transition(client, h, c["id"], to)
        assert r.status_code == 200, (to, r.text)
    # Mutasi setelah closed → 422.
    r = client.post(f"/api/v1/performance/cycles/{c['id']}/goals",
                    headers=h, json={
                        "employment_id": str(ctx["e_full"].id),
                        "title": "Goal telat", "weight": 100})
    assert r.status_code == 422, r.text
    # Transisi keluar dari closed → 422.
    r = _transition(client, h, c["id"], "calibration")
    assert r.status_code == 422, r.text


# ------------------------------------------------------------------ 5. 404
def test_employee_cannot_view_other_appraisal_404(client, ctx):
    _grant_mgr_perf(ctx)
    h, m = ah(client), mh(client)
    c = _mk_cycle(client, h)
    assert _transition(client, h, c["id"], "goal_setting").status_code == 200
    a = _mk_appraisal(client, h, ctx["e_staff"].id, c["id"])
    # u_mgr bukan atasan e_staff (manager_employment_id None) → 404,
    # bukan 403 (jangan bocorkan keberadaan).
    r = client.get(f"/api/v1/performance/appraisals/{a['id']}", headers=m)
    assert r.status_code == 404, r.text


def test_manager_can_view_team_appraisal(client, ctx):
    _grant_mgr_perf(ctx)
    _make_staff_report_to_mgr(ctx)
    h, m = ah(client), mh(client)
    c = _mk_cycle(client, h)
    assert _transition(client, h, c["id"], "goal_setting").status_code == 200
    a = _mk_appraisal(client, h, ctx["e_staff"].id, c["id"])
    r = client.get(f"/api/v1/performance/appraisals/{a['id']}", headers=m)
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ 6. manager score
def test_manager_score_before_self_rejected(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    r = _mgr_score(client, h, aid, gid, 4)
    assert r.status_code == 422, r.text
    assert "Self-assessment" in r.text


def test_manager_score_outside_year_end_rejected(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    r = _self_assess(client, h, aid, gid, 4)
    assert r.status_code == 200, r.text
    assert _transition(client, h, cid, "calibration").status_code == 200
    r = _mgr_score(client, h, aid, gid, 4)
    assert r.status_code == 422, r.text


# ------------------------------------------------------------------ 7. calibrate
def test_calibrate_outside_calibration_rejected(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    r = _calibrate(client, h, aid, 5)
    assert r.status_code == 422, r.text
    assert "calibration" in r.text


def test_calibrate_computes_final_score(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    assert _self_assess(client, h, aid, gid, 4).status_code == 200
    assert _mgr_score(client, h, aid, gid, 5).status_code == 200
    assert _transition(client, h, cid, "calibration").status_code == 200
    r = _calibrate(client, h, aid, 5)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["potential_score"] == 5
    assert float(body["final_score"]) == 5.0


# ------------------------------------------------------------------ 8. nine-box
def test_nine_box_before_calibration_rejected(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    r = client.get(f"/api/v1/performance/cycles/{cid}/nine-box", headers=h)
    assert r.status_code == 422, r.text


def test_nine_box_lists_star(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    assert _self_assess(client, h, aid, gid, 5).status_code == 200
    assert _mgr_score(client, h, aid, gid, 5).status_code == 200
    assert _transition(client, h, cid, "calibration").status_code == 200
    assert _calibrate(client, h, aid, 5).status_code == 200
    r = client.get(f"/api/v1/performance/cycles/{cid}/nine-box", headers=h)
    assert r.status_code == 200, r.text
    boxes = r.json()["boxes"]
    assert boxes["star"][0]["box_key"] == "star"
    assert boxes["star"][0]["label_id"] == "Bintang"


def test_nine_box_denied_for_non_hr(client, ctx):
    _grant_mgr_perf(ctx)
    h, m = ah(client), mh(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    assert _transition(client, h, cid, "calibration").status_code == 200
    # u_mgr punya appraisal/view tapi population "team" (bukan "all").
    r = client.get(f"/api/v1/performance/cycles/{cid}/nine-box", headers=m)
    assert r.status_code == 403, r.text


# ------------------------------------------------------------------ 9. rekomendasi
def test_training_recommendation_matches_box(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    assert _self_assess(client, h, aid, gid, 5).status_code == 200
    assert _mgr_score(client, h, aid, gid, 5).status_code == 200
    assert _transition(client, h, cid, "calibration").status_code == 200
    assert _calibrate(client, h, aid, 5).status_code == 200
    r = client.get(
        f"/api/v1/performance/cycles/{cid}/training-recommendations",
        headers=h, params={"employment_id": str(ctx["e_full"].id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["box_key"] == "star"
    assert body["recommended_categories"] == ["Leadership Development",
                                              "Mentoring"]


def test_training_recommendation_unavailable_before_calibration(client, ctx):
    h = ah(client)
    cid, gid, aid = _flow_to_year_end(client, h, ctx, ctx["e_full"].id)
    r = client.get(
        f"/api/v1/performance/cycles/{cid}/training-recommendations",
        headers=h, params={"employment_id": str(ctx["e_full"].id)})
    assert r.status_code == 422, r.text


# ------------------------------------------------------------------ 10. audit
def test_cycle_transition_audited(client, ctx):
    h = ah(client)
    c = _mk_cycle(client, h)
    assert _transition(client, h, c["id"], "goal_setting").status_code == 200
    r = client.get("/api/v1/audit-logs", headers=h, params={
        "object_type": "review_cycle", "object_id": c["id"], "limit": 50})
    assert r.status_code == 200, r.text
    actions = {(a["action"], (a.get("old_values") or {}).get("status"),
                (a.get("new_values") or {}).get("status"))
               for a in r.json()}
    assert ("create", None, "draft") in actions
    assert ("transition", "draft", "goal_setting") in actions


# ------------------------------------------------------------------ pelatihan
def test_course_enrollment_flow(client, ctx):
    h = ah(client)
    r = client.post("/api/v1/performance/courses", headers=h, json={
        "code": "LD-01", "name": "Leadership Development",
        "provider": "Academy", "duration_hours": 16, "cost": 2500000})
    assert r.status_code == 201, r.text
    course = r.json()
    r = client.post("/api/v1/performance/courses", headers=h, json={
        "code": "LD-01", "name": "Duplikat"})
    assert r.status_code == 422, r.text
    r = client.post("/api/v1/performance/enrollments", headers=h, json={
        "employment_id": str(ctx["e_full"].id), "course_id": course["id"]})
    assert r.status_code == 201, r.text
    enr = r.json()
    assert enr["status"] == "registered"
    r = client.post(
        f"/api/v1/performance/enrollments/{enr['id']}/complete", headers=h,
        json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
    assert r.json()["completed_at"] is not None
