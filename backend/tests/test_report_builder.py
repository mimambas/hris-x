"""Report builder self-service (ANL-002, PRD 13.4).

Katalog terkurasi digerbang izin RBP per objek dan field sensitif;
definisi tersimpan per pengguna dan dijalankan ulang terhadap
izin terkini. Ekspor XLSX memakai hasil run yang sama.
"""

from __future__ import annotations

from .conftest import login_headers


def hh(client):
    # u_full = HR penuh pada fixture bersama.
    return login_headers(client, "hashiru", "u_full@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def test_catalog_respects_rbp(client, ctx):
    r = client.get("/api/v1/report-builder/catalog", headers=hh(client))
    assert r.status_code == 200, r.text
    keys = [o["key"] for o in r.json()]
    assert "karyawan" in keys and "payroll" in keys, keys

    r = client.get("/api/v1/report-builder/catalog", headers=sh(client))
    assert r.status_code == 200, r.text
    staff_keys = [o["key"] for o in r.json()]
    assert "payroll" not in staff_keys, staff_keys
    assert "karyawan" not in staff_keys, staff_keys


def test_run_and_filter_karyawan(client, ctx):
    r = client.post("/api/v1/report-builder/run", headers=hh(client), json={
        "object": "karyawan", "fields": ["nama", "jabatan", "status"]})
    assert r.status_code == 200, r.text
    body = r.json()
    names = [row["nama"] for row in body["rows"]]
    assert any("Staf" in n for n in names), names

    r = client.post("/api/v1/report-builder/run", headers=hh(client), json={
        "object": "karyawan", "fields": ["nama"],
        "filters": [{"field": "nama", "op": "contains", "value": "Mgr"}]})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows and all("Mgr" in row["nama"] for row in rows), rows


def test_run_group_by_count(client, ctx):
    r = client.post("/api/v1/report-builder/run", headers=hh(client), json={
        "object": "karyawan", "fields": ["nama"], "group_by": "status",
        "aggregate_fn": "count"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert any(row["status"] == "active" and row["agregat"] >= 3
               for row in rows), rows


def test_sensitive_object_denied_for_staff(client, ctx):
    r = client.post("/api/v1/report-builder/run", headers=sh(client), json={
        "object": "payroll", "fields": ["nama", "gaji_bersih"]})
    assert r.status_code == 403, r.text

    r = client.post("/api/v1/report-builder/run", headers=hh(client), json={
        "object": "karyawan", "fields": ["nama", "field_ngawur"]})
    assert r.status_code == 403, r.text


def test_definitions_crud_and_run(client, ctx):
    h = hh(client)
    spec = {"object": "karyawan", "fields": ["nama", "status"],
            "filters": [{"field": "status", "op": "eq",
                         "value": "active"}]}
    r = client.post("/api/v1/report-definitions", headers=h,
                    json={"name": "Karyawan aktif", "spec": spec})
    assert r.status_code == 201, r.text
    def_id = r.json()["id"]

    mine = client.get("/api/v1/report-definitions", headers=h).json()
    assert any(d["id"] == def_id for d in mine), mine

    r = client.post(f"/api/v1/report-definitions/{def_id}/run", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["total_rows"] >= 3, r.json()

    # Definisi milik HR tidak terlihat oleh staf (404, bukan bocor).
    r = client.post(f"/api/v1/report-definitions/{def_id}/run",
                    headers=sh(client))
    assert r.status_code == 404, r.text

    r = client.delete(f"/api/v1/report-definitions/{def_id}", headers=h)
    assert r.status_code == 204, r.text


def test_export_xlsx(client, ctx):
    r = client.post("/api/v1/report-builder/export.xlsx",
                    headers=hh(client), json={
                        "object": "karyawan", "fields": ["nama", "nik"]})
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK", r.content[:8]
