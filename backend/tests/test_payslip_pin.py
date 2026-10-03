"""PIN slip gaji self-service (EXP-003, PRD 13.1).

Slip milik sendiri wajib PIN: belum diatur -> 403 PIN_BELUM_DIATUR,
salah -> 401 PIN_SALAH, 5x salah -> terkunci 15 menit, HR dapat
mereset. Slip orang lain oleh HR tetap tanpa PIN pemilik (diaudit).
Fixture payroll meniru pola tests/test_sprint4.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.models import Person, User

from .conftest import PASSWORD, login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


_NIK_SEQ = [900]


def _nik():
    _NIK_SEQ[0] += 1
    return f"7100{_NIK_SEQ[0]:012d}"


def _ctx_bank(ctx):
    db = ctx["db"]
    db.query(Person).filter(
        Person.tenant_id == ctx["ta"].id,
        Person.bank_account_no.is_(None),
    ).update({Person.bank_name: "BCA",
              Person.bank_account_no: "9000000001"},
             synchronize_session=False)
    db.commit()


def _mk_component(client, h, name, code, kind="earning",
                  calc_type="fixed", amount_or_formula="0"):
    r = client.post("/api/v1/payroll/components", headers=h, json={
        "name": name, "code": code, "kind": kind, "calc_type": calc_type,
        "amount_or_formula": amount_or_formula, "valid_from": "2024-01-01",
        "event": "salary_structure", "event_reason": "Komponen baru",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_paid_employee(client, ctx, nama, email, gaji=8_000_000):
    """Karyawan lengkap (job + comp + komponen) + akun login."""
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
        "job_id": str(ctx["job_stf"].id),
        "org_unit_id": str(ctx["ou"].id),
        "location_id": str(ctx["loc_b"].id),
        "event": "hire", "event_reason": "Rekrutmen reguler",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/comp-info", headers=h, json={
        "employment_id": e["id"], "valid_from": "2024-01-01",
        "pay_group": "Bulanan",
        "components": {"gaji_pokok": gaji, "tunjangan_tetap": 0},
        "event": "hire", "event_reason": "Penetapan gaji awal",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    for code in ("gaji_pokok", "tunjangan_tetap"):
        comp = _mk_component(client, h, code.replace("_", " ").title(),
                             code)
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
    user = db.execute(
        select(User).where(User.tenant_id == ctx["ta"].id,
                           User.email == email)).scalar_one()
    return {"person": p, "emp": e, "user": user, "email": email}


def _locked_run(client, ctx, period="2026-08"):
    _ctx_bank(ctx)
    h = ah(client)
    r = client.post("/api/v1/payroll/runs", headers=h,
                    json={"period": period})
    assert r.status_code == 201, r.text
    run = r.json()
    r = client.post(f"/api/v1/payroll/runs/{run['id']}/lock", headers=h)
    assert r.status_code == 200, r.text
    return run


def _slip_url(run, emp_id):
    return f"/api/v1/payroll/runs/{run['id']}/payslip/{emp_id}.pdf"


def test_pin_lifecycle_and_enforcement(client, ctx):
    target = _mk_paid_employee(client, ctx, "Pak Pin", "pakpin@x.id")
    run = _locked_run(client, ctx)
    h_self = login_headers(client, "hashiru", "pakpin@x.id")
    url = _slip_url(run, target["emp"]["id"])

    r = client.get("/api/v1/payslip-pin/status", headers=h_self)
    assert r.status_code == 200, r.text
    assert r.json()["pin_set"] is False
    assert r.json()["employment_id"] == target["emp"]["id"]

    # Riwayat slip sendiri: 1 baris dari run terkunci, tanpa izin payroll.
    r = client.get("/api/v1/payroll/my-payslips", headers=h_self)
    assert r.status_code == 200, r.text
    mine = r.json()
    assert len(mine) == 1 and mine[0]["period"] == "2026-08", mine
    assert mine[0]["take_home_pay"] > 0

    # Belum punya PIN: unduh slip sendiri ditolak.
    r = client.get(url, headers=h_self)
    assert r.status_code == 403 and "PIN_BELUM_DIATUR" in r.text, r.text

    # Konfirmasi tidak sama -> 422.
    r = client.post("/api/v1/payslip-pin/set", headers=h_self, json={
        "pin": "123456", "pin_confirmation": "123457"})
    assert r.status_code == 422, r.text

    r = client.post("/api/v1/payslip-pin/set", headers=h_self, json={
        "pin": "123456", "pin_confirmation": "123456"})
    assert r.status_code == 201, r.text
    assert r.json()["pin_set"] is True

    # Tanpa header PIN -> 403 PIN_SALAH (bukan 401 agar klien tidak
    # menafsirkannya sebagai sesi berakhir).
    r = client.get(url, headers=h_self)
    assert r.status_code == 403 and "PIN_SALAH" in r.text, r.text
    # PIN salah -> 403 (percobaan gagal ke-2).
    r = client.get(url, headers={**h_self, "X-Payslip-Pin": "000000"})
    assert r.status_code == 403, r.text
    # PIN benar -> PDF terunduh.
    r = client.get(url, headers={**h_self, "X-Payslip-Pin": "123456"})
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith(
        "application/pdf")

    # Ganti PIN: lama salah ditolak, benar diterima.
    r = client.post("/api/v1/payslip-pin/change", headers=h_self, json={
        "current_pin": "999999", "new_pin": "654321",
        "new_pin_confirmation": "654321"})
    assert r.status_code in (401, 403), r.text
    r = client.post("/api/v1/payslip-pin/change", headers=h_self, json={
        "current_pin": "123456", "new_pin": "654321",
        "new_pin_confirmation": "654321"})
    assert r.status_code == 200, r.text
    r = client.get(url, headers={**h_self, "X-Payslip-Pin": "123456"})
    assert r.status_code == 403, r.text

    # 5 kegagalan beruntun mengunci: reset dulu penghitung lewat PIN
    # benar, lalu gagal 5x lewat /verify.
    r = client.post("/api/v1/payslip-pin/verify", headers=h_self,
                    json={"pin": "654321"})
    assert r.status_code == 200, r.text
    for _ in range(4):
        r = client.post("/api/v1/payslip-pin/verify", headers=h_self,
                        json={"pin": "111111"})
        assert r.status_code == 403, r.text
    r = client.post("/api/v1/payslip-pin/verify", headers=h_self,
                    json={"pin": "111111"})
    assert r.status_code == 403 and "PIN_TERKUNCI" in r.text, r.text
    # PIN benar pun ditolak selama terkunci.
    r = client.post("/api/v1/payslip-pin/verify", headers=h_self,
                    json={"pin": "654321"})
    assert r.status_code == 403, r.text

    # HR mereset PIN -> karyawan membuat PIN baru dari awal.
    r = client.post("/api/v1/payslip-pin/reset", headers=fh(client),
                    json={"user_id": str(target["user"].id),
                          "reason": "Karyawan lupa PIN (uji)"})
    assert r.status_code == 200, r.text
    assert r.json()["pin_set"] is False
    r = client.post("/api/v1/payslip-pin/set", headers=h_self, json={
        "pin": "112233", "pin_confirmation": "112233"})
    assert r.status_code == 201, r.text
    r = client.get(url, headers={**h_self, "X-Payslip-Pin": "112233"})
    assert r.status_code == 200, r.text


def test_hr_downloads_other_slip_without_owner_pin(client, ctx):
    target = _mk_paid_employee(client, ctx, "Bu Slip", "buslip@x.id")
    run = _locked_run(client, ctx, period="2026-09")
    url = _slip_url(run, target["emp"]["id"])
    # HR (wildcard payroll) mengunduh slip karyawan tanpa PIN pemilik.
    r = client.get(url, headers=fh(client))
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    # Karyawan lain tanpa PIN pemilik pun tidak bisa lewat jalur sendiri:
    # staf fixture tidak memiliki employment itu -> bukan jalur PIN,
    # dan tanpa izin payroll ia ditolak di gerbang permission.
    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get(url, headers=h_staff)
    assert r.status_code == 403, r.text
