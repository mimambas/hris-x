"""HRIS-X backend — fondasi Sprint 1 (PRD 24.2 S1) s.d. Sprint 10.

Tenant, auth, RBP dasar, audit, layanan effective dating, modul HR lengkap,
dan hardening keamanan go-live (Sprint 10, ADR-0013).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import (
    DEFAULT_SECRET_KEY,
    get_allowed_origins,
    get_database_url,
    get_env,
    get_secret_key,
)
from app.core.db import get_engine, init_db
from app.core.rls import clear_request_tenant_id
from app.models import Base


def _check_production_secret() -> None:
    """Tolak start bila ENV=production tapi SECRET_KEY masih default.

    Kegagalan di sini fail-closed: lebih baik aplikasi tidak jalan daripada
    berjalan dengan kunci JWT yang bisa ditebak publik.
    """
    if get_env() == "production" and get_secret_key() == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "ENV=production tetapi SECRET_KEY masih bernilai default "
            "('dev-only-secret-key-ganti-di-produksi'). Set SECRET_KEY ke "
            "nilai acak yang panjang sebelum menjalankan di produksi."
        )


def create_app(database_url: str | None = None) -> FastAPI:
    _check_production_secret()

    url = database_url or get_database_url()
    engine = init_db(url)
    # create_all HANYA untuk dev/test (SQLite). Di Postgres produksi/
    # staging role aplikasi SENGAJA tanpa hak CREATE (ADR-0014) sehingga
    # create_all MELEDAK ("permission denied for schema public") setiap
    # ada tabel baru dan membuat SELURUH fungsi serverless gagal start.
    # Tabel baru dibuat pemilik DB via skrip migrations/*.sql.
    try:
        Base.metadata.create_all(engine)
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("hrisx").warning(
            "create_all dilewati (%s). Pastikan skema terbaru sudah "
            "diterapkan via migrations/*.sql sebagai pemilik database.",
            exc,
        )

    app = FastAPI(
        title="HRIS-X API",
        description="Sprint 1-10: tenant, auth, RBP, audit, effective dating, "
                    "modul HR lengkap + hardening keamanan go-live.",
        version="1.0.0-sprint10",
    )

    # Sprint 10: CORS — default TANPA CORS (same-origin saja); daftar
    # origin hanya dari env ALLOWED_ORIGINS (koma-dipisah).
    allowed_origins = get_allowed_origins()
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
            expose_headers=["Content-Disposition"],
        )

    # RLS request-context (ADR-0014): reset ContextVar tenant di awal &
    # akhir setiap request — higiene agar tenant request sebelumnya tidak
    # bocor ke request berikutnya (worker async dipakai ulang). Didaftarkan
    # duluan agar menjadi middleware terluar (finally-nya jalan paling akhir).
    @app.middleware("http")
    async def rls_tenant_context(request, call_next):
        clear_request_tenant_id()
        try:
            return await call_next(request)
        finally:
            clear_request_tenant_id()

    # Sprint 10: security headers dasar untuk semua respons.
    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HSTS hanya bila request memang HTTPS (langsung atau via proxy).
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if proto == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    app.include_router(api_router)

    @app.get("/health", tags=["ops"])
    def health():
        get_engine()  # pastikan DB terinisialisasi
        return {"status": "ok", "app": "hris-x", "sprint": 10}

    return app


app = create_app()
