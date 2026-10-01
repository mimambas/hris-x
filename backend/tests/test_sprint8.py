"""Sprint 8 (PRD 24.2 S8, Bagian 11.5): klaim & pinjaman karyawan.

Demo goal PRD: "Pengajuan klaim kesehatan sampai reimbursement tercatat."
"""

from datetime import date

from sqlalchemy import select

from app.models import FieldPermission, PermissionRole
from app.services import claims as claims_service
from app.services import loans as loans_service
from app.services import payroll as payroll_service

from .conftest import PASSWORD, login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


_NIK_SEQ = [400]


def _nik():
    _NIK_SEQ[0] += 1
    return f"9000{_NIK_SEQ[0]:012d}"


def _mk_employee(client, h, ctx, nama, gaji_pokok=8_000_000,
                 tunjangan_tetap=2_000_000, job="stf",
                 start="2024-01-01", manager_emp_id=None, bank="8210101999"):
    p = client.post("/api/v1/persons", headers=h, json={
        "nik": _nik(), "full_name": nama, "bank_name": "BCA",
        "bank_account_no": bank, "reason": "uji"}).json()
    e = client.post("/api/v1/employments", headers=h, json={
        "person_id": p["id"], "legal_entity_id": str(ctx["le"].id),
        "start_date": start, "status": "active", "reason": "uji"}).json()
    job_id = ctx["job_mgr"].id if job == "mgr" else ctx["job_stf"].id
    payload = {"employment_id": e["id"], "valid_from": start,
               "job_id": str(job_id), "org_unit_id": str(ctx["ou"].id),
               "location_id": str(ctx["loc_b"].id),
               "event": "hire", "event_reason": "Rekrutmen reguler",
               "reason": "uji"}
    if manager_emp_id:
        payload["manager_employment_id"] = str(manager_emp_id)
    r = client.post("/api/v1/job-info", headers=h, json=payload)
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/comp-info", headers=h, json={
        "employment_id": e["id"], "valid_from": start, "pay_group": "Bulanan",
        "components": {"gaji_pokok": gaji_pokok,
                       "tunjangan_tetap": tunjangan_tetap},
        "event": "hire", "event_reason": "Penetapan gaji awal",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    return p, e


def _mk_user(ctx, email, person_id):
    import uuid as _uuid
    from app.core.security import hash_password
    from app.models import User
    db = ctx["db"]
    if isinstance(person_id, str):
        person_id = _uuid.UUID(person_id)
    u = User(tenant_id=ctx["ta"].id, email=email,
             password_hash=hash_password(PASSWORD),
             full_name=email.split("@")[0], person_id=person_id)
    db.add(u)
    db.commit()
    return u


def _grant_claims(ctx):
    """Izin klaim/pinjaman untuk role Inserter & MgrRole (fixture tidak
    men-seed katalog klaim). Sekaligus isi rekening semua person agar
    payroll run bisa dikunci (pola test_sprint4._ctx_bank)."""
    from app.models import Person
    from sqlalchemy import update
    db, ta = ctx["db"], ctx["ta"]
    db.execute(
        update(Person)
        .where(Person.tenant_id == ta.id,
               Person.bank_account_no.is_(None))
        .values(bank_name="BCA", bank_account_no="9000000001")
    )
    db.commit()
    claims_service.seed_claim_types(db, ta.id)
    loans_service.get_loan_policy(db, ta.id)
    db.commit()
    r_ins = db.execute(select(PermissionRole).where(
        PermissionRole.tenant_id == ta.id,
        PermissionRole.name == "Inserter")).scalar_one()
    r_mgr = db.execute(select(PermissionRole).where(
        PermissionRole.tenant_id == ta.id,
        PermissionRole.name == "MgrRole")).scalar_one()
    db.add_all([
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="claim", field_name="*",
                        can_view=True, can_insert=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="claim_type", field_name="*",
                        can_view=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="claim", field_name="*",
                        can_view=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="claim_type", field_name="*",
                        can_view=True),
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="loan", field_name="*",
                        can_view=True, can_insert=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="loan_policy", field_name="*",
                        can_view=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="loan", field_name="*",
                        can_view=True),
        # Fix UAT 2026-10-01: cerminkan seed.py — role karyawan (Inserter)
        # butuh "document" view+insert agar bisa upload struk klaim (ESS),
        # manajer butuh view untuk persetujuan L1.
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="document", field_name="*",
                        can_view=True, can_insert=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="document", field_name="*",
                        can_view=True),
    ])
    db.commit()


