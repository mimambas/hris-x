"""Perubahan data pribadi via approval + OTP (EXP-004, PRD 13.1).

Alamat/telepon/email/tanggungan masuk antrean persetujuan HR;
rekening wajib verifikasi OTP karyawan lebih dulu. Persetujuan HR
menerapkan perubahan ke Person (tanggungan juga membuat versi
CompInfo baru seperti ptkp-change).
"""

from __future__ import annotations

from app.models import CompInfo, Person
from app.services import effective_dating as ed

from .conftest import login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def test_address_change_via_approval(client, ctx):
    h_staff, h_hr = sh(client), fh(client)
    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "alamat",
        "new_values": {"address": "Jl. Melati No. 8, Bekasi"},
        "note": "Pindah rumah"})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "menunggu_persetujuan"
    assert req["old_values"]["address"] is None

    # Duplikat aktif untuk tipe yang sama ditolak.
    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "alamat",
        "new_values": {"address": "Jl. Lain No. 1, Bekasi"}})
    assert r.status_code == 422, r.text

    # Data belum berubah sebelum disetujui.
    me = client.get("/api/v1/data-changes/me", headers=h_staff).json()
    assert me["address"] is None

    queue = client.get("/api/v1/data-changes", headers=h_hr).json()
    assert any(q["id"] == req["id"] for q in queue)

    r = client.post(f"/api/v1/data-changes/{req['id']}/approve",
                    headers=h_hr, json={"reason": None})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disetujui"
    assert r.json()["applied_at"] is not None

    me = client.get("/api/v1/data-changes/me", headers=h_staff).json()
    assert me["address"] == "Jl. Melati No. 8, Bekasi"


def test_bank_change_requires_otp_first(client, ctx):
    h_staff, h_hr, h_mgr = sh(client), fh(client), mh(client)
    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "rekening",
        "new_values": {"bank_name": "Mandiri",
                       "bank_account_no": "1234567890"}})
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "menunggu_otp"

    # HR belum boleh menyetujui sebelum OTP terverifikasi.
    r = client.post(f"/api/v1/data-changes/{req['id']}/approve",
                    headers=h_hr, json={})
    assert r.status_code == 422, r.text

    # Orang lain tidak bisa memverifikasi OTP staf.
    r = client.post(f"/api/v1/data-changes/{req['id']}/verify-otp",
                    headers=h_mgr, json={"code": "123456"})
    assert r.status_code == 404, r.text

    # Kode salah -> 403 OTP_SALAH.
    r = client.post(f"/api/v1/data-changes/{req['id']}/verify-otp",
                    headers=h_staff, json={"code": "000000"})
    assert r.status_code == 403 and "OTP_SALAH" in r.text, r.text

    # HR membaca kode (assisted OTP) lalu karyawan memverifikasi.
    r = client.get(f"/api/v1/data-changes/{req['id']}/otp", headers=h_hr)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    r = client.post(f"/api/v1/data-changes/{req['id']}/verify-otp",
                    headers=h_staff, json={"code": code})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "menunggu_persetujuan"
    assert r.json()["otp_verified_at"] is not None

    # Kode sudah dibersihkan.
    r = client.get(f"/api/v1/data-changes/{req['id']}/otp", headers=h_hr)
    assert r.status_code == 404, r.text

    r = client.post(f"/api/v1/data-changes/{req['id']}/approve",
                    headers=h_hr, json={})
    assert r.status_code == 200, r.text
    me = client.get("/api/v1/data-changes/me", headers=h_staff).json()
    assert me["bank_name"] == "Mandiri"
    assert me["bank_account_no"] == "1234567890"


def test_cancel_and_reject_paths(client, ctx):
    h_staff, h_hr = sh(client), fh(client)
    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "telepon",
        "new_values": {"phone": "081234567890"}})
    req = r.json()
    r = client.post(f"/api/v1/data-changes/{req['id']}/cancel",
                    headers=h_staff)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dibatalkan"

    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "telepon",
        "new_values": {"phone": "081234567890"}})
    req2 = r.json()
    # Tolak tanpa alasan -> 422.
    r = client.post(f"/api/v1/data-changes/{req2['id']}/reject",
                    headers=h_hr, json={})
    assert r.status_code == 422, r.text
    r = client.post(f"/api/v1/data-changes/{req2['id']}/reject",
                    headers=h_hr,
                    json={"reason": "Nomor tidak dapat dihubungi"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ditolak"
    me = client.get("/api/v1/data-changes/me", headers=h_staff).json()
    assert me["phone"] != "081234567890"


def test_dependents_change_updates_ptkp_and_compinfo(client, ctx):
    h_staff, h_hr = sh(client), fh(client)
    # e_staff butuh CompInfo agar versi PTKP baru bisa dibuat.
    r = client.post("/api/v1/comp-info", headers=ah(client), json={
        "employment_id": str(ctx["e_staff"].id), "valid_from": "2024-01-01",
        "pay_group": "Bulanan",
        "components": {"gaji_pokok": 7000000},
        "event": "hire", "event_reason": "Penetapan gaji awal",
        "reason": "uji"})
    assert r.status_code == 201, r.text

    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "tanggungan", "new_values": {"ptkp": "K/1"},
        "note": "Menikah tahun ini"})
    assert r.status_code == 201, r.text
    req = r.json()
    r = client.post(f"/api/v1/data-changes/{req['id']}/approve",
                    headers=h_hr, json={})
    assert r.status_code == 200, r.text

    db = ctx["db"]
    db.expire_all()  # sesi test terpisah dari sesi request API
    person = db.get(Person, ctx["e_staff"].person_id)
    assert person.ptkp == "K/1"
    from datetime import date
    current = ed.as_of(db=db, tenant_id=ctx["ta"].id, model=CompInfo,
                       identity_field="employment_id",
                       identity_value=ctx["e_staff"].id,
                       as_of_date=date.today())
    assert current is not None and current.ptkp == "K/1"
