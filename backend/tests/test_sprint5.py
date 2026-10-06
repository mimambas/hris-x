"""Sprint 5 (PRD 24.2 S5, Bagian 10): shift, absensi, cuti multi-level, lembur.

Demo goal PRD: cuti multi-level end-to-end lewat API.
"""

from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.models import Employment, FieldPermission, PermissionRole, User
from app.services import attendance as att_service

from .conftest import PASSWORD, login_headers


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


_NIK_SEQ = [300]


def _nik():
    _NIK_SEQ[0] += 1
    return f"8000{_NIK_SEQ[0]:012d}"


def _mk_employee(client, h, ctx, nama, job="stf", start="2024-01-01",
                 manager_emp_id=None):
    p = client.post("/api/v1/persons", headers=h, json={
        "nik": _nik(), "full_name": nama, "reason": "uji"}).json()
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
    return p, e


def _mk_user(ctx, email, person_id):
    import uuid as _uuid
    db = ctx["db"]
    if isinstance(person_id, str):
        person_id = _uuid.UUID(person_id)
    u = User(tenant_id=ctx["ta"].id, email=email,
             password_hash=hash_password(PASSWORD),
             full_name=email.split("@")[0], person_id=person_id)
    db.add(u)
    db.commit()
    return u


def _grant_ess(ctx):
    """Izin self-service cuti/lembur/absensi untuk role Inserter & MgrRole,
    plus seed jenis cuti & tarif lembur (fixture tidak men-seed katalog)."""
    from app.services import leave as leave_service
    from app.services import overtime as ot_service

    db, ta = ctx["db"], ctx["ta"]
    leave_service.seed_leave_types(db, ta.id)
    ot_service.seed_overtime_rate(db, ta.id)
    db.commit()
    r_ins = db.execute(select(PermissionRole).where(
        PermissionRole.tenant_id == ta.id,
        PermissionRole.name == "Inserter")).scalar_one()
    r_mgr = db.execute(select(PermissionRole).where(
        PermissionRole.tenant_id == ta.id,
        PermissionRole.name == "MgrRole")).scalar_one()
    db.add_all([
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="leave_request", field_name="*",
                        can_view=True, can_insert=True),
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="attendance", field_name="*",
                        can_view=True, can_insert=True),
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="overtime_request", field_name="*",
                        can_view=True, can_insert=True),
        FieldPermission(tenant_id=ta.id, role_id=r_ins.id,
                        object_name="leave_type", field_name="*",
                        can_view=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="leave_request", field_name="*",
                        can_view=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="overtime_request", field_name="*",
                        can_view=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="attendance", field_name="*",
                        can_view=True, can_correct=True),
        FieldPermission(tenant_id=ta.id, role_id=r_mgr.id,
                        object_name="leave_type", field_name="*",
                        can_view=True),
    ])
    db.commit()


def _seed_shifts(ctx):
    """Seed 3 shift standar; kembalikan {code: id}."""
    from app.models import Shift
    db = ctx["db"]
    att_service.seed_shifts(db, ctx["ta"].id)
    db.commit()
    rows = db.execute(select(Shift).where(
        Shift.tenant_id == ctx["ta"].id)).scalars().all()
    return {s.code: str(s.id) for s in rows}


def _checkin(client, h, emp_id, at, channel="api"):
    return client.post("/api/v1/attendance/check-in", headers=h, json={
        "employment_id": str(emp_id), "at": at, "channel": channel})


def _checkout(client, h, emp_id, at):
    return client.post("/api/v1/attendance/check-out", headers=h, json={
        "employment_id": str(emp_id), "at": at})


