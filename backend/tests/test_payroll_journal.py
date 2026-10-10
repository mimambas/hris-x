"""PAY-015 — jurnal payroll per cost center: debit = kredit per cost
center & per run, peta akun baku, ember tanpa cost center, dan CSV."""

from datetime import date

from app.models import (
    CostCenter,
    CostCenterInfo,
    Employment,
    JobInfo,
    OrgUnit,
    OrgUnitInfo,
    PayrollLine,
    PayrollRun,
    Person,
    User,
)
from app.services import effective_dating as ed
from tests.conftest import login_headers

PERIOD = "2026-09"


def _admin(db, ctx):
    return db.query(User).filter_by(email="admin_a@x.id").one()


def _mk_ou(db, ctx, name):
    admin = _admin(db, ctx)
    row = OrgUnit(tenant_id=ctx["ta"].id)
    db.add(row)
    db.flush()
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=OrgUnitInfo,
        identity_field="org_unit_id", identity_value=row.id,
        valid_from=date(2020, 1, 1),
        values={"name": name, "parent_id": None,
                "legal_entity_id": ctx["le"].id, "is_active": True},
        event="org_unit_created", event_reason="Lainnya",
        created_by=admin.id, event_applies_to="org")
    return row


def _mk_cc(db, ctx, code, name, org_unit_id):
    admin = _admin(db, ctx)
    row = CostCenter(tenant_id=ctx["ta"].id)
    db.add(row)
    db.flush()
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=CostCenterInfo,
        identity_field="cost_center_id", identity_value=row.id,
        valid_from=date(2020, 1, 1),
        values={"code": code, "name": name,
                "org_unit_id": org_unit_id, "is_active": True},
        event="org_unit_created", event_reason="Lainnya",
        created_by=admin.id, event_applies_to="org")
    return row


def _mk_emp(db, ctx, nik, name, org_unit_id):
    admin = _admin(db, ctx)
    p = Person(tenant_id=ctx["ta"].id, nik=nik, full_name=name)
    db.add(p)
    db.flush()
    e = Employment(tenant_id=ctx["ta"].id, person_id=p.id,
                   legal_entity_id=ctx["le"].id,
                   start_date=date(2024, 1, 1), status="active")
    db.add(e)
    db.flush()
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=JobInfo,
        identity_field="employment_id", identity_value=e.id,
        valid_from=date(2024, 1, 1),
        values={"job_id": ctx["job_stf"].id,
                "org_unit_id": org_unit_id,
                "location_id": ctx["loc_a"].id,
                "manager_employment_id": None},
        event="hire", event_reason="Lainnya", created_by=admin.id,
        event_applies_to="lifecycle")
    return e


def _line(ctx, run, emp, name, nik, **kw):
    base = dict(
        tenant_id=ctx["ta"].id, payroll_run_id=run.id,
        employment_id=emp.id, person_name=name, nik=nik,
        ptkp="TK/0", breakdown={}, inputs_snapshot={}, gross=0,
        total_deductions=0, pph21=0, pph21_borne_by="employee",
        thr_amount=0, retro_amount=0, retro_detail={},
        reimbursement_amount=0, reimbursement_claim_ids=[],
        take_home_pay=0, employer_cost={}, validation_errors=[])
    base.update(kw)
    return PayrollLine(**base)



