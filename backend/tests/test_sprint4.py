"""Uji Sprint 4: struktur gaji, formula engine, PPh 21, THR, run/lock/retro,
slip PDF, file transfer bank."""

from __future__ import annotations

import io

import pytest

from app.models import Person
from app.services import pph21 as pph21_service
from app.services.formula import FormulaError, evaluate
from tests.conftest import login_headers


def _ctx_bank(ctx):
    """Isi rekening dummy untuk karyawan bawaan fixture ctx.

    Lock payroll memvalidasi SEMUA karyawan aktif; karyawan ctx tidak
    punya rekening sehingga run tak bisa dikunci tanpa ini.
    """
    db = ctx["db"]
    db.query(Person).filter(
        Person.tenant_id == ctx["ta"].id,
        Person.bank_account_no.is_(None),
    ).update({Person.bank_name: "BCA",
              Person.bank_account_no: "9000000001"},
             synchronize_session=False)
    db.commit()


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


_NIK_SEQ = [100]


def _nik():
    _NIK_SEQ[0] += 1
    return f"7000{_NIK_SEQ[0]:012d}"


def _mk_employee(client, h, ctx, nama, gaji_pokok, tunjangan_tetap=0,
                 ptkp="TK/0", start="2024-01-01", bank="8210101999"):
    p = client.post("/api/v1/persons", headers=h, json={
        "nik": _nik(), "full_name": nama, "bank_name": "BCA",
        "bank_account_no": bank, "reason": "uji"}).json()
    e = client.post("/api/v1/employments", headers=h, json={
        "person_id": p["id"], "legal_entity_id": str(ctx["le"].id),
        "start_date": start, "status": "active", "reason": "uji"}).json()
    r = client.post("/api/v1/job-info", headers=h, json={
        "employment_id": e["id"], "valid_from": start,
        "job_id": str(ctx["job_stf"].id), "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id),
        "event": "hire", "event_reason": "Rekrutmen reguler",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/comp-info", headers=h, json={
        "employment_id": e["id"], "valid_from": start,
        "pay_group": "Bulanan",
        "components": {"gaji_pokok": gaji_pokok,
                       "tunjangan_tetap": tunjangan_tetap},
        "event": "hire", "event_reason": "Penetapan gaji awal",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    if ptkp != "TK/0":
        r = client.post(f"/api/v1/persons/{p['id']}/ptkp-change", headers=h,
                        json={"ptkp": ptkp, "effective_date": start,
                              "reason": "uji"})
        assert r.status_code == 200, r.text
    return p, e


def _mk_component(client, h, name, kind="earning", calc_type="fixed",
                  amount_or_formula="0", code=None, valid_from="2024-01-01",
                  event="salary_structure", event_reason="Komponen baru"):
    r = client.post("/api/v1/payroll/components", headers=h, json={
        "name": name, "code": code, "kind": kind, "calc_type": calc_type,
        "amount_or_formula": amount_or_formula, "valid_from": valid_from,
        "event": event, "event_reason": event_reason, "reason": "uji"})
    assert r.status_code == 201, r.text
    return r.json()


def _std_components(client, h):
    """5 komponen inti untuk uji hitungan tangan."""
    comps = {}
    comps["gaji_pokok"] = _mk_component(client, h, "Gaji Pokok",
                                        code="gaji_pokok")
    comps["tunjangan_tetap"] = _mk_component(client, h, "Tunjangan Tetap",
                                             code="tunjangan_tetap")
    comps["potongan_bpjs_kes"] = _mk_component(
        client, h, "Potongan BPJS Kes", kind="deduction",
        calc_type="formula", amount_or_formula="0.01 * min(gaji, 12000000)",
        code="potongan_bpjs_kes")
    comps["potongan_jht"] = _mk_component(
        client, h, "Potongan JHT", kind="deduction", calc_type="formula",
        amount_or_formula="0.02 * gaji", code="potongan_jht")
    comps["potongan_jp"] = _mk_component(
        client, h, "Potongan JP", kind="deduction", calc_type="formula",
        amount_or_formula="0.01 * min(gaji, 10547300)", code="potongan_jp")
    return comps


def _assign_all(client, h, emp_id, comps, valid_from="2024-01-01"):
    for comp in comps.values():
        r = client.post("/api/v1/payroll/assignments", headers=h, json={
            "employment_id": emp_id, "component_id": comp["id"],
            "valid_from": valid_from, "event": "salary_structure",
            "event_reason": "Komponen baru", "reason": "uji"})
        assert r.status_code == 201, r.text


def _run(client, h, period, **kw):
    body = {"period": period, **kw}
    r = client.post("/api/v1/payroll/runs", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _lock(client, h, run_id):
    r = client.post(f"/api/v1/payroll/runs/{run_id}/lock", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _lines(client, h, run_id):
    r = client.get(f"/api/v1/payroll/runs/{run_id}/lines", headers=h)
    assert r.status_code == 200, r.text
    return {l["employment_id"]: l for l in r.json()}


# ------------------------------------------------------- formula engine aman
def test_formula_valid():
    assert evaluate("hari_kerja * 50000", {"hari_kerja": 22}) == 1100000
    assert evaluate("0.02 * (gaji_pokok + tunjangan_tetap)",
                    {"gaji_pokok": 8000000, "tunjangan_tetap": 2000000}) == 200000
    assert evaluate("min(gaji, 12000000) * 0.01", {"gaji": 15000000}) == 120000
    assert evaluate("max(0, gaji - 5000000)", {"gaji": 3000000}) == 0
    assert evaluate("round(gaji / 3, 0)", {"gaji": 10000000}) == 3333333.0
    assert evaluate("abs(gaji - 9000000)", {"gaji": 8000000}) == 1000000


def test_formula_menolak_kode_jahat():
    for evil in [
        "__import__('os').system('x')",
        "[x for x in range(3)]",
        "gaji.__class__",
        "gaji.real",
        "(lambda: 1)()",
        "eval('1+1')",
        "open('/etc/passwd').read()",
        "{'a': 1}['a']",
        "gaji if gaji > 0 else 1",
        "'x' + 'y'",
        "True and gaji",
    ]:
        with pytest.raises(FormulaError):
            evaluate(evil, {"gaji": 8000000, "range": 1})
    # variabel tak dikenal juga ditolak
    with pytest.raises(FormulaError):
        evaluate("gaji + bonus_tak_ada", {"gaji": 1})


def test_formula_circular_ditolak(client, ctx):
    h = ah(client)
    a = _mk_component(client, h, "Komponen A", code="komp_a")
    _mk_component(client, h, "Komponen B", code="komp_b",
                  calc_type="formula", amount_or_formula="komp_a * 2")
    # A dibuat fixed dulu agar B valid; lalu A diubah jadi formula -> siklus.
    r = client.post(f"/api/v1/payroll/components/{a['id']}/versions",
                    headers=h, json={
                        "calc_type": "formula",
                        "amount_or_formula": "komp_b + 1",
                        "valid_from": "2024-01-01",
                        "event": "salary_structure",
                        "event_reason": "Perubahan rumus",
                        "reason": "uji"})
    assert r.status_code == 422, r.text
    assert "Circular" in r.text


def test_formula_nama_tak_dikenal_ditolak(client, ctx):
    h = ah(client)
    r = client.post("/api/v1/payroll/components", headers=h, json={
        "name": "Aneh", "kind": "earning", "calc_type": "formula",
        "amount_or_formula": "gaji_pokok * faktor_rahasia",
        "valid_from": "2024-01-01", "event": "salary_structure",
        "event_reason": "Komponen baru", "reason": "uji"})
    assert r.status_code == 422, r.text


def test_komponen_butuh_event_katalog(client, ctx):
    h = ah(client)
    r = client.post("/api/v1/payroll/components", headers=h, json={
        "name": "X", "kind": "earning", "calc_type": "fixed",
        "amount_or_formula": "1000", "valid_from": "2024-01-01",
        "event": "event_tak_ada", "event_reason": "x", "reason": "uji"})
    assert r.status_code == 422, r.text


def test_kode_otomatis_dari_nama(client, ctx):
    h = ah(client)
    c = _mk_component(client, h, "Tunjangan Hari Raya Khusus")
    assert c["code"] == "tunjangan_hari_raya_khusus", c


# ------------------------------------------------------------- PPh 21 tangan
def test_pph21_hitungan_tangan(client, ctx):
    """TK/0, gaji 10jt/bln -> PPh21 Rp235.000 (dihitung manual di ADR-0007)."""
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Pajak", 10_000_000)
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08")
    line = _lines(client, h, run["id"])[e["id"]]

    assert line["gross"] == 10_000_000
    assert line["breakdown"]["potongan_jht"] == 200_000
    assert line["breakdown"]["potongan_jp"] == 100_000
    assert line["breakdown"]["potongan_bpjs_kes"] == 100_000
    assert line["total_deductions"] == 400_000
    assert line["pph21"] == 235_000, line
    assert line["take_home_pay"] == 10_000_000 - 400_000 - 235_000
    assert line["pph21_borne_by"] == "employee"
    # employer cost tercatat sebagai info (tidak memotong take-home)
    assert line["employer_cost"]["jht_perusahaan"] == 370_000


def test_pph21_gross_up_konvergen(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji GrossUp", 10_000_000,
                        bank="8210102999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08", pph21_method="gross_up")
    line = _lines(client, h, run["id"])[e["id"]]

    assert line["pph21_borne_by"] == "employer"
    # tunjangan pajak = PPh21-nya sendiri, karyawan terima utuh
    assert line["breakdown"]["tunjangan_pajak"] == line["pph21"]
    assert line["pph21"] > 235_000  # > metode gross karena tunjangan kena pajak
    assert line["take_home_pay"] == line["gross"] - line["total_deductions"]


def test_pph21_net_ditanggung_perusahaan(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Net", 10_000_000,
                        bank="8210103999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08", pph21_method="net")
    line = _lines(client, h, run["id"])[e["id"]]

    assert line["pph21_borne_by"] == "employer"
    assert "tunjangan_pajak" not in line["breakdown"]
    assert line["take_home_pay"] == 10_000_000 - 400_000


def test_pph21_lapisan_progresif_unit():
    # 5%: 60jt pertama; 15% sisanya (s.d. 250jt)
    assert pph21_service.progressive_tax(100_000_000) == 9_000_000
    # 25% di atas 250jt
    assert pph21_service.progressive_tax(300_000_000) == (
        3_000_000 + 28_500_000 + 12_500_000)
    # 30% di atas 500jt
    assert pph21_service.progressive_tax(600_000_000) == (
        3_000_000 + 28_500_000 + 62_500_000 + 30_000_000)


# ------------------------------------------------------------------- THR
def test_thr_proporsional(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji THR Parsial", 12_000_000,
                        start="2026-01-10", bank="8210104999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    # Masa kerja 2026-01-10 -> 2026-03-20 = 2 bulan penuh
    run = _run(client, h, "2026-03", include_thr=True,
               thr_holiday_date="2026-03-20")
    line = _lines(client, h, run["id"])[e["id"]]
    assert line["thr_amount"] == 2_000_000, line  # 2/12 x 12jt


def test_thr_penuh_setahun(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji THR Penuh", 12_000_000,
                        start="2024-01-01", bank="8210105999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-03", include_thr=True,
               thr_holiday_date="2026-03-20")
    line = _lines(client, h, run["id"])[e["id"]]
    assert line["thr_amount"] == 12_000_000


def test_thr_tanpa_include_nol(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji THR Nol", 12_000_000,
                        start="2024-01-01", bank="8210106999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-03")
    line = _lines(client, h, run["id"])[e["id"]]
    assert line["thr_amount"] == 0


# ------------------------------------------------- run, lock, retro, Desember
def test_lock_dan_duplikat_ditolak(client, ctx):
    h = ah(client)
    _ctx_bank(ctx)
    _, e = _mk_employee(client, h, ctx, "Uji Kunci", 10_000_000,
                        bank="8210107999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08")
    _lock(client, h, run["id"])

    r = client.get(f"/api/v1/payroll/runs/{run['id']}", headers=h)
    assert r.json()["status"] == "locked"

    r = client.post(f"/api/v1/payroll/runs/{run['id']}/lock", headers=h)
    assert r.status_code == 422
    r = client.post("/api/v1/payroll/runs", headers=h,
                    json={"period": "2026-08"})
    assert r.status_code == 422  # periode sudah ada


def test_lock_ditolak_bila_rekening_kosong(client, ctx):
    h = ah(client)
    _ctx_bank(ctx)
    p = client.post("/api/v1/persons", headers=h, json={
        "nik": _nik(), "full_name": "Tanpa Rekening",
        "reason": "uji"}).json()  # tanpa bank_account_no
    e = client.post("/api/v1/employments", headers=h, json={
        "person_id": p["id"], "legal_entity_id": str(ctx["le"].id),
        "start_date": "2024-01-01", "status": "active",
        "reason": "uji"}).json()
    r = client.post("/api/v1/job-info", headers=h, json={
        "employment_id": e["id"], "valid_from": "2024-01-01",
        "job_id": str(ctx["job_stf"].id), "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id),
        "event": "hire", "event_reason": "Rekrutmen reguler",
        "reason": "uji"})
    assert r.status_code == 201
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08")
    r = client.post(f"/api/v1/payroll/runs/{run['id']}/lock", headers=h)
    assert r.status_code == 422
    assert "Rekening" in r.text


def test_retro_diff_muncul_di_run_berikutnya(client, ctx):
    h = ah(client)
    _ctx_bank(ctx)
    _, e = _mk_employee(client, h, ctx, "Uji Retro", 10_000_000,
                        bank="8210108999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)

    ags = _run(client, h, "2026-05")
    _lock(client, h, ags["id"])

    # Koreksi gaji berlaku mundur 1 Mei (setelah Mei dikunci).
    r = client.post("/api/v1/comp-info", headers=h, json={
        "employment_id": e["id"], "valid_from": "2026-05-01",
        "pay_group": "Bulanan",
        "components": {"gaji_pokok": 12_000_000, "tunjangan_tetap": 0},
        "event": "data_update", "event_reason": "Koreksi data",
        "reason": "uji retro"})
    assert r.status_code == 201, r.text

    jun = _run(client, h, "2026-06")
    line = _lines(client, h, jun["id"])[e["id"]]
    # Retro neto: +2jt gaji - 65.473 kenaikan potongan (JHT 40rb, JP 5.473,
    # BPJS Kes 20rb) karena potongan proporsional terhadap gaji.
    assert line["retro_amount"] == 1_934_527, line
    assert line["retro_detail"]["ref_period"] == "2026-05"
    # Gaji reguler Juni sudah memakai angka baru
    assert line["breakdown"]["gaji_pokok"] == 12_000_000
    _lock(client, h, jun["id"])

    # Juli: retro tidak dihitung ganda
    jul = _run(client, h, "2026-07")
    line2 = _lines(client, h, jul["id"])[e["id"]]
    assert line2["retro_amount"] == 0, line2


def test_penyesuaian_desember(client, ctx):
    _ctx_bank(ctx)
    """Kenaikan gaji tengah tahun -> total pajak = pajak tahunan aktual.

    Memakai tahun 2025 (penuh di masa lalu) karena run masa depan ditolak.
    """
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Desember", 10_000_000,
                        bank="8210109999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)

    for m in range(1, 13):
        period = f"2025-{m:02d}"
        if m == 7:
            r = client.post("/api/v1/comp-info", headers=h, json={
                "employment_id": e["id"], "valid_from": "2025-07-01",
                "pay_group": "Bulanan",
                "components": {"gaji_pokok": 12_000_000,
                               "tunjangan_tetap": 0},
                "event": "data_update", "event_reason": "Koreksi data",
                "reason": "uji desember"})
            assert r.status_code == 201, r.text
        run = _run(client, h, period)
        _lock(client, h, run["id"])

    total_tax, dec_tax = 0, 0
    for m in range(1, 13):
        r = client.get("/api/v1/payroll/runs", headers=h)
        run_id = next(x["id"] for x in r.json()
                      if x["period"] == f"2025-{m:02d}")
        line = _lines(client, h, run_id)[e["id"]]
        total_tax += line["pph21"]
        if m == 12:
            dec_tax = line["pph21"]

    # Hitungan tangan: bruto tahunan 132jt -> pajak 4.206.000;
    # Jan-Jun 235rb x6, Jul-Nov 496rb x5, Des penyesuaian 316rb.
    assert dec_tax == 316_000, dec_tax
    assert total_tax == 4_206_000, total_tax


def test_run_butuh_kunci_berurutan(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Urutan", 10_000_000,
                        bank="8210110999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    _run(client, h, "2026-08")  # draft, belum dikunci
    r = client.post("/api/v1/payroll/runs", headers=h,
                    json={"period": "2026-09"})
    assert r.status_code == 422
    assert "Kunci dulu" in r.text


# ------------------------------------------------- slip & file bank
def test_slip_rekonsiliasi(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Rekonsiliasi", 10_000_000,
                        bank="8210111999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08", include_thr=False)
    line = _lines(client, h, run["id"])[e["id"]]

    earnings = sum(v for c, v in line["breakdown"].items()
                   if not c.startswith("potongan_"))
    deductions = sum(v for c, v in line["breakdown"].items()
                     if c.startswith("potongan_"))
    assert earnings == line["gross"]
    assert deductions == line["total_deductions"]
    assert (line["gross"] + line["thr_amount"] + line["retro_amount"]
            - line["total_deductions"] - line["pph21"]
            == line["take_home_pay"])


def test_slip_pdf_tiga_karyawan(client, ctx):
    h = ah(client)
    emps = []
    for i, nama in enumerate(["Slip A", "Slip B", "Slip C"]):
        _, e = _mk_employee(client, h, ctx, nama, 8_000_000 + i * 1_000_000,
                            bank=f"8210112{i:03d}")
        emps.append(e)
    comps = _std_components(client, h)
    for e in emps:
        _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08")
    lines = _lines(client, h, run["id"])
    for e in emps:
        r = client.get(
            f"/api/v1/payroll/runs/{run['id']}/payslip/{e['id']}.pdf",
            headers=h)
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF", r.content[:20]
        line = lines[e["id"]]
        # rekonsiliasi: total = jumlah baris
        earnings = sum(v for c, v in line["breakdown"].items()
                       if not c.startswith("potongan_"))
        assert earnings == line["gross"]
        assert (line["gross"] - line["total_deductions"] - line["pph21"]
                == line["take_home_pay"])


def test_transfer_csv_valid(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Transfer", 10_000_000,
                        bank="8210112999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    run = _run(client, h, "2026-08")
    line = _lines(client, h, run["id"])[e["id"]]
    r = client.get(
        f"/api/v1/payroll/runs/{run['id']}/transfer-file?bank=bca", headers=h)
    assert r.status_code == 200, r.text
    rows = list(__import__("csv").reader(io.StringIO(r.text)))
    assert rows[0] == ["nama", "no_rekening", "nominal", "berita"]
    assert len(rows) == 1 + run["headcount"]
    mine = next(x for x in rows[1:] if x[1] == "8210112999")
    assert int(mine[2]) == line["take_home_pay"]
    assert "2026-08" in mine[3]


def test_desember_gross_up_konsisten_tahunan(client, ctx):
    """Setahun gross_up: total PPh21 == pajak tahunan atas total bruto."""
    from decimal import Decimal, ROUND_HALF_UP
    h = ah(client)
    _ctx_bank(ctx)
    _, e = _mk_employee(client, h, ctx, "Uji Des GU", 10_000_000,
                        bank="8210114999")
    comps = _std_components(client, h)
    _assign_all(client, h, e["id"], comps)
    for m in range(1, 13):
        run = _run(client, h, f"2025-{m:02d}", pph21_method="gross_up")
        _lock(client, h, run["id"])
    total_tax = total_gross = 0
    for m in range(1, 13):
        r = client.get("/api/v1/payroll/runs", headers=h)
        run_id = next(x["id"] for x in r.json()
                      if x["period"] == f"2025-{m:02d}")
        line = _lines(client, h, run_id)[e["id"]]
        total_tax += line["pph21"]
        total_gross += line["gross"]
        # tunjangan pajak selalu sama dengan PPh21-nya (konvergen)
        assert line["breakdown"]["tunjangan_pajak"] == line["pph21"]
        assert line["pph21_borne_by"] == "employer"
    pension = int((Decimal("0.03") * total_gross).to_integral_value(
        rounding=ROUND_HALF_UP))
    expected = pph21_service.annual_tax(total_gross, "TK/0", pension)
    assert total_tax == expected, (total_tax, expected)


def test_komponen_versi_masa_depan(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Uji Versi", 10_000_000,
                        bank="8210113999")
    um = _mk_component(client, h, "Uang Makan", code="uang_makan",
                       calc_type="formula",
                       amount_or_formula="hari_kerja * 50000")
    _assign_all(client, h, e["id"],
                {**_std_components(client, h), "uang_makan": um})
    r = client.post(f"/api/v1/payroll/components/{um['id']}/versions",
                    headers=h, json={
                        "amount_or_formula": "hari_kerja * 75000",
                        "valid_from": "2026-09-01",
                        "event": "salary_structure",
                        "event_reason": "Perubahan rumus",
                        "reason": "uji"})
    assert r.status_code == 201, r.text
    ags = _run(client, h, "2026-08")
    line = _lines(client, h, ags["id"])[e["id"]]
    assert line["breakdown"]["uang_makan"] == 21 * 50000  # Agustus: 21 hari kerja


def test_policy_basis_thr_total_fixed(client, ctx):
    h = ah(client)
    r = client.put("/api/v1/payroll/policy", headers=h, json={
        "thr_basis": "total_fixed", "reason": "uji"})
    assert r.status_code == 200, r.text
    assert r.json()["thr_basis"] == "total_fixed"
