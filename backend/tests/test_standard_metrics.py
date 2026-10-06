"""Metrik baku ANL-004 & dasbor per peran ANL-003.

GET /dashboard/metrics mengembalikan delapan metrik PRD 13.4
dengan definisi yang dipakai. Voluntary turnover dinyatakan
belum terklasifikasi (alasan keluar belum dibedakan pada data).
"""

from __future__ import annotations

from datetime import date

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
    # Voluntary belum terklasifikasi secara jujur (None), bukan tebakan.
    assert m["voluntary_turnover_pct"] is None, m
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
