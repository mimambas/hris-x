"""Sprint 2: org bertanggal efektif, custom field, target population, RLS."""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import login_headers

TODAY = date.today()
FUTURE = (TODAY + timedelta(days=60)).isoformat()
PAST = "2021-01-01"


def ah(client):
    return login_headers(client, "hashiru", "admin_a@x.id")


def _mk_unit(client, h, name, le_id, parent_id=None, valid_from=PAST):
    r = client.post(
        "/api/v1/org/units",
        headers=h,
        json={
            "name": name,
            "parent_id": str(parent_id) if parent_id else None,
            "legal_entity_id": str(le_id),
            "valid_from": valid_from,
            "event": "Pembentukan",
            "event_reason": "test",
            "reason": "test",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _version_unit(client, h, unit_id, valid_from, reason="test", **fields):
    body = {
        "valid_from": valid_from,
        "event": "Reorganisasi",
        "event_reason": "test",
        "reason": reason,
        **fields,
    }
    return client.post(
        f"/api/v1/org/units/{unit_id}/versions", headers=h, json=body
    )


def _chart(client, h, as_of):
    r = client.get(f"/api/v1/org/chart?as_of={as_of}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _flatten(nodes, parent=None, out=None):
    out = {} if out is None else out
    for n in nodes:
        out[n["name"]] = parent
        _flatten(n["children"], n["name"], out)
    return out


# ---------------------------------------------------------------------------
# Struktur organisasi bertanggal efektif
# ---------------------------------------------------------------------------
def test_org_chart_hierarki_dan_as_of(client, ctx):
    h = ah(client)
    le = ctx["le"]
    p1 = _mk_unit(client, h, "P1", le.id)["org_unit_id"]
    p2 = _mk_unit(client, h, "P2", le.id)["org_unit_id"]
    c = _mk_unit(client, h, "C", le.id, parent_id=p1)["org_unit_id"]

    # Pindah C dari P1 ke P2 berlaku 60 hari ke depan.
    r = _version_unit(client, h, c, FUTURE, parent_id=str(p2))
    assert r.status_code == 201, r.text

    before = _flatten(_chart(client, h, TODAY.isoformat()))
    assert before["C"] == "P1"
    after = _flatten(_chart(client, h, FUTURE))
    assert after["C"] == "P2"
    assert after["P1"] is None and after["P2"] is None


def test_org_unit_timeline_mencatat_perpindahan(client, ctx):
    h = ah(client)
    le = ctx["le"]
    a = _mk_unit(client, h, "A", le.id)["org_unit_id"]
    b = _mk_unit(client, h, "B", le.id)["org_unit_id"]
    r = _version_unit(client, h, b, FUTURE, parent_id=str(a))
    assert r.status_code == 201, r.text

    r = client.get(f"/api/v1/org/units/{b}/timeline", headers=h)
    assert r.status_code == 200, r.text
    tl = r.json()
    assert len(tl) == 2
    # Kronologis menaik (PLT-011): versi awal dulu, lalu hasil pindah parent.
    assert tl[0]["valid_from"] == PAST
    assert tl[0]["parent_id"] is None
    assert tl[1]["valid_from"] == FUTURE
    assert tl[1]["parent_id"] == str(a)
    assert tl[0]["seq_no"] == 1 and tl[1]["seq_no"] == 1


def test_org_circular_parent_ditolak(client, ctx):
    h = ah(client)
    le = ctx["le"]
    a = _mk_unit(client, h, "CA", le.id)["org_unit_id"]
    b = _mk_unit(client, h, "CB", le.id, parent_id=a)["org_unit_id"]

    # A menjadi anak dari B -> siklus A > B > A.
    r = _version_unit(client, h, a, FUTURE, parent_id=str(b))
    assert r.status_code == 422, r.text
    assert "sirkular" in r.json()["detail"].lower()

    # Unit menjadi parent dirinya sendiri.
    r = _version_unit(client, h, a, FUTURE, parent_id=str(a))
    assert r.status_code == 422, r.text


def test_org_nonaktif_unit_berpenghuni_ditolak(client, ctx):
    h = ah(client)
    ou_id = ctx["ou"].id  # fixture: 4 employment aktif di unit "Eng"
    r = _version_unit(client, h, str(ou_id), FUTURE, is_active=False)
    assert r.status_code == 422, r.text
    assert "tidak bisa dinonaktifkan" in r.json()["detail"]


def test_org_nonaktif_unit_kosong_boleh(client, ctx):
    h = ah(client)
    le = ctx["le"]
    u = _mk_unit(client, h, "Unit Kosong", le.id)["org_unit_id"]
    r = _version_unit(client, h, u, FUTURE, is_active=False)
    assert r.status_code == 201, r.text
    assert r.json()["is_active"] is False
    # Unit nonaktif tidak muncul di chart.
    names = _flatten(_chart(client, h, FUTURE))
    assert "Unit Kosong" not in names


def test_org_rename_dan_timeline_legal_entity(client, ctx):
    h = ah(client)
    r = client.post(
        "/api/v1/org/legal-entities",
        headers=h,
        json={
            "name": "PT Contoh",
            "npwp": "00",
            "valid_from": PAST,
            "event": "Pendirian",
            "event_reason": "test",
            "reason": "test",
        },
    )
    assert r.status_code == 201, r.text
    le_id = r.json()["legal_entity_id"]
    r = client.post(
        f"/api/v1/org/legal-entities/{le_id}/versions",
        headers=h,
        json={
            "name": "PT Contoh Tbk",
            "valid_from": FUTURE,
            "event": "Rebranding",
            "event_reason": "test",
            "reason": "test",
        },
    )
    assert r.status_code == 201, r.text
    r = client.get(f"/api/v1/org/legal-entities/{le_id}/timeline", headers=h)
    assert r.status_code == 200, r.text
    tl = r.json()
    assert [v["name"] for v in tl] == ["PT Contoh", "PT Contoh Tbk"]


def test_org_cost_center_crud_dan_timeline(client, ctx):
    h = ah(client)
    le = ctx["le"]
    ou = _mk_unit(client, h, "OU CC", le.id)["org_unit_id"]
    r = client.post(
        "/api/v1/org/cost-centers",
        headers=h,
        json={
            "code": "CC-TEST-01",
            "name": "Pusat Biaya Test",
            "org_unit_id": str(ou),
            "valid_from": PAST,
            "event": "Pembentukan",
            "event_reason": "test",
            "reason": "test",
        },
    )
    assert r.status_code == 201, r.text
    cc_id = r.json()["cost_center_id"]
    r = client.post(
        f"/api/v1/org/cost-centers/{cc_id}/versions",
        headers=h,
        json={
            "name": "Pusat Biaya Test Renamed",
            "valid_from": FUTURE,
            "event": "Rename",
            "event_reason": "test",
            "reason": "test",
        },
    )
    assert r.status_code == 201, r.text
    r = client.get(f"/api/v1/org/cost-centers/{cc_id}/timeline", headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2
    r = client.get("/api/v1/org/cost-centers", headers=h)
    assert r.status_code == 200, r.text
    assert any(c["code"] == "CC-TEST-01" for c in r.json())


def test_org_list_s1_tetap_kompatibel(client, ctx):
    h = ah(client)
    r = client.get("/api/v1/org/units", headers=h)
    assert r.status_code == 200, r.text
    units = {u["name"]: u for u in r.json()}
    assert "Eng" in units
    # id tetap identity id (kontrak S1).
    assert units["Eng"]["id"] == str(ctx["ou"].id)
    assert units["Eng"]["legal_entity_id"] == str(ctx["le"].id)
    r = client.get("/api/v1/org/legal-entities", headers=h)
    assert any(le["name"] == "PT Hashiru" for le in r.json())
    r = client.get("/api/v1/org/locations", headers=h)
    assert len(r.json()) == 3
    r = client.get("/api/v1/org/jobs", headers=h)
    assert len(r.json()) == 2


def test_org_audit_tertulis(client, ctx):
    h = ah(client)
    le = ctx["le"]
    _mk_unit(client, h, "Unit Audit", le.id)
    r = client.get(
        "/api/v1/audit-logs",
        headers=h,
        params={"object_type": "org_unit_info"},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) >= 1


# ---------------------------------------------------------------------------
# Custom field
# ---------------------------------------------------------------------------
def _mk_def(client, h, field_key="hobi_test", field_type="text", options=None,
            object_name="person"):
    body = {
        "object_name": object_name,
        "field_key": field_key,
        "label_id": f"Label {field_key}",
        "label_en": f"Label EN {field_key}",
        "field_type": field_type,
        "required": False,
        "options": options or [],
        "reason": "test",
    }
    r = client.post("/api/v1/custom-fields/definitions", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _set_value(client, h, definition_id, record_id, value):
    return client.post(
        "/api/v1/custom-fields/values",
        headers=h,
        json={
            "definition_id": str(definition_id),
            "record_id": str(record_id),
            "value": value,
            "reason": "test",
        },
    )


def _person_id(client, h, full_name):
    r = client.get("/api/v1/persons", headers=h)
    assert r.status_code == 200, r.text
    for p in r.json():
        if p["full_name"] == full_name:
            return p["id"]
    raise AssertionError(f"person {full_name} tidak ditemukan")


def test_custom_field_select_picklist_e2e(client, ctx):
    h = ah(client)
    d = _mk_def(
        client, h, field_key="ukuran_seragam", field_type="select",
        options=[
            {"value": "S", "label_id": "S", "label_en": "Small", "active": True},
            {"value": "M", "label_id": "M", "label_en": "Medium", "active": True},
            {"value": "L", "label_id": "L", "label_en": "Large", "active": True},
        ],
    )
    pid = _person_id(client, h, "Staff")
    r = _set_value(client, h, d["id"], pid, "L")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["field_key"] == "ukuran_seragam"
    assert out["value"] == "L"
    assert out["definition_active"] is True

    r = client.get(
        "/api/v1/custom-fields/values",
        headers=h,
        params={"object_name": "person", "record_id": pid},
    )
    assert r.status_code == 200, r.text
    vals = {v["field_key"]: v for v in r.json()}
    assert vals["ukuran_seragam"]["value"] == "L"
    assert vals["ukuran_seragam"]["label_id"] == "Label ukuran_seragam"


def test_custom_field_select_invalid_ditolak(client, ctx):
    h = ah(client)
    d = _mk_def(
        client, h, field_key="gol_darah", field_type="select",
        options=[{"value": "A", "label_id": "A", "active": True}],
    )
    pid = _person_id(client, h, "Staff")
    r = _set_value(client, h, d["id"], pid, "Z")
    assert r.status_code == 422, r.text
    assert "tidak tersedia" in r.json()["detail"]


def test_custom_field_tipe_number_date_text(client, ctx):
    h = ah(client)
    pid = _person_id(client, h, "Staff")
    d_num = _mk_def(client, h, field_key="skor_test", field_type="number")
    d_date = _mk_def(client, h, field_key="tgl_masuk_test", field_type="date")
    d_text = _mk_def(client, h, field_key="catatan_test", field_type="text")

    assert _set_value(client, h, d_num["id"], pid, 87.5).status_code == 201
    assert _set_value(client, h, d_date["id"], pid, "2026-03-15").status_code == 201
    assert _set_value(client, h, d_text["id"], pid, "bebas").status_code == 201

    r = client.get(
        "/api/v1/custom-fields/values",
        headers=h,
        params={"object_name": "person", "record_id": pid},
    )
    vals = {v["field_key"]: v for v in r.json()}
    assert float(vals["skor_test"]["value"]) == 87.5
    assert vals["tgl_masuk_test"]["value"] == "2026-03-15"
    assert vals["catatan_test"]["value"] == "bebas"

    # number yang bukan angka ditolak
    r = _set_value(client, h, d_num["id"], pid, "bukan-angka")
    assert r.status_code == 422, r.text


def test_custom_field_lookup_validasi_target(client, ctx):
    h = ah(client)
    d = _mk_def(
        client, h, field_key="jabatan_ref", field_type="lookup",
        options={"target": "job"},
    )
    pid = _person_id(client, h, "Staff")
    r = _set_value(client, h, d["id"], pid, str(ctx["job_stf"].id))
    assert r.status_code == 201, r.text
    # UUID acak yang bukan job -> 422
    import uuid as _uuid
    r = _set_value(client, h, d["id"], pid, str(_uuid.uuid4()))
    assert r.status_code == 422, r.text


def test_custom_field_nonaktif_data_lama_tetap_terbaca(client, ctx):
    h = ah(client)
    d = _mk_def(client, h, field_key="field_lama")
    pid = _person_id(client, h, "Staff")
    assert _set_value(client, h, d["id"], pid, "nilai lama").status_code == 201

    r = client.patch(
        f"/api/v1/custom-fields/definitions/{d['id']}",
        headers=h,
        json={"is_active": False, "reason": "test"},
    )
    assert r.status_code == 200, r.text

    # Nilai lama tetap terbaca, bertanda definisi nonaktif.
    r = client.get(
        "/api/v1/custom-fields/values",
        headers=h,
        params={"object_name": "person", "record_id": pid},
    )
    vals = {v["field_key"]: v for v in r.json()}
    assert vals["field_lama"]["value"] == "nilai lama"
    assert vals["field_lama"]["definition_active"] is False

    # Nilai baru tidak bisa ditulis ke definisi nonaktif.
    r = _set_value(client, h, d["id"], pid, "nilai baru")
    assert r.status_code == 422, r.text


def test_custom_field_soft_delete_dan_duplikat_key(client, ctx):
    h = ah(client)
    d = _mk_def(client, h, field_key="field_hapus")
    pid = _person_id(client, h, "Staff")
    assert _set_value(client, h, d["id"], pid, "tetap ada").status_code == 201

    r = client.delete(
        f"/api/v1/custom-fields/definitions/{d['id']}",
        headers=h,
        params={"reason": "test hapus"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    # Tidak muncul di daftar aktif, tapi nilai lama tetap terbaca.
    r = client.get("/api/v1/custom-fields/definitions", headers=h,
                   params={"object_name": "person"})
    assert all(x["field_key"] != "field_hapus" for x in r.json())
    r = client.get(
        "/api/v1/custom-fields/values",
        headers=h,
        params={"object_name": "person", "record_id": pid},
    )
    vals = {v["field_key"]: v for v in r.json()}
    assert vals["field_hapus"]["value"] == "tetap ada"

    # field_key ganda untuk objek yang sama ditolak (409).
    r = client.post(
        "/api/v1/custom-fields/definitions",
        headers=h,
        json={
            "object_name": "person", "field_key": "field_hapus",
            "label_id": "X", "field_type": "text", "reason": "test",
        },
    )
    assert r.status_code == 409, r.text


def test_custom_field_tanpa_izin_ditolak(client, ctx):
    # u_none: role Empty tanpa izin apa pun -> 403.
    h = login_headers(client, "hashiru", "u_none@x.id")
    r = client.get("/api/v1/custom-fields/definitions", headers=h)
    assert r.status_code == 403, r.text


def test_custom_field_deny_spesifik_mengalahkan_wildcard(client, ctx):
    h_admin = ah(client)
    d = _mk_def(client, h_admin, field_key="rahasia_test")
    pid = _person_id(client, h_admin, "Staff")
    assert _set_value(client, h_admin, d["id"], pid, "s3cr3t").status_code == 201

    # Role pembaca: person view + custom_field view.
    r = client.post("/api/v1/roles", headers=h_admin,
                    json={"name": "CFReader", "reason": "test"})
    assert r.status_code == 201, r.text
    role_id = r.json()["id"]
    for obj in ("person", "custom_field"):
        r = client.post(
            f"/api/v1/roles/{role_id}/field-permissions", headers=h_admin,
            json={"object_name": obj, "can_view": True, "reason": "test"},
        )
        assert r.status_code == 201, r.text
    r = client.post("/api/v1/groups", headers=h_admin,
                    json={"name": "G-CF", "population_rule": {"type": "all"},
                          "reason": "test"})
    assert r.status_code == 201, r.text
    group_id = r.json()["id"]
    r = client.post(
        f"/api/v1/roles/{role_id}/assign", headers=h_admin,
        json={"group_id": group_id,
              "target_population": {"type": "all"}, "reason": "test"},
    )
    assert r.status_code == 201, r.text

    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get(
        "/api/v1/custom-fields/values", headers=h_staff,
        params={"object_name": "person", "record_id": pid},
    )
    assert r.status_code == 200, r.text
    assert "rahasia_test" in {v["field_key"] for v in r.json()}

    # Deny eksplisit pada field spesifik.
    r = client.post(
        f"/api/v1/roles/{role_id}/field-permissions", headers=h_admin,
        json={"object_name": "person", "field_name": "custom:rahasia_test",
              "can_view": False, "reason": "test"},
    )
    assert r.status_code == 201, r.text
    r = client.get(
        "/api/v1/custom-fields/values", headers=h_staff,
        params={"object_name": "person", "record_id": pid},
    )
    assert r.status_code == 200, r.text
    assert "rahasia_test" not in {v["field_key"] for v in r.json()}


# ---------------------------------------------------------------------------
# Target population
# ---------------------------------------------------------------------------
def _set_manager(client, h_admin, ctx):
    r = client.post(
        "/api/v1/job-info",
        headers=h_admin,
        json={
            "employment_id": str(ctx["e_staff"].id),
            "valid_from": TODAY.isoformat(),
            "job_id": str(ctx["job_stf"].id),
            "org_unit_id": str(ctx["ou"].id),
            "location_id": str(ctx["loc_b"].id),
            "manager_employment_id": str(ctx["e_mgr"].id),
            "event": "Penetapan atasan",
            "event_reason": "test",
            "reason": "test",
        },
    )
    assert r.status_code == 201, r.text


def test_population_manager_melihat_tim(client, ctx):
    h_admin = ah(client)
    _set_manager(client, h_admin, ctx)
    h_mgr = login_headers(client, "hashiru", "u_mgr@x.id")

    r = client.get("/api/v1/persons", headers=h_mgr)
    assert r.status_code == 200, r.text
    names = {p["full_name"] for p in r.json()}
    assert "Staff" in names  # direct report terlihat
    assert "Full" not in names and "None" not in names  # di luar tim

    staff_id = _person_id(client, h_admin, "Staff")
    full_id = _person_id(client, h_admin, "Full")
    assert client.get(f"/api/v1/persons/{staff_id}", headers=h_mgr).status_code == 200
    # Detail di luar populasi -> 404 (tidak membocorkan keberadaan).
    assert client.get(f"/api/v1/persons/{full_id}", headers=h_mgr).status_code == 404


def test_population_karyawan_hanya_diri_sendiri(client, ctx):
    h_admin = ah(client)
    # Role SelfRole: person view, populasi "self".
    r = client.post("/api/v1/roles", headers=h_admin,
                    json={"name": "SelfRole", "reason": "test"})
    assert r.status_code == 201, r.text
    role_id = r.json()["id"]
    r = client.post(
        f"/api/v1/roles/{role_id}/field-permissions", headers=h_admin,
        json={"object_name": "person", "can_view": True, "reason": "test"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/groups", headers=h_admin,
                    json={"name": "G-Self", "population_rule": {"type": "all"},
                          "reason": "test"})
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/v1/roles/{role_id}/assign", headers=h_admin,
        json={"group_id": r.json()["id"],
              "target_population": {"type": "self"}, "reason": "test"},
    )
    assert r.status_code == 201, r.text

    h_staff = login_headers(client, "hashiru", "u_staff@x.id")
    r = client.get("/api/v1/persons", headers=h_staff)
    assert r.status_code == 200, r.text
    persons = r.json()
    assert len(persons) == 1
    assert persons[0]["full_name"] == "Staff"

    mgr_id = _person_id(client, h_admin, "Mgr")
    assert client.get(f"/api/v1/persons/{mgr_id}", headers=h_staff).status_code == 404


def test_population_assign_invalid_ditolak(client, ctx):
    h_admin = ah(client)
    r = client.post("/api/v1/roles", headers=h_admin,
                    json={"name": "BadPop", "reason": "test"})
    role_id = r.json()["id"]
    r = client.post("/api/v1/groups", headers=h_admin,
                    json={"name": "G-Bad", "reason": "test"})
    group_id = r.json()["id"]
    r = client.post(
        f"/api/v1/roles/{role_id}/assign", headers=h_admin,
        json={"group_id": group_id,
              "target_population": {"type": "semua-orang"}, "reason": "test"},
    )
    assert r.status_code == 422, r.text


def test_population_admin_melihat_semua(client, ctx):
    h = ah(client)
    r = client.get("/api/v1/persons", headers=h)
    assert r.status_code == 200, r.text
    assert {p["full_name"] for p in r.json()} == {"Full", "Mgr", "Staff", "None"}


# ---------------------------------------------------------------------------
# RLS Postgres (verifikasi statis: butuh Postgres asli untuk uji perilaku)
# ---------------------------------------------------------------------------
def test_rls_migration_memuat_policy_tenant():
    from pathlib import Path

    sql = (Path(__file__).parent.parent / "migrations" / "001_rls.sql").read_text()
    assert "CREATE POLICY tenant_isolation" in sql
    assert "app.tenant_id" in sql
    assert "SET LOCAL" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    for tabel in ("persons", "employments", "org_unit_info",
                  "custom_field_values", "audit_logs"):
        assert tabel in sql
