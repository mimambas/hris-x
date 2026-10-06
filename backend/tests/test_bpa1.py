"""BPA1 tahunan (PAY-011/PAY-006, sisa EXP-003).

Agregasi PayrollLine satu tahun -> ringkasan HR, PDF karyawan
di balik PIN slip, dan ekspor XML massal mengikuti struktur
template resmi DJP (A1Bulk). NIK tidak 16 digit memblokir ekspor.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from sqlalchemy import select

from app.core.security import hash_password
from app.models import LegalEntityInfo, Person, User

from .conftest import PASSWORD, login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


_SEQ = [100]


def _nik():
    _SEQ[0] += 1
    return f"7200{_SEQ[0]:012d}"


def _component(client, h, code):
    r = client.post("/api/v1/payroll/components", headers=h, json={
        "name": code.replace("_", " ").title(), "code": code,
        "kind": "earning", "calc_type": "fixed", "amount_or_formula": "0",
        "valid_from": "2024-01-01", "event": "salary_structure",
        "event_reason": "Komponen baru", "reason": "uji"})
    assert r.status_code == 201, r.text
    return r.json()


def _employee(client, ctx, nama, email, gaji=8_000_000):
    h = ah(client)
    p = client.post("/api/v1/persons", headers=h, json={
        "nik": _nik(), "full_name": nama, "bank_name": "BCA",
        "bank_account_no": "8210101999", "reason": "uji"}).json()
    e = client.post("/api/v1/employments", headers=h, json={
        "person_id": p["id"], "legal_entity_id": str(ctx["le"].id),
        "start_date": "2024-01-01", "status": "active",
        "reason": "uji"}).json()
    r = client.post("/api/v1/job-info", headers=h, json={
        "employment_id": e["id"], "valid_from": "2024-01-01",
        "job_id": str(ctx["job_stf"].id), "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id), "event": "hire",
        "event_reason": "Rekrutmen reguler", "reason": "uji"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/comp-info", headers=h, json={
        "employment_id": e["id"], "valid_from": "2024-01-01",
        "pay_group": "Bulanan",
        "components": {"gaji_pokok": gaji}, "event": "hire",
        "event_reason": "Penetapan gaji awal", "reason": "uji"})
    assert r.status_code == 201, r.text
    comp = _component(client, h, "gaji_pokok")
    r = client.post("/api/v1/payroll/assignments", headers=h, json={
        "employment_id": e["id"], "component_id": comp["id"],
        "valid_from": "2024-01-01", "event": "salary_structure",
        "event_reason": "Komponen baru", "reason": "uji"})
    assert r.status_code == 201, r.text
    db = ctx["db"]
    db.add(User(tenant_id=ctx["ta"].id, email=email,
                password_hash=hash_password(PASSWORD), full_name=nama,
                person_id=uuid.UUID(p["id"]), is_superadmin=False))
    db.commit()
    return {"person": p, "emp": e, "email": email}


def _run(client, ctx, period):
    db = ctx["db"]
    db.query(Person).filter(
        Person.tenant_id == ctx["ta"].id,
        Person.bank_account_no.is_(None),
    ).update({Person.bank_name: "BCA",
              Person.bank_account_no: "9000000001"},
             synchronize_session=False)
    db.commit()
    h = ah(client)
    run = client.post("/api/v1/payroll/runs", headers=h,
                      json={"period": period}).json()
    r = client.post(f"/api/v1/payroll/runs/{run['id']}/lock", headers=h)
    assert r.status_code == 200, r.text
    return run


def _set_npwp(ctx, npwp):
    db = ctx["db"]
    infos = db.execute(select(LegalEntityInfo).where(
        LegalEntityInfo.tenant_id == ctx["ta"].id)).scalars().all()
    assert infos
    for info in infos:
        info.npwp = npwp
    db.commit()


def test_summary_xml_dan_pdf(client, ctx):
    h = fh(client)
    emp = _employee(client, ctx, "Bu Ani BPA", "ani.bpa@x.id")
    _run(client, ctx, "2026-01")
    _run(client, ctx, "2026-02")

    r = client.get("/api/v1/bpa1/summary?year=2026", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    row = next(x for x in body["rows"]
               if x["employment_id"] == emp["emp"]["id"])
    assert row["nik_valid"] is True
    assert row["months_count"] == 2
    assert row["month_start"] == 1 and row["month_end"] == 2
    assert row["status"] == "Annualized"
    assert row["salary"] == 2 * 8_000_000
    assert row["gross_total"] >= row["salary"]
    assert body["employers"][0]["employees"] >= 1

    # NPWP belum diatur -> ekspor 422.
    le_id = str(ctx["le"].id)
    r = client.get(f"/api/v1/bpa1/export.xml?year=2026"
                   f"&legal_entity_id={le_id}", headers=h)
    assert r.status_code == 422, r.text
    assert "NPWP" in r.json()["detail"]

    _set_npwp(ctx, "1234567890123456")
    r = client.get(f"/api/v1/bpa1/export.xml?year=2026"
                   f"&legal_entity_id={le_id}", headers=h)
    assert r.status_code == 200, r.text
    root = ET.fromstring(r.content)
    assert root.tag == "A1Bulk"
    ns = {"xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    assert root.find("TIN").text == "1234567890123456"
    a1s = root.find("ListOfA1").findall("A1")
    mine = [a for a in a1s
            if a.find("CounterpartTin").text == emp["person"]["nik"]]
    assert len(mine) == 1
    a1 = mine[0]
    assert a1.find("SalaryPensionJhtTht").text == "16000000"
    assert a1.find("NumberOfMonths").text == "2"
    assert a1.find("StatusOfWithholding").text == "Annualized"
    assert a1.find("TaxObjectCode").text == "21-100-01"
    assert a1.find("Article21IncomeTax").text == "0"
    assert a1.find("IDPlaceOfBusinessActivity").text == \
        "1234567890123456" + "000000"
    assert a1.find("WithholdingDate").text == "2026-12-31"
    assert a1.find("CounterpartOpt").text == "Resident"
    assert a1.find("TaxCertificate").text == "N/A"
    nil_el = a1.find("CounterpartPassport")
    assert nil_el.get(f"{{{ns['xsi']}}}nil") == "true"

    # PDF karyawan tanpa PIN -> 403 PIN_BELUM_DIATUR; dengan PIN -> PDF.
    h_self = login_headers(client, "hashiru", "ani.bpa@x.id")
    url = f"/api/v1/bpa1/{emp['emp']['id']}.pdf?year=2026"
    r = client.get(url, headers=h_self)
    assert r.status_code == 403 and r.json()["detail"] == "PIN_BELUM_DIATUR"
    r = client.post("/api/v1/payslip-pin/set", headers=h_self, json={
        "pin": "135790", "pin_confirmation": "135790"})
    assert r.status_code == 201, r.text
    r = client.get(url, headers=h_self)
    assert r.status_code == 403 and r.json()["detail"] == "PIN_SALAH"
    r = client.get(url, headers={**h_self, "X-Payslip-Pin": "135790"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"

    # HR mengunduh PDF karyawan tanpa PIN pemilik.
    r = client.get(url, headers=h)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"

    # Tahun tanpa payroll -> PDF 404.
    r = client.get(f"/api/v1/bpa1/{emp['emp']['id']}.pdf?year=2021",
                   headers=h)
    assert r.status_code == 404


def test_nik_tidak_valid_mem_blokir_ekspor(client, ctx):
    h = fh(client)
    emp = _employee(client, ctx, "Pak Rusak NIK", "rusak@x.id")
    _run(client, ctx, "2026-03")
    db = ctx["db"]
    person = db.get(Person, uuid.UUID(emp["person"]["id"]))
    person.nik = "12345"
    db.commit()
    _set_npwp(ctx, "1234567890123456")
    r = client.get("/api/v1/bpa1/summary?year=2026", headers=h)
    row = next(x for x in r.json()["rows"]
               if x["employment_id"] == emp["emp"]["id"])
    assert row["nik_valid"] is False
    r = client.get(f"/api/v1/bpa1/export.xml?year=2026"
                   f"&legal_entity_id={ctx['le'].id}", headers=h)
    assert r.status_code == 422, r.text
    assert "Pak Rusak NIK" in r.json()["detail"]


def test_karyawan_biasa_ditolak_ringkasan(client, ctx):
    _employee(client, ctx, "Bu Polos", "polos@x.id")
    h_self = login_headers(client, "hashiru", "polos@x.id")
    r = client.get("/api/v1/bpa1/summary?year=2026", headers=h_self)
    assert r.status_code == 403, r.text


def test_atur_npwp_badan_hukum_via_org(client, ctx):
    """HR melengkapi NPWP dari halaman Organisasi (versi baru)."""
    h = fh(client)
    le_id = str(ctx["le"].id)
    r = client.post(f"/api/v1/org/legal-entities/{le_id}/versions",
                    headers=h, json={
                        "valid_from": "2026-10-06",
                        "name": "PT Uji",
                        "npwp": "1234567890123456",
                        "event": "org_data_update",
                        "event_reason": "Pembaruan data",
                        "reason": "Melengkapi NPWP untuk BPA1"})
    assert r.status_code == 201, r.text
    r = client.get("/api/v1/org/legal-entities", headers=h)
    mine = next(e for e in r.json() if e["id"] == le_id)
    assert mine["npwp"] == "1234567890123456"