def _submit_leave(client, h, emp_id, start, end, code="cuti_tahunan"):
    lt = {t["code"]: t["id"]
          for t in client.get("/api/v1/leave/types", headers=h).json()}
    r = client.post("/api/v1/leave/requests", headers=h, json={
        "employment_id": str(emp_id), "leave_type_id": lt[code],
        "start_date": start, "end_date": end, "reason": "Uji cuti"})
    assert r.status_code == 201, r.text
    req = r.json()
    r = client.post(f"/api/v1/leave/requests/{req['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _balances(client, h, emp_id, year=2026):
    r = client.get("/api/v1/leave/balances", headers=h,
                   params={"employment_id": str(emp_id), "year": year})
    assert r.status_code == 200, r.text
    return {row["leave_type_code"]: row for row in r.json()}


# ---------------------------------------------------------------- absensi

def test_checkin_late_detected(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Absen Uji")
    r = client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    assert r.status_code == 201, r.text
    r = _checkin(client, h, e["id"], "2026-11-02T08:20:00")
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["status"] == "late"
    assert rec["late_minutes"] == 5  # shift 08:00 + toleransi 15 mnt


def test_checkout_early_leave(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Absen Pulang")
    client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    assert _checkin(client, h, e["id"], "2026-11-02T07:55:00").status_code == 201
    r = _checkout(client, h, e["id"], "2026-11-02T16:00:00")
    assert r.status_code == 200, r.text
    assert r.json()["early_leave_minutes"] == 60  # shift s.d. 17:00


def test_shift_overlap_rejected(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Shift Ganda")
    payload = {"employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
               "valid_from": "2024-01-01", "reason": "uji"}
    assert client.post("/api/v1/shift-assignments", headers=h,
                       json=payload).status_code == 201
    r = client.post("/api/v1/shift-assignments", headers=h, json=payload)
    assert r.status_code == 422  # periode tumpang tindih


def test_shift_assignment_dapat_diakhiri_lalu_diganti(client, ctx):
    """Skenario EXP-012: akhiri penugasan terbuka, tugaskan pola baru.

    Sebelum endpoint PATCH ini ada, alur ini hanya bisa lewat SQL.
    """
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Ganti Pola")
    shifts = _seed_shifts(ctx)
    r = client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": shifts["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    assert r.status_code == 201, r.text
    asg = r.json()
    url = f"/api/v1/shift-assignments/{asg['id']}"
    r = client.patch(url, headers=h, json={
        "valid_to": "2023-01-01", "reason": "uji"})
    assert r.status_code == 422  # sebelum tanggal mulai
    r = client.patch(url, headers=h, json={
        "valid_to": "2026-10-05", "reason": "Ganti pola shift"})
    assert r.status_code == 200, r.text
    assert r.json()["valid_to"] == "2026-10-05"
    r = client.get("/api/v1/shift-assignments", headers=h,
                   params={"employment_id": e["id"]})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["valid_to"] == "2026-10-05"
    r = client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": shifts["siang"],
        "valid_from": "2026-10-06", "reason": "uji"})
    assert r.status_code == 201, r.text
    r = client.patch(url, headers=h, json={
        "valid_to": "2026-10-05", "reason": "uji"})
    assert r.status_code == 422  # harus lebih awal dari akhir saat ini


def test_correct_requires_reason_and_versions(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Koreksi Uji")
    client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    r = _checkin(client, h, e["id"], "2026-11-02T08:20:00")
    assert r.json()["late_minutes"] == 5
    rec_id = r.json()["id"]
    r = client.post(f"/api/v1/attendance/{rec_id}/correct", headers=h, json={
        "check_in": "2026-11-02T08:05:00", "reason": ""})
    assert r.status_code == 422  # alasan wajib
    r = client.post(f"/api/v1/attendance/{rec_id}/correct", headers=h, json={
        "check_in": "2026-11-02T08:05:00",
        "reason": "Salah pencet tombol check-in"})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["version"] == 2
    assert new["late_minutes"] == 0  # 08:05 masih dalam toleransi 15 mnt
    # Versi lama tetap tersimpan dan tidak current.
    rows = client.get("/api/v1/attendance/records", headers=h, params={
        "employment_id": e["id"], "date_from": "2026-11-02",
        "date_to": "2026-11-02"}).json()
    assert len(rows) == 1 and rows[0]["version"] == 2


def test_correct_partial_with_aware_datetimes_like_postgres(client, ctx):
    """Regresi Defect 2 UAT: di Postgres, check_in/check_out terbaca sebagai
    datetime aware (kolom timestamptz), sedangkan jam shift naive. Koreksi
    parsial (hanya alasan, atau hanya salah satu jam) tidak boleh TypeError
    (yang di staging menjadi 500 + pesan "Tidak dapat terhubung ke server")."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models import AttendanceRecord

    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Koreksi Aware Uji")
    client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    r = _checkin(client, h, e["id"], "2026-11-03T08:10:00")
    assert r.status_code == 201, r.text
    r = _checkout(client, h, e["id"], "2026-11-03T17:05:00")
    assert r.status_code == 200, r.text
    rec_id = _uuid.UUID(r.json()["id"])

    db = ctx["db"]
    # Simulasikan pembacaan Postgres: kolom timestamptz -> aware.
    rec = db.get(AttendanceRecord, rec_id)
    rec.check_in = rec.check_in.replace(tzinfo=timezone.utc)
    rec.check_out = rec.check_out.replace(tzinfo=timezone.utc)
    db.flush()

    # Koreksi hanya alasan: jam diambil dari record lama (aware).
    new = att_service.correct_record(
        db=db, tenant_id=ctx["ta"].id, record_id=rec_id,
        reason="Koreksi alasan saja")
    assert new.version == 2
    assert new.check_in == datetime(2026, 11, 3, 8, 10)
    assert new.late_minutes == 0
    db.commit()

    # Koreksi hanya check_out: check_in diambil dari versi sebelumnya.
    new2 = att_service.correct_record(
        db=db, tenant_id=ctx["ta"].id, record_id=new.id,
        check_out=datetime(2026, 11, 3, 16, 30), reason="Pulang cepat")
    assert new2.version == 3
    assert new2.check_in == datetime(2026, 11, 3, 8, 10)
    assert new2.early_leave_minutes == 30
    db.commit()


def test_summary_counts_present_late_absent(client, ctx):
    h = ah(client)
    _, e = _mk_employee(client, h, ctx, "Rekap Uji")
    client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    # Hadir tepat waktu 2 hari, telat 1 hari, mangkir 1 hari (4–5, 9–10 Nov).
    for _at in ("2026-11-04T07:50:00", "2026-11-05T07:55:00",
                "2026-11-09T08:30:00"):
        _r = _checkin(client, h, e["id"], _at)
        assert _r.status_code == 201, (_at, _r.text)
    r = client.get("/api/v1/attendance/summary", headers=h, params={
        "employment_id": e["id"], "period": "2026-11"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["present"] == 2  # 4 & 5 Nov tepat waktu
    assert s["late"] == 1     # 9 Nov telat — tetap dihitung hadir untuk payroll
    # November 2026: 21 hari kerja → mangkir 18.
    assert s["absent"] == 18


# ---------------------------------------------------------------- cuti

def _manager_staff_setup(client, ctx):
    """Return (h_admin, h_mgr, h_staff, mgr_emp, staff_emp)."""
    import uuid as _uuid

    from app.models import Employment

    h = ah(client)
    _grant_ess(ctx)
    p_mgr, e_mgr = _mk_employee(client, h, ctx, "Manajer Cuti", job="mgr")
    _, e_staff = _mk_employee(client, h, ctx, "Staf Cuti",
                              manager_emp_id=e_mgr["id"])
    _mk_user(ctx, "mgr@cuti.id", p_mgr["id"])
    staff_person_id = ctx["db"].get(
        Employment, _uuid.UUID(e_staff["id"])).person_id
    _mk_user(ctx, "staff@cuti.id", staff_person_id)
    h_mgr = login_headers(client, "hashiru", "mgr@cuti.id")
    h_staff = login_headers(client, "hashiru", "staff@cuti.id")
    return h, h_mgr, h_staff, e_mgr, e_staff


def test_leave_two_level_approval_flow(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    req = _submit_leave(client, h_staff, e_staff["id"],
                        "2026-11-09", "2026-11-11")
    assert req["status"] == "submitted"
    assert req["days"] == 3  # Senin–Rabu, tanpa libur

    # L2 (HR/admin) tidak bisa approve sebelum L1.
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l2",
                    headers=h, json={"reason": "ok"})
    assert r.status_code == 422

    # L1 oleh manajer langsung.
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l1",
                    headers=h_mgr, json={"reason": "Disetujui atasan"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved_l1"

    # L2 oleh HR/admin: saldo terpotong saat final.
    before = _balances(client, h, e_staff["id"])["cuti_tahunan"]["remaining"]
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l2",
                    headers=h, json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    after = _balances(client, h, e_staff["id"])["cuti_tahunan"]["remaining"]
    assert after == before - 3


def test_leave_l1_only_by_direct_manager(client, ctx):
    h, h_mgr, h_staff, e_mgr, e_staff = _manager_staff_setup(client, ctx)
    # Karyawan lain (bukan atasan) mencoba approve L1.
    _, e_other = _mk_employee(client, h, ctx, "Staf Lain",
                              manager_emp_id=e_mgr["id"])
    import uuid as _uuid

    from app.models import Employment
    e_row = ctx["db"].get(Employment, _uuid.UUID(e_other["id"]))
    _mk_user(ctx, "other@cuti.id", e_row.person_id)
    h_other = login_headers(client, "hashiru", "other@cuti.id")

    req = _submit_leave(client, h_staff, e_staff["id"],
                        "2026-11-16", "2026-11-16")
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l1",
                    headers=h_other, json={"reason": "coba"})
    assert r.status_code == 422  # bukan atasan langsung


def test_leave_exceeds_balance_rejected(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    bal = _balances(client, h, e_staff["id"])["cuti_tahunan"]["remaining"]
    assert bal == 12
    # Longgarkan batas berurutan agar uji saldo murni (bukan batas policy).
    r = client.put("/api/v1/leave/policy", headers=h, json={
        "max_consecutive_days": 40, "reason": "uji"})
    assert r.status_code == 200, r.text
    # Minta 30 hari kerja > saldo 12 → 422 saat submit.
    lt = {t["code"]: t["id"]
          for t in client.get("/api/v1/leave/types", headers=h).json()}
    r = client.post("/api/v1/leave/requests", headers=h_staff, json={
        "employment_id": str(e_staff["id"]), "leave_type_id": lt["cuti_tahunan"],
        "start_date": "2026-11-02", "end_date": "2026-12-15",
        "reason": "kebanyakan"})
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    r = client.post(f"/api/v1/leave/requests/{req_id}/submit", headers=h_staff)
    assert r.status_code == 422
    assert "saldo" in r.json()["detail"].lower()


def test_cancel_before_start_refunds_balance(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    req = _submit_leave(client, h_staff, e_staff["id"],
                        "2026-11-09", "2026-11-10")
    client.post(f"/api/v1/leave/requests/{req['id']}/approve-l1",
                headers=h_mgr, json={"reason": "ok"})
    client.post(f"/api/v1/leave/requests/{req['id']}/approve-l2",
                headers=h, json={"reason": "ok"})
    before = _balances(client, h, e_staff["id"])["cuti_tahunan"]["remaining"]
    r = client.post(f"/api/v1/leave/requests/{req['id']}/cancel",
                    headers=h_staff, json={"reason": "batal"})
    assert r.status_code == 200, r.text
    after = _balances(client, h, e_staff["id"])["cuti_tahunan"]["remaining"]
    assert after == before + 2  # saldo dikembalikan


def test_mass_leave_deducts_balance(client, ctx):
    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_employee(client, h, ctx, "Cuti Bersama Uji")
    before = _balances(client, h, e["id"])["cuti_tahunan"]["remaining"]
    r = client.post("/api/v1/holidays", headers=h, json={
        "date": "2026-12-24", "name": "Cuti bersama Natal",
        "is_cuti_bersama": True})
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    r = client.post(f"/api/v1/holidays/{hid}/apply-mass-leave", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deducted"] >= 1
    assert body["holiday"]["mass_leave_applied"] is True
    after = _balances(client, h, e["id"])["cuti_tahunan"]["remaining"]
    assert after == before - 1
    # Idempotent: panggilan kedua tidak memotong lagi.
    r = client.post(f"/api/v1/holidays/{hid}/apply-mass-leave", headers=h)
    assert r.json()["deducted"] == 0
    again = _balances(client, h, e["id"])["cuti_tahunan"]["remaining"]
    assert again == after


def test_accrual_prorata_join_july(client, ctx):
    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_employee(client, h, ctx, "Prorata Uji", start="2026-07-01")
    bal = _balances(client, h, e["id"])["cuti_tahunan"]
    # Gabung Juli → 6 bulan tersisa → 12 × 6/12 = 6 hari.
    assert bal["entitled"] == 6
    assert bal["remaining"] == 6


def test_leave_reject_records_reason(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    req = _submit_leave(client, h_staff, e_staff["id"],
                        "2026-11-09", "2026-11-09")
    r = client.post(f"/api/v1/leave/requests/{req['id']}/reject",
                    headers=h_mgr, json={"reason": "Proyek deadline"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "Proyek deadline"


# ---------------------------------------------------------------- lembur

def _mk_component(client, h, name, code, kind="earning", calc_type="fixed",
                  amount_or_formula="0"):
    r = client.post("/api/v1/payroll/components", headers=h, json={
        "name": name, "code": code, "kind": kind, "calc_type": calc_type,
        "amount_or_formula": amount_or_formula, "valid_from": "2024-01-01",
        "event": "salary_structure", "event_reason": "Komponen baru",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    return r.json()


def _mk_with_pay(client, h, ctx, nama, gaji_pokok, start="2024-01-01"):
    """Karyawan + 4 komponen Sprint 5 (formula sama dengan seed produksi)."""
    p, e = _mk_employee(client, h, ctx, nama, start=start)
    comps = {
        "gaji_pokok": _mk_component(client, h, "Gaji Pokok", "gaji_pokok"),
        "uang_makan": _mk_component(client, h, "Uang Makan", "uang_makan",
                                    calc_type="formula",
                                    amount_or_formula="hari_hadir * 50000"),
        "lembur": _mk_component(client, h, "Upah Lembur", "lembur",
                                calc_type="formula",
                                amount_or_formula=(
                                    "jam_lembur * upah_per_jam + upah_lembur")),
        "potongan_mangkir": _mk_component(
            client, h, "Potongan Mangkir", "potongan_mangkir",
            kind="deduction", calc_type="formula",
            amount_or_formula="hari_mangkir * (gaji / 25) "
                             "* potongan_mangkir_aktif"),
    }
    r = client.post("/api/v1/comp-info", headers=h, json={
        "employment_id": e["id"], "valid_from": start, "pay_group": "Bulanan",
        "components": {"gaji_pokok": gaji_pokok, "uang_makan": 0,
                       "lembur": 0, "potongan_mangkir": 0},
        "event": "hire", "event_reason": "Penetapan gaji awal",
        "reason": "uji"})
    assert r.status_code == 201, r.text
    for name in ("gaji_pokok", "uang_makan", "lembur", "potongan_mangkir"):
        r = client.post("/api/v1/payroll/assignments", headers=h, json={
            "employment_id": e["id"], "component_id": comps[name]["id"],
            "valid_from": start, "event": "salary_structure",
            "event_reason": "Komponen baru", "reason": "uji"})
        assert r.status_code == 201, r.text
    return p, e


def _submit_overtime(client, h, emp_id, day, start_t, end_t):
    r = client.post("/api/v1/overtime/requests", headers=h, json={
        "employment_id": str(emp_id), "date": day,
        "start_time": start_t, "end_time": end_t, "reason": "Uji lembur"})
    assert r.status_code == 201, r.text
    req = r.json()
    r = client.post(f"/api/v1/overtime/requests/{req['id']}/submit", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_overtime_3_hours_pay_formula(client, ctx):
    """3 jam lembur = 1,5×1 jam + 2×2 jam; upah/jam = gaji/173 (PP 35/2021)."""
    import uuid as _uuid

    from app.services import overtime as ot_service

    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_with_pay(client, h, ctx, "Lembur Uji", 8_650_000)
    req = _submit_overtime(client, h, e["id"], "2026-08-03", "18:00", "21:00")
    assert req["hours"] == 3
    assert req["pay_amount"] == 0  # upah dikunci saat approval final
    # 8.650.000 / 173 = 50.000/jam → 50.000 × (1,5 + 2×2) = 275.000.
    pay = ot_service.compute_pay(ctx["db"], ctx["ta"].id,
                                 _uuid.UUID(e["id"]), date(2026, 8, 3), 3.0)
    assert pay == 275_000


def test_overtime_approved_flows_into_payroll(client, ctx):
    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_with_pay(client, h, ctx, "Lembur Gaji", 8_650_000)
    req = _submit_overtime(client, h, e["id"], "2026-08-03", "18:00", "21:00")
    # Approve 2 level oleh admin (superadmin boleh di kedua level).
    for ep in ("approve-l1", "approve-l2"):
        r = client.post(f"/api/v1/overtime/requests/{req['id']}/{ep}",
                        headers=h, json={"reason": "ok"})
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["pay_amount"] == 275_000  # dikunci saat L2
    r = client.post("/api/v1/payroll/runs", headers=h, json={
        "period": "2026-08", "notes": "uji"})
    assert r.status_code == 201, r.text
    run = r.json()
    lines = client.get(f"/api/v1/payroll/runs/{run['id']}/lines",
                       headers=h).json()
    line = next(l for l in lines if l["employment_id"] == e["id"])
    assert line["breakdown"]["lembur"] == 275_000
    snap = line["inputs_snapshot"]
    # upah_lembur = hasil merge otomatis lembur approved (ATT-010);
    # jam_lembur murni input manual saat create run.
    assert snap["upah_lembur"] == 275_000
    assert snap["jam_lembur"] == 0


def test_overtime_l2_before_l1_rejected(client, ctx):
    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_with_pay(client, h, ctx, "Lembur Urutan", 8_650_000)
    req = _submit_overtime(client, h, e["id"], "2026-08-03", "18:00", "20:00")
    r = client.post(f"/api/v1/overtime/requests/{req['id']}/approve-l2",
                    headers=h, json={"reason": "ok"})
    assert r.status_code == 422


def test_overtime_max_4_hours_per_day(client, ctx):
    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_with_pay(client, h, ctx, "Lembur Maks", 8_650_000)
    r = client.post("/api/v1/overtime/requests", headers=h, json={
        "employment_id": str(e["id"]), "date": "2026-08-03",
        "start_time": "17:00", "end_time": "23:00", "reason": "kepanjangan"})
    assert r.status_code == 422  # > 4 jam/hari ditolak


# ------------------------------------------- integrasi payroll: kehadiran

def test_uang_makan_and_mangkir_from_attendance(client, ctx):
    h = ah(client)
    _grant_ess(ctx)
    _, e = _mk_with_pay(client, h, ctx, "Hadir Uji", 8_650_000)
    client.post("/api/v1/shift-assignments", headers=h, json={
        "employment_id": e["id"], "shift_id": _seed_shifts(ctx)["pagi"],
        "valid_from": "2024-01-01", "reason": "uji"})
    for d in ("2026-08-03", "2026-08-04", "2026-08-05"):
        _checkin(client, h, e["id"], f"{d}T07:55:00")
    # Aktifkan potongan mangkir.
    r = client.put("/api/v1/attendance/policy", headers=h, json={
        "deduct_absent": True, "reason": "uji"})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/payroll/runs", headers=h, json={
        "period": "2026-08", "notes": "uji"})
    assert r.status_code == 201, r.text
    run = r.json()
    lines = client.get(f"/api/v1/payroll/runs/{run['id']}/lines",
                       headers=h).json()
    line = next(l for l in lines if l["employment_id"] == e["id"])
    brk = line["breakdown"]
    snap = line["inputs_snapshot"]
    assert snap["hari_hadir"] == 3
    assert brk["uang_makan"] == 3 * 50_000
    # Agustus 2026: 21 hari kerja → mangkir 18.
    assert snap["hari_mangkir"] == 18
    assert brk["potongan_mangkir"] == 18 * (8_650_000 / 25)


# --------------------------------- regresi otorisasi approval final (SEC-001)
#
# Manajer memegang izin "correct" pada leave_request/overtime_request/claim
# (dibutuhkan untuk antrean L1), tetapi approval FINAL hanya boleh oleh HR
# (superadmin atau pemegang payroll:correct). Regresi dari insiden staging
# 2026-10-01: manajer berhasil approve-l2 lembur.


def test_manager_cannot_l2_leave(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    req = _submit_leave(client, h_staff, e_staff["id"],
                        "2026-11-09", "2026-11-11")
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l1",
                    headers=h_mgr, json={"reason": "Disetujui atasan"})
    assert r.status_code == 200, r.text
    # Manajer (bukan HR) ditolak di L2.
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l2",
                    headers=h_mgr, json={"reason": "Coba L2"})
    assert r.status_code == 403, r.text
    # Status tidak berubah; HR/superadmin tetap bisa L2.
    r = client.post(f"/api/v1/leave/requests/{req['id']}/approve-l2",
                    headers=h, json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


def test_manager_cannot_l2_overtime(client, ctx):
    h, h_mgr, h_staff, _, e_staff = _manager_staff_setup(client, ctx)
    req = _submit_overtime(client, h_staff, e_staff["id"],
                           "2026-11-10", "18:00", "20:00")
    r = client.post(f"/api/v1/overtime/requests/{req['id']}/approve-l1",
                    headers=h_mgr, json={"reason": "Disetujui atasan"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/overtime/requests/{req['id']}/approve-l2",
                    headers=h_mgr, json={"reason": "Coba L2"})
    assert r.status_code == 403, r.text
    r = client.post(f"/api/v1/overtime/requests/{req['id']}/approve-l2",
                    headers=h, json={"reason": "Disetujui HR"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