def _setup(ctx):
    db = ctx["db"]
    _mk_cc(db, ctx, "CC-ENG", "Engineering", ctx["ou"].id)
    ou_ops = _mk_ou(db, ctx, "Ops")
    _mk_cc(db, ctx, "CC-OPS", "Operasional", ou_ops.id)
    ou_lab = _mk_ou(db, ctx, "Lab")
    emp_b = _mk_emp(db, ctx, "5555555555555555", "Bima", ou_ops.id)
    emp_c = _mk_emp(db, ctx, "6666666666666666", "Citra", ou_lab.id)
    run = PayrollRun(tenant_id=ctx["ta"].id, period=PERIOD,
                     status="locked", pph21_method="gross",
                     totals={}, headcount=3)
    db.add(run)
    db.flush()
    # Baris A — CC-ENG (e_full, unit Eng dari ctx): pajak karyawan.
    db.add(_line(
        ctx, run, ctx["e_full"], "Full", "1111111111111111",
        breakdown={"gaji_pokok": 10000000, "tunjangan_tetap": 2000000,
                   "potongan_bpjs_kes": 100000, "potongan_jht": 200000,
                   "potongan_jp": 100000, "potongan_mangkir": 50000,
                   "cicilan_pinjaman": 250000},
        gross=12000000, total_deductions=700000, pph21=300000,
        take_home_pay=11000000,
        employer_cost={"bpjs_kesehatan_perusahaan": 400000,
                       "jkk_perusahaan": 54000, "jkm_perusahaan": 30000,
                       "jht_perusahaan": 370000, "jp_perusahaan": 200000}))
    # Baris B — CC-OPS: pajak ditanggung perusahaan, THR, retro negatif,
    # reimbursement masuk bruto.
    db.add(_line(
        ctx, run, emp_b, "Bima", "5555555555555555",
        breakdown={"gaji_pokok": 7850000, "reimbursement_klaim": 150000,
                   "potongan_bpjs_kes": 80000, "potongan_jht": 160000,
                   "potongan_jp": 80000},
        gross=8000000, total_deductions=320000, pph21=200000,
        pph21_borne_by="employer", thr_amount=1000000,
        retro_amount=-100000, reimbursement_amount=150000,
        take_home_pay=8580000,
        employer_cost={"bpjs_kesehatan_perusahaan": 320000,
                       "jkk_perusahaan": 43200, "jkm_perusahaan": 24000,
                       "jht_perusahaan": 296000, "jp_perusahaan": 160000}))
    # Baris C — tanpa cost center: polos tanpa potongan.
    db.add(_line(
        ctx, run, emp_c, "Citra", "6666666666666666",
        breakdown={"gaji_pokok": 5000000}, gross=5000000,
        take_home_pay=5000000))
    db.commit()
    return run


def _entry(journal, cc, acc):
    for e in journal["entries"]:
        if e["cost_center_code"] == cc and e["account_code"] == acc:
            return e
    return None


def test_jurnal_seimbang_dan_rincian_akun(client, ctx):
    run = _setup(ctx)
    h = login_headers(client, "hashiru", "admin_a@x.id")
    r = client.get(f"/api/v1/payroll/runs/{run.id}/journal", headers=h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["period"] == PERIOD and j["status"] == "locked"
    assert j["journal_date"] == "2026-09-30"
    assert j["balanced"] is True
    assert j["total_debit"] == j["total_credit"] == 28097200
    assert all(b["balanced"] for b in j["per_cost_center"])
    assert {b["cost_center_code"] for b in j["per_cost_center"]} == {
        "CC-ENG", "CC-OPS", "TANPA-CC"}
    # CC-ENG
    assert _entry(j, "CC-ENG", "6101")["debit"] == 12000000
    assert _entry(j, "CC-ENG", "6105")["debit"] == 1054000
    assert _entry(j, "CC-ENG", "2101")["credit"] == 11000000
    assert _entry(j, "CC-ENG", "2103")["credit"] == 500000
    assert _entry(j, "CC-ENG", "2104")["credit"] == 954000
    assert _entry(j, "CC-ENG", "2105")["credit"] == 250000
    assert _entry(j, "CC-ENG", "2106")["credit"] == 50000
    # CC-OPS: gaji bersih dari reimbursement; retro negatif berbalik
    # menjadi kredit pada akun beban retro.
    assert _entry(j, "CC-OPS", "6101")["debit"] == 7850000
    assert _entry(j, "CC-OPS", "6104")["debit"] == 150000
    assert _entry(j, "CC-OPS", "6106")["debit"] == 200000
    retro = _entry(j, "CC-OPS", "6103")
    assert retro["debit"] == 0 and retro["credit"] == 100000
    assert _entry(j, "CC-OPS", "2104")["credit"] == 763200
    # Tanpa cost center tetap seimbang.
    assert _entry(j, "TANPA-CC", "6101")["debit"] == 5000000
    assert _entry(j, "TANPA-CC", "2101")["credit"] == 5000000


def test_jurnal_csv_dan_akses(client, ctx):
    run = _setup(ctx)
    h = login_headers(client, "hashiru", "admin_a@x.id")
    r = client.get(f"/api/v1/payroll/runs/{run.id}/journal.csv",
                   headers=h)
    assert r.status_code == 200, r.text
    assert "Kode Cost Center" in r.text and "TOTAL" in r.text
    assert "28097200" in r.text and "Seimbang" in r.text
    assert r.headers["content-disposition"].endswith(
        "filename=jurnal-2026-09.csv")
    # Tanpa izin payroll -> 403; run tak dikenal -> 404.
    h_none = login_headers(client, "hashiru", "u_none@x.id")
    r = client.get(f"/api/v1/payroll/runs/{run.id}/journal",
                   headers=h_none)
    assert r.status_code == 403, r.text
    r = client.get(
        "/api/v1/payroll/runs/00000000-0000-0000-0000-000000000000/journal",
        headers=h)
    assert r.status_code == 404, r.text
