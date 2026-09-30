"""Uji autentikasi multi-tenant."""

from __future__ import annotations

import jwt as pyjwt

from tests.conftest import PASSWORD, login_headers


def test_login_ok(client, ctx):
    r = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "hashiru", "email": "u_full@x.id",
              "password": PASSWORD},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["tenant_id"] == str(ctx["ta"].id)
    assert "HR" in body["roles"]
    # JWT memuat tenant_id & user_id
    payload = pyjwt.decode(body["access_token"], options={"verify_signature": False})
    assert payload["tenant_id"] == str(ctx["ta"].id)
    assert payload["sub"]


def test_login_salah_password(client, ctx):
    r = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "hashiru", "email": "u_full@x.id",
              "password": "salah"},
    )
    assert r.status_code == 401


def test_login_tenant_tidak_dikenal(client, ctx):
    r = client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "tidak-ada", "email": "u_full@x.id",
              "password": PASSWORD},
    )
    assert r.status_code == 401


def test_login_beda_tenant_beda_token(client, ctx):
    h_a = login_headers(client, "hashiru", "admin_a@x.id")
    h_b = login_headers(client, "acme", "admin_b@x.id")
    me_a = client.get("/api/v1/me", headers=h_a).json()
    me_b = client.get("/api/v1/me", headers=h_b).json()
    assert me_a["tenant_id"] != me_b["tenant_id"]


def test_me_tanpa_token_401(client, ctx):
    assert client.get("/api/v1/me").status_code == 401


def test_me_dengan_token(client, ctx):
    h = login_headers(client, "hashiru", "u_mgr@x.id")
    r = client.get("/api/v1/me", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "u_mgr@x.id"
    assert "MgrRole" in body["roles"]
    assert "Inserter" in body["roles"]
