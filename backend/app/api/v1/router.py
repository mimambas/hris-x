"""Agregator router API v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    attendance,
    audit_logs,
    auth,
    claims,
    comp_info,
    contracts,
    custom_fields,
    dashboard,
    documents,
    imports,
    job_info,
    leave,
    lifecycle,
    loans,
    org,
    overtime,
    payroll,
    performance,
    persons,
    rbac,
    recruitment,
    reports,
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
api_router.include_router(custom_fields.router)
api_router.include_router(lifecycle.router)
api_router.include_router(contracts.router)
api_router.include_router(imports.router)
api_router.include_router(documents.router)
api_router.include_router(payroll.router)
api_router.include_router(performance.router)
api_router.include_router(attendance.router)
api_router.include_router(leave.router)
api_router.include_router(overtime.router)
api_router.include_router(recruitment.router)
api_router.include_router(claims.router)
api_router.include_router(loans.router)
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)
