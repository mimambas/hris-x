"""Agregator router API v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    audit_logs,
    auth,
    comp_info,
    job_info,
    org,
    persons,
    rbac,
    tenants,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(persons.router)
api_router.include_router(job_info.router)
api_router.include_router(comp_info.router)
api_router.include_router(audit_logs.router)
api_router.include_router(rbac.router)
api_router.include_router(org.router)
