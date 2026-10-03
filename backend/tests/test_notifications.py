"""Notifikasi in-app & preferensi notifikasi (EXP-005, PRD 13.1).

Pengumuman/kudos/perubahan-data memicu notifikasi in-app penerima;
preferensi kanal in_app per kategori yang dimatikan menekan
notifikasi baru. Kanal email/whatsapp tersimpan sebagai preferensi
tapi ditandai belum terhubung.
"""

from __future__ import annotations

from .conftest import login_headers


def fh(client):
    return login_headers(client, "hashiru", "u_full@x.id")


def mh(client):
    return login_headers(client, "hashiru", "u_mgr@x.id")


def sh(client):
    return login_headers(client, "hashiru", "u_staff@x.id")


def _publish_announcement(client, title="Libur nasional"):
    r = client.post("/api/v1/announcements", headers=fh(client), json={
        "title": title, "body": "Kantor tutup.", "target_type": "semua"})
    assert r.status_code == 201, r.text
    return r.json()


def _inbox(client, h, **kw):
    r = client.get("/api/v1/notifications", headers=h, params=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_announcement_creates_inapp_notification(client, ctx):
    h_staff = sh(client)
    assert _inbox(client, h_staff)["unread_count"] == 0
    _publish_announcement(client)
    box = _inbox(client, h_staff)
    assert box["unread_count"] == 1, box
    item = box["items"][0]
    assert item["category"] == "pengumuman"
    assert "Libur nasional" in item["title"]
    assert item["is_read"] is False

    r = client.post(f"/api/v1/notifications/{item['id']}/read",
                    headers=h_staff)
    assert r.status_code == 200, r.text
    assert r.json()["is_read"] is True
    assert _inbox(client, h_staff)["unread_count"] == 0


def test_notification_is_private_to_owner(client, ctx):
    h_staff, h_mgr = sh(client), mh(client)
    _publish_announcement(client, "Rapat umum")
    item = _inbox(client, h_staff)["items"][0]
    r = client.post(f"/api/v1/notifications/{item['id']}/read",
                    headers=h_mgr)
    assert r.status_code == 404, r.text


def test_preference_matrix_and_suppression(client, ctx):
    h_staff = sh(client)
    r = client.get("/api/v1/notification-preferences", headers=h_staff)
    assert r.status_code == 200, r.text
    matrix = r.json()
    assert len(matrix) == 15, matrix  # 5 kategori x 3 kanal
    in_app = [m for m in matrix if m["channel"] == "in_app"]
    assert all(m["enabled"] and m["channel_available"] for m in in_app)
    email = [m for m in matrix if m["channel"] == "email"]
    assert all(m["channel_available"] is False for m in email)

    # Matikan in-app untuk pengumuman -> pengumuman baru tidak berbunyi.
    r = client.put("/api/v1/notification-preferences", headers=h_staff,
                   json={"preferences": [{
                       "category": "pengumuman", "channel": "in_app",
                       "enabled": False}]})
    assert r.status_code == 200, r.text
    entry = [m for m in r.json() if m["category"] == "pengumuman"
             and m["channel"] == "in_app"][0]
    assert entry["enabled"] is False

    _publish_announcement(client, "Tidak akan berbunyi")
    box = _inbox(client, h_staff)
    assert all("Tidak akan berbunyi" not in i["title"]
               for i in box["items"]), box


def test_kudos_and_data_change_notifications(client, ctx):
    h_staff, h_hr = sh(client), fh(client)
    r = client.post("/api/v1/kudos", headers=h_hr, json={
        "to_employment_id": str(ctx["e_staff"].id),
        "category": "kolaborasi", "message": "Bantuannya luar biasa!"})
    assert r.status_code == 201, r.text
    box = _inbox(client, h_staff)
    assert any(i["category"] == "kudos" for i in box["items"]), box

    r = client.post("/api/v1/data-changes", headers=h_staff, json={
        "change_type": "alamat",
        "new_values": {"address": "Jl. Kenanga No. 3, Bekasi"}})
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    r = client.post(f"/api/v1/data-changes/{req_id}/approve",
                    headers=h_hr, json={})
    assert r.status_code == 200, r.text
    box = _inbox(client, h_staff)
    assert any(i["category"] == "perubahan_data" for i in box["items"]), box

    r = client.post("/api/v1/notifications/read-all", headers=h_staff)
    assert r.status_code == 200, r.text
    assert _inbox(client, h_staff)["unread_count"] == 0
