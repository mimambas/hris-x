"""Metrik baku ANL-004 & dasbor per peran ANL-003.

GET /dashboard/metrics mengembalikan delapan metrik PRD 13.4
dengan definisi yang dipakai. Voluntary turnover diklasifikasikan
dari alasan kejadian terminasi JobInfo (pengunduran diri =
sukarela, PHK = tidak sukarela); tanpa data terminasi hasilnya
0,0 persen dan tanpa kejadian terminasi sama sekali tetap None
(belum terklasifikasi — dinyatakan jujur, bukan tebakan).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import Employment, JobInfo, User

from .conftest import login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def nh(client):
    return login_headers(client, "hashiru", "u_none@x.id")


def _period() -> str:
    return date.today().strftime("%Y-%m")


def test_metrics_shape_and_values(client, ctx):
    r = client.get(f"/api/v1/dashboard/metrics?period={_period()}",
                   headers=ah(client))
    assert r.status_code == 200, r.text
    m = r.json()
    for key in ("turnover_rate_pct", "absenteeism_rate_pct",
                "late_rate_pct", "overtime_ratio_pct",
                "labor_cost_per_employee", "avg_headcount", "workdays"):
        assert key in m, key
    assert m["avg_headcount"] >= 2, m
    assert m["workdays"] >= 20, m
    # Tidak ada yang keluar pada fixture bulan ini: 0,0 persen,
    # hitungan kelas tersedia dan nol semua.
    assert m["terminated"] == 0, m
    assert m["voluntary_turnover_pct"] == 0.0, m
    assert m["voluntary_terminated"] == 0
    assert m["involuntary_terminated"] == 0
    assert m["unclassified_terminated"] == 0
    defs = m["definitions"]
    assert "voluntary_turnover" in defs and "turnover_rate" in defs


def test_metrics_payroll_period_optional(client, ctx):
    # Periode lampau tanpa payroll run tetap 200 dengan penanda.
    r = client.get("/api/v1/dashboard/metrics?period=2020-01",
                   headers=ah(client))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["payroll_run_available"] is False
    assert m["labor_cost_per_employee"] == 0


def test_metrics_requires_dashboard_permission(client, ctx):
    r = client.get(f"/api/v1/dashboard/metrics?period={_period()}",
                   headers=nh(client))
    assert r.status_code == 403, r.text


def _terminate(ctx, employment, reason: str | None):
    """Tutup employment hari ini + catat kejadian terminasinya."""
    db = ctx["db"]
    today = date.today()
    admin = db.execute(select(User).where(
        User.email == "admin_a@x.id")).scalar_one()
    emp = db.get(Employment, employment.id)
    emp.status = "terminated"
    emp.end_date = today
    if reason is not None:
        db.add(JobInfo(
            tenant_id=ctx["ta"].id, employment_id=emp.id,
            job_id=ctx["job_stf"].id, org_unit_id=ctx["ou"].id,
            location_id=ctx["loc_b"].id, valid_from=today,
            event="termination", event_reason=reason,
            created_by_user_id=admin.id))
    db.commit()


def test_voluntary_turnover_terklasifikasi_dari_alasan(client, ctx):
    _terminate(ctx, ctx["e_staff"], "Pengunduran diri")
    _terminate(ctx, ctx["e_mgr"], "PHK")
    r = client.get(f"/api/v1/dashboard/metrics?period={_period()}",
                   headers=ah(client))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["terminated"] == 2, m
    assert m["voluntary_terminated"] == 1, m
    assert m["involuntary_terminated"] == 1, m
    assert m["other_terminated"] == 0, m
    assert m["unclassified_terminated"] == 0, m
    expected = round(1 / m["avg_headcount"] * 100, 2)
    assert m["voluntary_turnover_pct"] == expected, m


def test_keluar_tanpa_kejadian_terminasi_belum_terklasifikasi(client, ctx):
    _terminate(ctx, ctx["e_staff"], None)
    r = client.get(f"/api/v1/dashboard/metrics?period={_period()}",
                   headers=ah(client))
    m = r.json()
    assert m["terminated"] == 1, m
    assert m["unclassified_terminated"] == 1, m
    # Semua yang keluar tidak terklasifikasi: tetap None, bukan 0.
    assert m["voluntary_turnover_pct"] is None, m
