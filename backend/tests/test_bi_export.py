"""Ekspor data warehouse/BI (ANL-005).

API tarik inkremental di atas objek terkurasi report builder:
autentikasi JWT atau kunci API BI (hash sha256, token tampil
sekali), izin RBP + populasi mengikuti pemilik kunci, filter
since berbasis penanda alami (tanggal/periode), format JSON/CSV,
pencabutan kunci.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.models import AttendanceRecord, Person

from .conftest import login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def _setup_payroll(client, ctx):
    h = ah(client)
    from tests.test_payslip_pin import _mk_paid_employee
    emp = _mk_paid_employee(client, ctx, "Bu BI", "bi@x.id")
    db = ctx["db"]
    for p in db.query(Person).filter_by(tenant_id=ctx["ta"].id).all():
        if not p.bank_account_no:
            p.bank_name, p.bank_account_no = "BCA", "9000000001"
    db.add(AttendanceRecord(
        tenant_id=ctx["ta"].id,
        employment_id=uuid.UUID(emp["emp"]["id"]),
        date=date(2026, 8, 3), status="present", late_minutes=0))
    db.commit()
    run = client.post("/api/v1/payroll/runs", headers=h,
                      json={"period": "2026-08"}).json()
    r = client.post(f"/api/v1/payroll/runs/{run['id']}/lock", headers=h)
    assert r.status_code == 200, r.text
    return emp


def test_bi_export_dan_kunci(client, ctx):
    emp = _setup_payroll(client, ctx)
    h = fh(client)

    r = client.get("/api/v1/bi/datasets", headers=h)
    assert r.status_code == 200, r.text
    keys = {d["dataset"] for d in r.json()}
    assert {"karyawan", "absensi", "payroll"} <= keys
    ds = {d["dataset"]: d for d in r.json()}
    assert ds["absensi"]["sync_field"] == "tanggal"
    assert ds["karyawan"]["sync_field"] is None
    assert ds["payroll"]["mode"] == "inkremental"

    # Ekspor JWT: payroll periode 2026-08.
    r = client.get("/api/v1/bi/exports/payroll?since=2026-08",
                   headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert body["rows"][0]["periode"] == "2026-08"
    assert body["rows"][0]["gaji_bersih"] > 0

    # since di masa depan -> kosong, bukan error.
    r = client.get("/api/v1/bi/exports/payroll?since=2027-01",
                   headers=h)
    assert r.json()["count"] == 0

    # Karyawan snapshot: since ditolak eksplisit.
    r = client.get("/api/v1/bi/exports/karyawan?since=2026-01-01",
                   headers=h)
    assert r.status_code == 422

    # Buat kunci -> token sekali; ekspor via header X-BI-Key.
    r = client.post("/api/v1/bi/keys", headers=h,
                    json={"name": "Metabase demo"})
    assert r.status_code == 201, r.text
    created = r.json()
    token = created["token"]
    assert token.startswith("hrisx_bi_")
    key_id = created["id"]

    r = client.get("/api/v1/bi/exports/absensi?since=2026-08-01",
                   headers={"X-BI-Key": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["tanggal"] == "2026-08-03"
    assert body["rows"][0]["nama"] == "Bu BI"

    r = client.get("/api/v1/bi/exports/absensi?since=2026-08-04",
                   headers={"X-BI-Key": token})
    assert r.json()["count"] == 0

    # Format CSV.
    r = client.get("/api/v1/bi/exports/absensi?format=csv",
                   headers={"X-BI-Key": token})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("nama,")

    # last_used_at tercatat.
    r = client.get("/api/v1/bi/keys", headers=h)
    mine = next(k for k in r.json() if k["id"] == key_id)
    assert mine["last_used_at"] is not None

    # Token acak ditolak; kunci dicabut -> 401.
    r = client.get("/api/v1/bi/exports/absensi",
                   headers={"X-BI-Key": "hrisx_bi_palsu"})
    assert r.status_code == 401
    r = client.delete(f"/api/v1/bi/keys/{key_id}", headers=h)
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    r = client.get("/api/v1/bi/exports/absensi",
                   headers={"X-BI-Key": token})
    assert r.status_code == 401


def test_bi_izin_objek_mengikuti_pemilik(client, ctx):
    _setup_payroll(client, ctx)
    h_none = login_headers(client, "hashiru", "u_none@x.id")
    r = client.get("/api/v1/bi/datasets", headers=h_none)
    assert r.status_code == 200, r.text
    assert r.json() == [] or all(
        d["dataset"] not in {"payroll"} for d in r.json())
    r = client.get("/api/v1/bi/exports/payroll", headers=h_none)
    assert r.status_code == 403, r.text
    r = client.get("/api/v1/bi/exports/absensi", headers=h_none)
    assert r.status_code == 403, r.text
