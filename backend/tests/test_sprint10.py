"""Test Sprint 10: go-live & hardening keamanan (ADR-0013).

Rate limiting login, kebijakan password, isolasi tenant, JWT kedaluwarsa,
security headers, dan startup check SECRET_KEY produksi.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.v1.auth import clear_login_attempts
from app.core.config import JWT_ALGORITHM, get_secret_key
from app.core.security import validate_password_policy
from app.main import create_app

from .conftest import login_headers  # noqa: F401  (dipakai via fixture ctx/client)

STRONG = "Password123!"  # 12 char, lolos semua aturan kebijakan


def _fail_login(client, email, n=1):
    codes = []
    for _ in range(n):
        r = client.post("/api/v1/auth/login", json={
            "tenant_slug": "hashiru", "email": email,
            "password": "salah-salah-salah"})
        codes.append(r.status_code)
    return codes


# ------------------------------------------------------------- rate limiting
def test_rate_limit_5_gagal_lalu_429(client):
    clear_login_attempts()
    codes = _fail_login(client, "ratelimit1@x.id", 6)
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": "ratelimit1@x.id",
        "password": "salah-salah-salah"})
    assert r.headers.get("retry-after") == "60"


def test_rate_limit_sukses_me_reset(client, ctx):
    clear_login_attempts()
    email = "u_full@x.id"
    assert _fail_login(client, email, 4) == [401] * 4
    # sukses untuk email yang SAMA me-reset counter
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": email, "password": STRONG})
    assert r.status_code == 200
    # 5 kegagalan baru setelah reset: belum 429
    assert _fail_login(client, email, 5) == [401] * 5
    # kegagalan ke-6 setelah reset -> 429
    assert _fail_login(client, email, 1) == [429]


# ---------------------------------------------------------- kebijakan password
@pytest.mark.parametrize("password,alasan", [
    ("Pendek1!", "terlalu pendek"),
    ("password123!!", "tanpa huruf besar"),
    ("PASSWORD123!!", "tanpa huruf kecil"),
    ("Password!!!!!", "tanpa angka"),
    ("Password12345", "tanpa simbol"),
])
def test_password_lemah_ditolak_422(client, ctx, password, alasan):
    h = login_headers(client, "hashiru", "admin_a@x.id")
    r = client.post("/api/v1/users", headers=h, json={
        "email": f"lemah-{alasan.split()[1]}@x.id".replace(" ", ""),
        "full_name": "Lemah", "password": password, "reason": "test s10"})
    assert r.status_code == 422, (alasan, r.text)


def test_password_kuat_lolos_dan_bisa_login(client, ctx):
    h = login_headers(client, "hashiru", "admin_a@x.id")
    email = "kuat@x.id"
    r = client.post("/api/v1/users", headers=h, json={
        "email": email, "full_name": "Kuat", "password": STRONG,
        "reason": "test s10"})
    assert r.status_code == 201, r.text
    assert r.json()["is_superadmin"] is False
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": email, "password": STRONG})
    assert r.status_code == 200


def test_validate_password_policy_unit():
    assert validate_password_policy(STRONG) == []
    v = validate_password_policy("pendek")  # tanpa besar/angka/simbol + pendek
    assert len(v) == 4 and any("12 karakter" in x for x in v)


def test_change_password_lemah_422_lalu_sukses(client, ctx):
    h = login_headers(client, "hashiru", "admin_a@x.id")
    r = client.post("/api/v1/auth/change-password", headers=h, json={
        "old_password": STRONG, "new_password": "lemah"})
    assert r.status_code == 422
    r = client.post("/api/v1/auth/change-password", headers=h, json={
        "old_password": "salah-lama", "new_password": STRONG + "x"})
    assert r.status_code == 401
    baru = "BaruKuat123!#"
    r = client.post("/api/v1/auth/change-password", headers=h, json={
        "old_password": STRONG, "new_password": baru})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/login", json={
        "tenant_slug": "hashiru", "email": "admin_a@x.id", "password": baru})
    assert r.status_code == 200


# ------------------------------------------------------------- isolasi & JWT
def test_person_tenant_lain_404(client, ctx):
    h = login_headers(client, "hashiru", "admin_a@x.id")
    r = client.get(f"/api/v1/persons/{ctx['p_b'].id}", headers=h)
    assert r.status_code == 404


def test_jwt_kedaluwarsa_401(client, ctx):
    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "tenant_id": str(ctx["ta"].id), "roles": [],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    token = jwt.encode(payload, get_secret_key(), algorithm=JWT_ALGORITHM)
    r = client.get("/api/v1/persons",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_tanpa_token_401(client):
    r = client.get("/api/v1/persons")
    assert r.status_code == 401


# -------------------------------------------------------- security headers
def test_security_headers_hadir(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in r.headers  # HTTP polos


def test_hsts_hanya_bila_https(client):
    r = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert "strict-transport-security" in r.headers


# ------------------------------------------------------------ startup check
def test_startup_tolak_secret_default_di_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("sqlite://")


def test_startup_ok_bila_secret_diisi(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "rahasia-produksi-yang-panjang-32-karakter-xx")
    app = create_app("sqlite://")  # tidak raise
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
