"""Test PAY-014: final pay & pesangon per alasan terminasi.

- Tabel konfigurasi (bracket masa kerja + faktor alasan) ter-seed
  bawaan PP 35/2021 dan dapat diganti per tenant.
- Perhitungan: sisa gaji prorata hari kerja, UPH sisa cuti, pesangon &
  UPMK bracket x faktor, kompensasi PKWT, PPh final berlapis,
  potongan sisa pinjaman.
- Alur status draft -> finalized -> paid; satu final pay aktif per
  employment; izin payroll digerbang RBP.
"""

from __future__ import annotations

from datetime import date

from app.models import CompInfo, JobInfo, User
from app.services import effective_dating as ed
from tests.conftest import login_headers


def _admin(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def _beri_gaji(db, ctx, employment, gaji_pokok, tunjangan=0, sejak=date(2024, 1, 1)):
    admin = db.query(User).filter_by(email="admin_a@x.id").one()
    ed.insert_record(
        db=db, tenant_id=ctx["ta"].id, model=CompInfo,
        identity_field="employment_id", identity_value=employment.id,
        valid_from=sejak,
        values={"pay_group": "Bulanan",
                "components": {"gaji_pokok": gaji_pokok,
                               "tunjangan_tetap": tunjangan},
                "ptkp": "TK/0"},
        event="hire", event_reason="Penetapan gaji awal",
        created_by=admin.id, event_applies_to="lifecycle",
    )
    db.commit()


def _nonaktif(db, ctx, employment_id):
    """Employment pada ctx yang sudah berstatus terminated."""
    from app.models import Employment

    return db.query(Employment).filter_by(
        tenant_id=ctx["ta"].id, status="terminated",
    ).all()


def _terminasi(client, h, employment_id, ctx, tanggal, alasan="PHK"):
    """Terminasi lewat API job-info (menutup employment + end_date)."""
    r = client.post(
        "/api/v1/job-info",
        json={
            "employment_id": str(employment_id),
            "valid_from": tanggal,
            "job_id": str(ctx["job_stf"].id),
            "org_unit_id": str(ctx["ou"].id),
            "location_id": str(ctx["loc_b"].id),
            "event": "termination",
            "event_reason": alasan,
            "reason": "uji final pay",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r


def _setup_terminated(client, db, ctx, *, nama_idx=0, tanggal="2026-06-15",
                      alasan="PHK", gaji=10_000_000):
    """Ambil employment fixture, beri gaji, lalu terminasikan."""
    from app.models import Employment, Person

    h = _admin(client)
    emps = (
        db.query(Employment)
        .filter_by(tenant_id=ctx["ta"].id, status="active")
        .order_by(Employment.start_date)
        .all()
    )
    emp = emps[nama_idx]
    _beri_gaji(db, ctx, emp, gaji)
    person = db.get(Person, emp.person_id)
    _terminasi(client, h, emp.id, ctx, tanggal, alasan)
    db.expire_all()
    emp = db.get(Employment, emp.id)
    assert emp.status == "terminated"
    assert emp.end_date is not None
    return h, emp, person


def test_config_bawaan_pp35(client, ctx):
    db = ctx["db"]
    h = _admin(client)
    r = client.get("/api/v1/final-pay/config", headers=h)
    assert r.status_code == 200, r.text
    cfg = r.json()
    pes = [b for b in cfg["brackets"] if b["component"] == "pesangon"]
    upmk = [b for b in cfg["brackets"] if b["component"] == "upmk"]
    assert len(pes) == 9 and pes[-1]["months"] == 9
    assert len(upmk) == 8 and upmk[-1]["months"] == 10
    reasons = {f["reason"]: f for f in cfg["reason_factors"]}
    assert reasons["Pengunduran diri"]["pesangon_factor"] == 0
    assert reasons["Kontrak berakhir"]["pkwt_compensation"] is True
    assert reasons["PHK"]["pesangon_factor"] == 1


def test_config_dapat_diganti_dan_berlaku(client, ctx):
    db = ctx["db"]
    h, emp, _ = _setup_terminated(client, db, ctx, tanggal="2026-06-15")
    r = client.get("/api/v1/final-pay/config", headers=h)
    cfg = r.json()
    # Ubah faktor PHK menjadi 0,5 (efisiensi merugi).
    for f in cfg["reason_factors"]:
        if f["reason"] == "PHK":
            f["pesangon_factor"] = 0.5
    put = client.put("/api/v1/final-pay/config", json=cfg, headers=h)
    assert put.status_code == 200, put.text
    pv = client.post(
        "/api/v1/final-pay/preview",
        json={"employment_id": str(emp.id)}, headers=h,
    )
    assert pv.status_code == 200, pv.text
    assert pv.json()["breakdown"]["pesangon_faktor"] == 0.5


def test_hitung_phk_masa_kerja_2_5_tahun(client, ctx):
    db = ctx["db"]
    # Mulai 2024-01-01 (fixture), terminasi 2026-06-15 -> ~2,45 tahun:
    # pesangon bracket 2-<3 = 3 bulan x 10 jt = 30 jt; UPMK 0 (<3 th).
    h, emp, person = _setup_terminated(client, db, ctx, tanggal="2026-06-15")
    pv = client.post(
        "/api/v1/final-pay/preview",
        json={"employment_id": str(emp.id)}, headers=h,
    )
    assert pv.status_code == 200, pv.text
    body = pv.json()
    assert body["person_name"] == person.full_name
    assert body["monthly_wage"] == 10_000_000
    bd = body["breakdown"]
    assert bd["pesangon_bulan"] == 3
    assert bd["pesangon"] == 30_000_000
    assert bd["upmk"] == 0
    assert bd["kompensasi_pkwt"] == 0
    # Sisa gaji Juni 2026: hari kerja 1-15 Juni = 11 dari 22 hari kerja.
    assert bd["hari_kerja_terpakai"] == 11
    assert bd["hari_kerja_sebulan"] == 22
    assert bd["sisa_gaji"] == 5_000_000
    # Pajak final: 35 jt bruto pesangon masuk lapisan 0 persen.
    assert body["tax_amount"] == 0
    assert body["gross_total"] == 35_000_000
    assert body["net_amount"] == 35_000_000


def test_resign_tanpa_pesangon(client, ctx):
    db = ctx["db"]
    h, emp, _ = _setup_terminated(
        client, db, ctx, nama_idx=1, tanggal="2026-06-15",
        alasan="Pengunduran diri",
    )
    pv = client.post(
        "/api/v1/final-pay/preview",
        json={"employment_id": str(emp.id)}, headers=h,
    )
    assert pv.status_code == 200, pv.text
    bd = pv.json()["breakdown"]
    assert bd["pesangon"] == 0 and bd["upmk"] == 0
    assert bd["uph_termasuk"] is True
    assert pv.json()["gross_total"] == bd["sisa_gaji"]


def test_pajak_final_berlapis(client, ctx):
    db = ctx["db"]
    # Gaji 40 jt, PHK, masa kerja ~2,45 th -> pesangon 3x40jt = 120 jt.
    # Pajak: 50jtx0 + 50jtx5 + 20jtx15 = 2,5jt + 3jt = 5,5 jt.
    h, emp, _ = _setup_terminated(
        client, db, ctx, nama_idx=2, tanggal="2026-06-15", gaji=40_000_000,
    )
    pv = client.post(
        "/api/v1/final-pay/preview",
        json={"employment_id": str(emp.id)}, headers=h,
    )
    assert pv.status_code == 200, pv.text
    body = pv.json()
    assert body["breakdown"]["pesangon"] == 120_000_000
    assert body["tax_amount"] == 5_500_000


def test_kompensasi_pkwt_kontrak_berakhir(client, ctx):
    db = ctx["db"]
    h, emp, _ = _setup_terminated(
        client, db, ctx, nama_idx=3, tanggal="2026-06-15",
        alasan="Kontrak berakhir",
    )
    pv = client.post(
        "/api/v1/final-pay/preview",
        json={"employment_id": str(emp.id)}, headers=h,
    )
    assert pv.status_code == 200, pv.text
    bd = pv.json()["breakdown"]
    assert bd["pesangon"] == 0 and bd["upmk"] == 0
    # masa kerja/12 x upah: ~2,45 th x 10 jt.
    assert 24_000_000 < bd["kompensasi_pkwt"] < 25_000_000


def test_alur_draft_final_paid_dan_anti_duplikat(client, ctx):
    db = ctx["db"]
    h, emp, _ = _setup_terminated(client, db, ctx, tanggal="2026-06-15")
    r = client.post(
        "/api/v1/final-pay",
        json={"employment_id": str(emp.id),
              "adjustments": [{"label": "Uang pisah", "amount": 1_000_000}]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    fp_id = r.json()["id"]
    assert r.json()["status"] == "draft"
    assert r.json()["gross_total"] == 36_000_000

    dup = client.post(
        "/api/v1/final-pay", json={"employment_id": str(emp.id)}, headers=h,
    )
    assert dup.status_code == 409

    pay_early = client.post(f"/api/v1/final-pay/{fp_id}/pay", headers=h)
    assert pay_early.status_code == 409

    fin = client.post(f"/api/v1/final-pay/{fp_id}/finalize", headers=h)
    assert fin.status_code == 200, fin.text
    assert fin.json()["status"] == "finalized"

    delete_locked = client.delete(f"/api/v1/final-pay/{fp_id}", headers=h)
    assert delete_locked.status_code == 409

    paid = client.post(f"/api/v1/final-pay/{fp_id}/pay", headers=h)
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"
    assert paid.json()["paid_at"] is not None

    lst = client.get("/api/v1/final-pay", headers=h)
    assert any(x["id"] == fp_id for x in lst.json())
    cands = client.get("/api/v1/final-pay/candidates", headers=h)
    mine = [c for c in cands.json() if c["employment_id"] == str(emp.id)]
    assert mine and mine[0]["has_final_pay"] is True


def test_hapus_draft_lalu_buat_ulang(client, ctx):
    db = ctx["db"]
    h, emp, _ = _setup_terminated(client, db, ctx, tanggal="2026-06-15")
    r = client.post(
        "/api/v1/final-pay", json={"employment_id": str(emp.id)}, headers=h,
    )
    fp_id = r.json()["id"]
    d = client.delete(f"/api/v1/final-pay/{fp_id}", headers=h)
    assert d.status_code == 204
    again = client.post(
        "/api/v1/final-pay", json={"employment_id": str(emp.id)}, headers=h,
    )
    assert again.status_code == 201


def test_izin_ditolak_tanpa_hak_payroll(client, ctx):
    db = ctx["db"]
    # u_none hanya punya role Empty (tanpa izin) pada tenant yang sama.
    h_none = login_headers(client, "hashiru", "u_none@x.id")
    r = client.get("/api/v1/final-pay/config", headers=h_none)
    assert r.status_code == 403
