"""Test modul Kompensasi (CMP, PRD 12.4 F3).

- CMP-001: pay grade + salary band; compa-ratio otomatis per karyawan.
- CMP-002: siklus merit + anggaran unit + guideline (rating x compa-ratio);
  usulan yang membuat unit melewati anggaran butuh persetujuan tambahan.
- CMP-005: finalisasi menulis versi CompInfo baru (event_reason "Merit").
- CMP-003: total rewards statement (JSON + PDF).
- CMP-004: analitik kesetaraan hanya untuk izin khusus.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models import (
    Appraisal,
    CompInfo,
    FieldPermission,
    PermissionRole,
    Person,
    ReviewCycle,
    User,
)
from app.services import effective_dating as ed
from tests.conftest import login_headers


def _admin(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def _beri_gaji(db, ctx, employment, gaji):
    admin = db.query(User).filter_by(email="admin_a@x.id").one()
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=CompInfo,
        identity_field="employment_id", identity_value=employment.id,
        valid_from=date(2024, 1, 1),
        values={"pay_group": "Bulanan",
                "components": {"gaji_pokok": gaji, "tunjangan_tetap": 0},
                "ptkp": "TK/0"},
        event="hire", event_reason="Penetapan gaji awal",
        created_by=admin.id, event_applies_to="lifecycle",
    )
    db.commit()


def _buat_grade(client, h, code="G5", mn=8_000_000, mid=10_000_000,
                mx=12_000_000):
    r = client.post(
        "/api/v1/compensation/pay-grades",
        json={"code": code, "name": f"Grade {code}", "band_min": mn,
              "band_mid": mid, "band_max": mx},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _buat_siklus(client, h, year=2027):
    r = client.post(
        "/api/v1/compensation/cycles",
        json={"name": f"Merit {year}", "kind": "merit", "period_year": year,
              "effective_date": f"{year}-01-01"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _grant_mgr_comp(db, ctx):
    r_mgr = db.query(PermissionRole).filter_by(
        tenant_id=ctx["ta"].id, name="MgrRole").one()
    db.add(FieldPermission(tenant_id=ctx["ta"].id, role_id=r_mgr.id,
                           object_name="compensation", field_name="*",
                           can_view=True, can_correct=True))
    db.commit()


def test_pay_grade_crud_dan_validasi(client, ctx):
    h = _admin(client)
    g = _buat_grade(client, h)
    # Kode duplikat ditolak.
    r = client.post("/api/v1/compensation/pay-grades",
                    json={"code": "G5", "name": "Duplikat",
                          "band_min": 1, "band_mid": 2, "band_max": 3},
                    headers=h)
    assert r.status_code == 422
    # Band tidak valid (min > mid) ditolak.
    r = client.post("/api/v1/compensation/pay-grades",
                    json={"code": "G9", "name": "Rusak",
                          "band_min": 10, "band_mid": 5, "band_max": 3},
                    headers=h)
    assert r.status_code == 422
    # Koreksi band.
    r = client.patch(f"/api/v1/compensation/pay-grades/{g['id']}",
                     json={"band_max": 13_000_000}, headers=h)
    assert r.status_code == 200
    assert r.json()["band_max"] == 13_000_000
    assert len(client.get("/api/v1/compensation/pay-grades",
                          headers=h).json()) == 1


def test_compa_ratio_per_karyawan(client, ctx):
    h = _admin(client)
    db = ctx["db"]
    g = _buat_grade(client, h)
    r = client.post("/api/v1/compensation/job-grades",
                    json={"job_id": str(ctx["job_stf"].id),
                          "pay_grade_id": g["id"]}, headers=h)
    assert r.status_code == 200, r.text
    _beri_gaji(db, ctx, ctx["e_staff"], 8_000_000)
    _beri_gaji(db, ctx, ctx["e_full"], 12_500_000)
    rows = client.get("/api/v1/compensation/employees", headers=h).json()
    by_emp = {r["employment_id"]: r for r in rows}
    staff = by_emp[str(ctx["e_staff"].id)]
    assert staff["grade_code"] == "G5"
    assert staff["compa_ratio"] == 0.8
    full = by_emp[str(ctx["e_full"].id)]
    assert full["compa_ratio"] == 1.25
    # Jabatan manajer belum punya grade -> compa-ratio kosong.
    mgr = by_emp[str(ctx["e_mgr"].id)]
    assert mgr["grade_code"] is None
    assert mgr["compa_ratio"] is None


def test_siklus_usulan_dan_guideline(client, ctx):
    h = _admin(client)
    db = ctx["db"]
    g = _buat_grade(client, h)
    client.post("/api/v1/compensation/job-grades",
                json={"job_id": str(ctx["job_stf"].id),
                      "pay_grade_id": g["id"]}, headers=h)
    _beri_gaji(db, ctx, ctx["e_staff"], 8_000_000)
    # Rating terakhir 4.8 -> guideline bawaan 8-12%; CR 0,8 -> tanpa geser.
    rc = ReviewCycle(tenant_id=ctx["ta"].id, name="Review 2026", year=2026,
                     status="closed", start_date=date(2026, 1, 1),
                     end_date=date(2026, 12, 31))
    db.add(rc)
    db.flush()
    db.add(Appraisal(tenant_id=ctx["ta"].id,
                     employment_id=ctx["e_staff"].id, cycle_id=rc.id,
                     final_score=Decimal("4.80")))
    db.commit()
    cycle = _buat_siklus(client, h)
    r = client.post(f"/api/v1/compensation/cycles/{cycle['id']}/proposals",
                    json={"employment_id": str(ctx["e_staff"].id),
                          "proposed_salary": 8_800_000}, headers=h)
    assert r.status_code == 201, r.text
    prop = r.json()
    assert prop["rating"] == 4.8
    assert prop["guideline_min_pct"] == 8.0
    assert prop["guideline_max_pct"] == 12.0
    assert prop["increase_pct"] == 10.0
    assert prop["within_guideline"] is True
    assert prop["status"] == "draft"
    # Satu karyawan hanya boleh punya satu usulan per siklus.
    r = client.post(f"/api/v1/compensation/cycles/{cycle['id']}/proposals",
                    json={"employment_id": str(ctx["e_staff"].id),
                          "proposed_salary": 9_000_000}, headers=h)
    assert r.status_code == 422


def test_over_budget_butuh_persetujuan_tambahan(client, ctx):
    h = _admin(client)
    db = ctx["db"]
    _beri_gaji(db, ctx, ctx["e_staff"], 8_000_000)
    cycle = _buat_siklus(client, h)
    # Anggaran unit hanya Rp10 juta/tahun; kenaikan yang diusulkan
    # (8jt -> 9,6jt) bernilai Rp19,2 juta/tahun.
    r = client.put(
        f"/api/v1/compensation/cycles/{cycle['id']}/budgets/{ctx['ou'].id}",
        json={"budget_amount": 10_000_000}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/compensation/cycles/{cycle['id']}/proposals",
                    json={"employment_id": str(ctx["e_staff"].id),
                          "proposed_salary": 9_600_000}, headers=h)
    pid = r.json()["id"]
    assert client.post(f"/api/v1/compensation/proposals/{pid}/submit",
                       headers=h).status_code == 200
    r = client.post(f"/api/v1/compensation/proposals/{pid}/approve",
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_extra_approval"
    assert r.json()["over_budget"] is True
    # Persetujuan tambahan tidak boleh oleh orang yang sama.
    r = client.post(f"/api/v1/compensation/proposals/{pid}/approve-extra",
                    headers=h)
    assert r.status_code == 422
    # HR lain (u_full, peran HR) dapat memberi persetujuan tambahan.
    h_hr = login_headers(client, "hashiru", "u_full@x.id")
    r = client.post(f"/api/v1/compensation/proposals/{pid}/approve-extra",
                    headers=h_hr)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


def test_finalize_menulis_compinfo_merit(client, ctx):
    h = _admin(client)
    db = ctx["db"]
    _beri_gaji(db, ctx, ctx["e_staff"], 8_000_000)
    cycle = _buat_siklus(client, h)
    r = client.post(f"/api/v1/compensation/cycles/{cycle['id']}/proposals",
                    json={"employment_id": str(ctx["e_staff"].id),
                          "proposed_salary": 9_000_000}, headers=h)
    pid = r.json()["id"]
    # Finalize ditolak selama ada usulan belum diputuskan.
    r = client.post(f"/api/v1/compensation/cycles/{cycle['id']}/finalize",
                    headers=h)
    assert r.status_code == 422
    client.post(f"/api/v1/compensation/proposals/{pid}/submit", headers=h)
    client.post(f"/api/v1/compensation/proposals/{pid}/approve", headers=h)
    r = client.post(f"/api/v1/compensation/cycles/{cycle['id']}/finalize",
                    headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "finalized"
    # CMP-005: versi CompInfo baru berlaku per tanggal efektif siklus,
    # dengan event_reason "Merit".
    rec = ed.as_of(db=db, tenant_id=ctx["ta"].id, model=CompInfo,
                   identity_field="employment_id",
                   identity_value=ctx["e_staff"].id,
                   as_of_date=date(2027, 6, 1))
    assert rec.components["gaji_pokok"] == 9_000_000
    assert rec.event == "compensation_change"
    assert rec.event_reason == "Merit"
    # Sebelum tanggal efektif, gaji lama yang berlaku.
    rec_lama = ed.as_of(db=db, tenant_id=ctx["ta"].id, model=CompInfo,
                        identity_field="employment_id",
                        identity_value=ctx["e_staff"].id,
                        as_of_date=date(2026, 6, 1))
    assert rec_lama.components["gaji_pokok"] == 8_000_000


def test_total_rewards_saya(client, ctx):
    db = ctx["db"]
    _beri_gaji(db, ctx, ctx["e_staff"], 8_000_000)
    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get("/api/v1/compensation/total-rewards/me", headers=h_staff)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["monthly_cash"] == 8_000_000
    assert body["thr_estimate"] == 8_000_000
    assert body["annual_total"] > 8_000_000 * 12
    r = client.get("/api/v1/compensation/total-rewards/me/pdf",
                   headers=h_staff)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")


def test_analitik_kesetaraan_izin_khusus(client, ctx):
    h = _admin(client)
    db = ctx["db"]
    g = _buat_grade(client, h)
    client.post("/api/v1/compensation/job-grades",
                json={"job_id": str(ctx["job_stf"].id),
                      "pay_grade_id": g["id"]}, headers=h)
    _beri_gaji(db, ctx, ctx["e_staff"], 8_000_000)
    _beri_gaji(db, ctx, ctx["e_full"], 10_000_000)
    p_staff = db.get(Person, ctx["e_staff"].person_id)
    p_staff.gender = "L"
    p_full = db.get(Person, ctx["e_full"].person_id)
    p_full.gender = "P"
    db.commit()
    r = client.get("/api/v1/compensation/analytics/pay-equity", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["min_group"] == 5
    rows = {(x["grade_code"], x["gender"]): x for x in body["rows"]}
    # Grup 1 orang: statistik disembunyikan (kalau tidak, rata-rata =
    # gaji persis orang itu). Jumlah anggota tetap tampil.
    laki = rows[("G5", "Laki-laki")]
    assert laki["headcount"] == 1 and laki["suppressed"] is True
    assert laki["avg_salary"] is None and laki["median_salary"] is None
    per = rows[("G5", "Perempuan")]
    assert per["suppressed"] is True and per["avg_salary"] is None
    gap = body["gaps"][0]
    assert gap["suppressed"] is True
    assert gap["avg_laki"] is None and gap["gap_pct"] is None
    # Manajer (punya izin compensation) tetap ditolak: izin khusus HR.
    _grant_mgr_comp(db, ctx)
    h_mgr = login_headers(client, "hashiru", "u_mgr@x.id")
    assert client.get("/api/v1/compensation/analytics/pay-equity",
                      headers=h_mgr).status_code == 403
    assert client.get("/api/v1/compensation/pay-grades",
                      headers=h_mgr).status_code == 200


def test_analitik_kesetaraan_grup_cukup_statistik_tampil(client, ctx):
    from tests.conftest import _mkperson_emp_job

    h = _admin(client)
    db = ctx["db"]
    g = _buat_grade(client, h)
    client.post("/api/v1/compensation/job-grades",
                json={"job_id": str(ctx["job_stf"].id),
                      "pay_grade_id": g["id"]}, headers=h)
    admin = db.query(User).filter_by(email="admin_a@x.id").one()
    gaji_l = [8_000_000, 9_000_000, 10_000_000, 11_000_000, 12_000_000]
    gaji_p = [9_000_000, 9_000_000, 10_000_000, 10_000_000, 11_000_000]
    for i, (gender, daftar) in enumerate((("L", gaji_l), ("P", gaji_p))):
        for j, gaji in enumerate(daftar):
            p, e, _ = _mkperson_emp_job(
                db, ctx["ta"].id, f"88{i}{j}" + "0" * 12,
                f"Uji {gender}{j}", ctx["le"].id, ctx["loc_b"].id,
                ctx["job_stf"].id, ctx["ou"].id, admin.id)
            p.gender = gender
            db.commit()
            _beri_gaji(db, ctx, e, gaji)
    r = client.get("/api/v1/compensation/analytics/pay-equity", headers=h)
    assert r.status_code == 200, r.text
    rows = {(x["grade_code"], x["gender"]): x for x in r.json()["rows"]}
    laki = rows[("G5", "Laki-laki")]
    assert laki["headcount"] == 5 and laki["suppressed"] is False
    assert laki["avg_salary"] == 10_000_000
    assert laki["median_salary"] == 10_000_000
    per = rows[("G5", "Perempuan")]
    assert per["avg_salary"] == 9_800_000
    assert per["median_salary"] == 10_000_000
    gap = r.json()["gaps"][0]
    assert gap["suppressed"] is False
    assert gap["gap_pct"] == 2.0


def test_isolasi_tenant(client, ctx):
    h = _admin(client)
    cycle = _buat_siklus(client, h)
    h_b = login_headers(client, "acme", "admin_b@x.id")
    assert client.get("/api/v1/compensation/pay-grades",
                      headers=h_b).json() == []
    assert client.get(f"/api/v1/compensation/cycles/{cycle['id']}",
                      headers=h_b).status_code == 404
