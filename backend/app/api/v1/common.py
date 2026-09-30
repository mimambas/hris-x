"""Helper kecil untuk endpoint API v1."""

from __future__ import annotations

from fastapi import HTTPException, Request, status


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def snapshot(obj, fields: list[str]) -> dict:
    return {f: getattr(obj, f) for f in fields if hasattr(obj, f)}


def resolve_employment(db, user, employment_id, object_name: str,
                       action: str = "view"):
    """Kembalikan Employment bila user boleh bertindak; 404/403 bila tidak.

    Aturan: superadmin bebas; employment milik sendiri bebas; selain itu
    butuh izin `action` pada object + lolos target population (via person).
    Dipakai endpoint ESS (absensi/cuti/lembur) Sprint 5.
    """
    from app.models import Employment
    from app.services import population as population_service
    from app.services import rbp as rbp_service

    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Employment tidak ditemukan")
    if user.is_superadmin:
        return emp
    own = population_service.get_user_employment(db, user)
    if own is not None and str(own.id) == str(emp.id):
        return emp
    if (rbp_service.has_permission(db, user, object_name, action)
            and population_service.can_view_person(db, user, emp.person_id)):
        return emp
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses employment ditolak")