def _manager_staff_setup(client, ctx):
    """Return (h_admin, h_mgr, h_staff, mgr_emp, staff_emp)."""
    import uuid as _uuid
    from app.models import Employment
    h = ah(client)
    _grant_claims(ctx)
    p_mgr, e_mgr = _mk_employee(client, h, ctx, "Manajer Klaim", job="mgr")
    _, e_staff = _mk_employee(client, h, ctx, "Staf Klaim",
                              manager_emp_id=e_mgr["id"])
    _mk_user(ctx, "mgr@klaim.id", p_mgr["id"])
    staff_person_id = ctx["db"].get(
        Employment, _uuid.UUID(e_staff["id"])).person_id
    _mk_user(ctx, "staff@klaim.id", staff_person_id)
    h_mgr = login_headers(client, "hashiru", "mgr@klaim.id")
    h_staff = login_headers(client, "hashiru", "staff@klaim.id")
    return h, h_mgr, h_staff, e_mgr, e_staff


def _claim_types(client, h):
    return {t["code"]: t["id"]
            for t in client.get("/api/v1/claims/types", headers=h).json()}


def _submit_claim(client, h, emp_id, claim_type_id, amount=1_500_000,
                  claim_date="2026-09-10", receipt="auto"):
    import uuid as _uuid
    if receipt == "auto":
        receipt = str(_uuid.uuid4())
    r = client.post("/api/v1/claims", headers=h, json={
        "employment_id": emp_id, "claim_type_id": claim_type_id,
        "amount": amount, "claim_date": claim_date,
        "description": "Uji klaim",
        "receipt_document_id": receipt})
    assert r.status_code == 201, r.text
    claim = r.json()
    r = client.post(f"/api/v1/claims/{claim['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _assign_comps(client, h, ctx, emp_id):
    """Assign gaji_pokok & tunjangan_tetap agar payroll run menghitung gaji."""
    from app.models import SalaryComponent, User
    db, ta = ctx["db"], ctx["ta"]
    admin = db.execute(select(User).where(
        User.tenant_id == ta.id, User.email == "admin_a@x.id")).scalar_one()
    payroll_service.seed_payroll_catalog(db, ta.id, created_by=admin.id)
    db.commit()
    comp_ids = {
        c.code: str(c.id)
        for c in db.execute(select(SalaryComponent).where(
            SalaryComponent.tenant_id == ta.id)).scalars().all()
        if c.code in ("gaji_pokok", "tunjangan_tetap")
    }
    for code, comp_id in comp_ids.items():
        r = client.post("/api/v1/payroll/assignments", headers=h, json={
            "employment_id": emp_id, "component_id": comp_id,
            "valid_from": "2024-01-01", "event": "salary_structure",
            "event_reason": "Komponen baru", "reason": "uji"})
        assert r.status_code == 201, r.text


def _run(client, h, period, **kw):
    r = client.post("/api/v1/payroll/runs", headers=h,
                    json={"period": period, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _lock(client, h, run_id):
    r = client.post(f"/api/v1/payroll/runs/{run_id}/lock", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ klaim: limit
def test_claim_limit_per_claim_ditolak(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Klaim Batas")
    ct = _claim_types(client, h)
    # klaim_kesehatan: plafon per pengajuan Rp2jt.
    r = client.post("/api/v1/claims", headers=h, json={
        "employment_id": e["id"], "claim_type_id": ct["klaim_kesehatan"],
        "amount": 2_500_000, "claim_date": "2026-09-10",
        "receipt_document_id": str(__import__("uuid").uuid4())})
    assert r.status_code == 422
    assert "plafon per pengajuan" in r.json()["detail"]


def test_claim_limit_tahunan_ditolak(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Klaim Tahunan")
    # Jenis khusus: per pengajuan 5jt, per tahun 5jt.
    r = client.post("/api/v1/claims/types", headers=h, json={
        "code": "klaim_tahunan_uji", "name": "Klaim Tahunan Uji",
        "limit_per_year": 5_000_000, "limit_per_claim": 5_000_000,
        "requires_receipt": False})
    assert r.status_code == 201, r.text
    ct_id = r.json()["id"]
    claim = _submit_claim(client, h, e["id"], ct_id, amount=3_000_000)
    assert claim["status"] == "submitted"
    r = client.post("/api/v1/claims", headers=h, json={
        "employment_id": e["id"], "claim_type_id": ct_id,
        "amount": 3_000_000, "claim_date": "2026-09-11"})
    assert r.status_code == 422
    assert "Plafon tahunan" in r.json()["detail"]


def test_claim_struk_wajib_bila_requires_receipt(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Klaim Struk")
    ct = _claim_types(client, h)
    r = client.post("/api/v1/claims", headers=h, json={
        "employment_id": e["id"], "claim_type_id": ct["klaim_kesehatan"],
        "amount": 1_000_000, "claim_date": "2026-09-10"})
    assert r.status_code == 201, r.text
    claim = r.json()
    r = client.post(f"/api/v1/claims/{claim['id']}/submit", headers=h)
    assert r.status_code == 422
    assert "struk" in r.json()["detail"].lower()


def test_claim_summary_sisa_plafon(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Klaim Ringkas")
    ct = _claim_types(client, h)
    _submit_claim(client, h, e["id"], ct["klaim_transport"],
                  amount=600_000, receipt=None)  # tanpa struk, tetap boleh
    r = client.get("/api/v1/claims/summary/yearly", headers=h,
                   params={"employment_id": e["id"], "year": 2026})
    assert r.status_code == 200, r.text
    rows = {row["claim_type_code"]: row for row in r.json()}
    # transport: 6jt/tahun, terpakai 600rb.
    assert rows["klaim_transport"]["used"] == 600_000
    assert rows["klaim_transport"]["remaining"] == 5_400_000


# ------------------------------------------------- klaim: alur approval
def test_claim_two_level_approval_flow(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    ct = _claim_types(client, h_staff)
    claim = _submit_claim(client, h_staff, e_staff["id"],
                          ct["klaim_kesehatan"])
    assert claim["status"] == "submitted"

    # Karyawan tidak bisa approve klaim sendiri.
    r = client.post(f"/api/v1/claims/{claim['id']}/approve-l1",
                    headers=h_staff, json={"reason": "coba"})
    assert r.status_code == 422

    # L1 oleh atasan langsung.
    r = client.post(f"/api/v1/claims/{claim['id']}/approve-l1",
                    headers=h_mgr, json={"reason": "Disetujui atasan"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved_l1"

    # L2 (final) tidak bisa sebelum L1 untuk klaim lain.
    claim2 = _submit_claim(client, h_staff, e_staff["id"],
                           ct["klaim_transport"], amount=500_000, receipt=None)
    r = client.post(f"/api/v1/claims/{claim2['id']}/approve", headers=h,
                    json={"reason": "coba"})
    assert r.status_code == 422

    # L2 oleh HR/admin.
    r = client.post(f"/api/v1/claims/{claim['id']}/approve", headers=h,
                    json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # Tandai dibayar (HR).
    r = client.post(f"/api/v1/claims/{claim['id']}/mark-paid", headers=h,
                    json={"payment_ref": "TRF-2026-001"})
    assert r.status_code == 200, r.text
    paid = r.json()
    assert paid["status"] == "paid"
    assert paid["payment_ref"] == "TRF-2026-001"

    # Jejak audit tercatat untuk tiap transisi.
    r = client.get("/api/v1/audit-logs", headers=h,
                   params={"object_type": "claim", "object_id": claim["id"],
                           "limit": 50})
    assert r.status_code == 200, r.text
    actions = [a["action"] for a in r.json()]
    for expected in ("create", "submit", "approve_l1", "approve",
                     "mark_paid"):
        assert expected in actions


def test_claim_reject_butuh_alasan(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    ct = _claim_types(client, h_staff)
    claim = _submit_claim(client, h_staff, e_staff["id"],
                          ct["klaim_kesehatan"])
    r = client.post(f"/api/v1/claims/{claim['id']}/approve-l1",
                    headers=h_mgr, json={"reason": "ok"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/claims/{claim['id']}/reject", headers=h,
                    json={"reason": ""})
    assert r.status_code == 422
    r = client.post(f"/api/v1/claims/{claim['id']}/reject", headers=h,
                    json={"reason": "Struk tidak jelas"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "Struk tidak jelas"


def test_claim_batalkan_kembalikan_plafon(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Klaim Batal")
    ct = _claim_types(client, h)
    claim = _submit_claim(client, h, e["id"], ct["klaim_transport"],
                          amount=1_000_000, receipt=None)
    r = client.post(f"/api/v1/claims/{claim['id']}/cancel", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    # Plafon kembali utuh setelah batal.
    r = client.get("/api/v1/claims/summary/yearly", headers=h,
                   params={"employment_id": e["id"], "year": 2026})
    rows = {row["claim_type_code"]: row for row in r.json()}
    assert rows["klaim_transport"]["used"] == 0


# ------------------------------------------------------------ pinjaman
def test_loan_policy_default_dan_update(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    r = client.get("/api/v1/loans/policy", headers=h)
    assert r.status_code == 200, r.text
    policy = r.json()
    assert float(policy["max_amount_multiplier"]) == 3.0
    assert policy["max_tenor_months"] == 24
    assert float(policy["default_interest_rate"]) == 0.0
    r = client.put("/api/v1/loans/policy", headers=h,
                   json={"max_tenor_months": 12})
    assert r.status_code == 200, r.text
    assert r.json()["max_tenor_months"] == 12


def _submit_loan(client, h, emp_id, amount=12_000_000, tenor=12):
    r = client.post("/api/v1/loans", headers=h, json={
        "employment_id": emp_id, "amount": amount,
        "tenor_months": tenor, "purpose": "Uji pinjaman"})
    assert r.status_code == 201, r.text
    loan = r.json()
    r = client.post(f"/api/v1/loans/{loan['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_loan_approve_hitung_angsuran_dan_batas(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Pinjam Uji",
                        gaji_pokok=8_000_000, tunjangan_tetap=2_000_000)
    loan = _submit_loan(client, h, e["id"], amount=12_000_000, tenor=12)
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h,
                    json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    loan = r.json()
    assert loan["status"] == "active"
    assert loan["total_payable"] == 12_000_000  # bunga 0%
    assert loan["monthly_installment"] == 1_000_000
    assert loan["remaining_total"] == 12_000_000


def test_loan_satu_aktif_per_karyawan(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Pinjam Ganda")
    loan = _submit_loan(client, h, e["id"], amount=5_000_000, tenor=12)
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text
    # Pinjaman kedua masih aktif -> 422 saat approve.
    loan2 = _submit_loan(client, h, e["id"], amount=3_000_000, tenor=6)
    r = client.post(f"/api/v1/loans/{loan2['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 422
    assert "masih punya pinjaman aktif" in r.json()["detail"]


def test_loan_submitted_memblokir_approve_pesan_tepat(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Pinjam Antre")
    loan1 = _submit_loan(client, h, e["id"], amount=5_000_000, tenor=12)
    loan2 = _submit_loan(client, h, e["id"], amount=3_000_000, tenor=6)
    # Belum ada yang disetujui; pemblokir berstatus submitted -> pesan
    # menyebut "menunggu persetujuan", bukan "lunasi dulu".
    r = client.post(f"/api/v1/loans/{loan2['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 422
    assert "menunggu persetujuan" in r.json()["detail"]
    # Yang pertama tetap bisa disetujui setelah yang kedua dibatalkan.
    r = client.post(f"/api/v1/loans/{loan2['id']}/cancel", headers=h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/loans/{loan1['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"


def test_loan_melebihi_maksimal_ditolak(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Pinjam Besar",
                        gaji_pokok=8_000_000, tunjangan_tetap=2_000_000)
    # 3x gaji = 30jt; ajukan 31jt.
    loan = _submit_loan(client, h, e["id"], amount=31_000_000, tenor=12)
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 422
    assert "melebihi batas" in r.json()["detail"]


def test_loan_bunga_flat_menambah_total(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Pinjam Bunga")
    r = client.post("/api/v1/loans", headers=h, json={
        "employment_id": e["id"], "amount": 12_000_000,
        "tenor_months": 12, "interest_rate": 0.06,
        "purpose": "Uji bunga"})
    assert r.status_code == 201, r.text
    loan_id = r.json()["id"]
    r = client.post(f"/api/v1/loans/{loan_id}/submit", headers=h)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/loans/{loan_id}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text
    loan = r.json()
    # Bunga flat 6%/tahun x 12/12 = 720rb.
    assert loan["total_payable"] == 12_720_000
    assert loan["monthly_installment"] == 12_720_000 // 12


# --------------------------------- integrasi payroll: reimbursement + cicilan
def test_reimbursement_masuk_run_non_pajak_dan_cicilan_dipotong(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Integrasi Uji")
    _assign_comps(client, h, ctx, e["id"])
    ct = _claim_types(client, h)

    # Klaim kesehatan 1,5jt: approve penuh (belum mark-paid).
    claim = _submit_claim(client, h, e["id"], ct["klaim_kesehatan"],
                          amount=1_500_000)
    r = client.post(f"/api/v1/claims/{claim['id']}/approve-l1", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/claims/{claim['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text

    # Pinjaman 12jt tenor 12 -> angsuran 1jt.
    loan = _submit_loan(client, h, e["id"], amount=12_000_000, tenor=12)
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text

    run = _run(client, h, "2026-09")
    r = client.get(f"/api/v1/payroll/runs/{run['id']}/lines", headers=h)
    assert r.status_code == 200, r.text
    lines = [l for l in r.json() if l["employment_id"] == e["id"]]
    assert len(lines) == 1
    line = lines[0]
    bd = line["breakdown"]
    assert bd["reimbursement"] == 1_500_000
    assert bd["cicilan_pinjaman"] == 1_000_000
    assert line["reimbursement_amount"] == 1_500_000
    # Reimbursement menambah take-home tapi tidak menambah PPh 21:
    # pph21 dihitung dari bruto kena pajak (gaji 10jt, bukan 11,5jt).
    expected_take_home = (line["gross"] + line["thr_amount"]
                          + line["retro_amount"] - line["total_deductions"]
                          - line["pph21"])
    assert line["take_home_pay"] == expected_take_home
    # Bruto termasuk reimbursement 1,5jt di atas gaji 10jt.
    assert line["gross"] == 10_000_000 + 1_500_000

    # Kunci: angsuran paid, sisa pinjaman berkurang, klaim tertaut ke run.
    _lock(client, h, run["id"])
    r = client.get(f"/api/v1/loans/{loan['id']}", headers=h)
    assert r.json()["remaining_total"] == 11_000_000
    r = client.get(f"/api/v1/loans/{loan['id']}/installments", headers=h)
    insts = r.json()
    assert len(insts) == 1
    assert insts[0]["period"] == "2026-09"
    assert insts[0]["status"] == "paid"
    assert insts[0]["payroll_run_id"] == run["id"]
    r = client.get(f"/api/v1/claims/{claim['id']}", headers=h)
    assert r.json()["payroll_run_id"] == run["id"]

    # Slip PDF tetap bisa dirender (baris reimbursement & cicilan).
    r = client.get(
        f"/api/v1/payroll/runs/{run['id']}/payslip/{e['id']}.pdf",
        headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert len(r.content) > 1000


def test_payoff_melunasi_pinjaman_di_run_berikutnya(client, ctx):
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Payoff Uji")
    _assign_comps(client, h, ctx, e["id"])
    loan = _submit_loan(client, h, e["id"], amount=6_000_000, tenor=6)
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text

    # Pelunasan dipercepat: sisa 6jt menjadi potongan di periode berjalan
    # (periode = bulan hari ini; tanpa run sebelumnya _next_open_period
    # memakai date.today() — test ini tidak boleh hardcode bulan).
    # (cicilan 12jt > gaji akan ditolak lock karena take-home negatif).
    r = client.post(f"/api/v1/loans/{loan['id']}/payoff", headers=h)
    assert r.status_code == 201, r.text
    inst = r.json()
    assert inst["kind"] == "payoff"
    assert inst["amount"] == 6_000_000
    periode = date.today().strftime("%Y-%m")
    assert inst["period"] == periode

    run = _run(client, h, periode)
    r = client.get(f"/api/v1/payroll/runs/{run['id']}/lines", headers=h)
    lines = [l for l in r.json() if l["employment_id"] == e["id"]]
    assert lines[0]["breakdown"]["cicilan_pinjaman"] == 6_000_000
    _lock(client, h, run["id"])
    r = client.get(f"/api/v1/loans/{loan['id']}", headers=h)
    loan = r.json()
    assert loan["status"] == "completed"
    assert loan["remaining_total"] == 0
    assert loan["paid_off_at"] is not None


def test_installment_idempoten_satu_per_periode(client, ctx):
    """Dua run untuk periode sama mustahil; cicilan lazy tidak ganda."""
    h = ah(client)
    _grant_claims(ctx)
    _, e = _mk_employee(client, h, ctx, "Idempoten Uji")
    _assign_comps(client, h, ctx, e["id"])
    loan = _submit_loan(client, h, e["id"], amount=6_000_000, tenor=6)
    r = client.post(f"/api/v1/loans/{loan['id']}/approve", headers=h,
                    json={"reason": "ok"})
    assert r.status_code == 200, r.text
    run = _run(client, h, "2026-09")
    # Run kedua untuk periode sama ditolak (disiplin periode).
    r = client.post("/api/v1/payroll/runs", headers=h,
                    json={"period": "2026-09"})
    assert r.status_code == 422
    _lock(client, h, run["id"])
    r = client.get(f"/api/v1/loans/{loan['id']}/installments", headers=h)
    assert len(r.json()) == 1


# ------------------------------------------------- isolasi tenant & RLS
def test_klaim_pinjaman_isolasi_tenant(client, ctx):
    """Klaim/pinjaman tenant A tak terlihat dari tenant B (level aplikasi)."""
    from app.models import Claim, Loan
    db, ta, tb = ctx["db"], ctx["ta"], ctx["tb"]
    n_a = db.execute(select(Claim).where(Claim.tenant_id == ta.id)).all()
    n_b = db.execute(select(Claim).where(Claim.tenant_id == tb.id)).all()
    n_la = db.execute(select(Loan).where(Loan.tenant_id == ta.id)).all()
    assert n_a is not None and n_b is not None and n_la is not None
    # Tenant B tidak punya claim types seed -> daftar kosong.
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "acme", "email": "admin_b@x.id",
        "password": PASSWORD})
    assert r.status_code == 200, r.text
    h_b = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/api/v1/claims/types", headers=h_b)
    # superadmin tenant B tanpa grant -> 403/404; yang penting bukan data A.
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert r.json() == []


def test_rls_migration_mencakup_tabel_klaim_pinjaman():
    from pathlib import Path
    sql = (Path(__file__).parent.parent / "migrations"
           / "001_rls.sql").read_text()
    for tabel in ("claim_types", "claims", "tenant_loan_policies",
                  "loans", "loan_installments"):
        assert tabel in sql


# --------------------------------- regresi UAT 2026-10-01: izin dokumen
def test_karyawan_upload_struk_lalu_ajukan_klaim(client, ctx):
    """Regresi UAT 2026-10-01: alur ESS klaim (upload struk -> ajukan ->
    submit) gagal total dengan 403 "Izin 'insert' pada 'document' ditolak"
    karena role karyawan tak punya izin document insert di seed.
    Karyawan wajib bisa upload struk miliknya sendiri."""
    h, h_mgr, h_staff, e_mgr, e_staff = _manager_staff_setup(client, ctx)
    types = _claim_types(client, h)
    png = b"\x89PNG\r\n\x1a\n-contoh-struk"
    r = client.post(
        "/api/v1/documents", headers=h_staff,
        data={"doc_type": "lain", "employment_id": e_staff["id"],
              "notes": "Struk klaim"},
        files={"file": ("struk.png", png, "image/png")},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    # Struk terpasang -> klaim bisa diajukan & disubmit (draft -> submitted).
    claim = _submit_claim(client, h_staff, e_staff["id"], types["klaim_kesehatan"],
                          amount=1_500_000, receipt=doc_id)
    assert claim["status"] == "submitted"
    assert claim["receipt_document_id"] == doc_id
    # Manajer bisa melihat daftar dokumen (untuk verifikasi struk saat L1).
    r = client.get("/api/v1/documents",
                   params={"employment_id": e_staff["id"]}, headers=h_mgr)
    assert r.status_code == 200, r.text
    assert any(d["id"] == doc_id for d in r.json())


def test_seed_memberi_izin_document_untuk_alur_klaim():
    """Regresi UAT 2026-10-01 (statis, pola test_channel_literal_muat_di_kolom_db):
    seed.py wajib memberi izin 'document' ke role Karyawan (view+insert,
    untuk upload struk) dan Manajer (view, untuk L1). Tanpa ini tenant baru
    mengulang bug 403 pada pengajuan klaim."""
    import pathlib
    import re
    seed = (pathlib.Path(__file__).resolve().parent.parent / "seed.py").read_text()
    m_emp = re.search(
        r'grant\(role_emp,\s*"document"([^)]*)\)', seed)
    assert m_emp, "seed.py: grant document untuk role_emp tidak ditemukan"
    assert "can_insert=True" in m_emp.group(1), \
        "seed.py: role Karyawan wajib can_insert=True pada 'document'"
    assert "can_view=True" in m_emp.group(1), \
        "seed.py: role Karyawan wajib can_view=True pada 'document'"
    m_mgr = re.search(
        r'grant\(role_mgr,\s*"document"([^)]*)\)', seed)
    assert m_mgr, "seed.py: grant document untuk role_mgr tidak ditemukan"
    assert "can_view=True" in m_mgr.group(1), \
        "seed.py: role Manajer wajib can_view=True pada 'document'"
