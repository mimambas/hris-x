"""HRIS-X backend — fondasi Sprint 1 (PRD 24.2 S1).

Tenant, auth, RBP dasar, audit, layanan effective dating.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_database_url
from app.core.db import get_engine, init_db
from app.models import Base


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or get_database_url()
    engine = init_db(url)
    Base.metadata.create_all(engine)

    app = FastAPI(
        title="HRIS-X API",
        description="Fondasi Sprint 1: tenant, auth, RBP, audit, effective dating.",
        version="0.1.0-sprint1",
    )
    app.include_router(api_router)

    @app.get("/health", tags=["ops"])
    def health():
        get_engine()  # pastikan DB terinisialisasi
        return {"status": "ok", "app": "hris-x", "sprint": 1}

    return app


app = create_app()
