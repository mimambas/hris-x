"""Router ANL-005: katalog dataset, ekspor inkremental, kunci API BI.

Ekspor dapat diakses JWT pengguna atau header X-BI-Key (kunci
milik pengguna; izin & populasi mengikuti pemiliknya). Membuat
kunci membalas token plaintext SATU KALI — hanya hash-nya yang
disimpan server.
"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import (APIRouter, Depends, Header, HTTPException, Query,
                     Request, Response, status)
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.rls import set_request_tenant_id
from app.core.security import decode_access_token
from app.models import Tenant, User
from app.schemas import schemas as sch
from app.services import bi_export as bi_service
from app.services.audit import write_audit

router = APIRouter(tags=["bi"])


def _authenticate(request: Request, db: Session,
                  x_bi_key: str | None) -> User:
    """JWT Bearer, atau kunci BI via header X-BI-Key."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = decode_access_token(
                auth.split(" ", 1)[1].strip())
            user_id = uuid.UUID(payload["sub"])
            tenant_id = uuid.UUID(payload["tenant_id"])
        except Exception as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Token tidak valid atau kedaluwarsa") from exc
        set_request_tenant_id(tenant_id)
        user = db.get(User, user_id)
        tenant = db.get(Tenant, tenant_id)
        if user is None or not user.is_active \
                or user.tenant_id != tenant_id \
                or tenant is None or not tenant.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "Token tidak valid")
        return user
    if x_bi_key:
        tenant_id = bi_service.tenant_id_from_token(x_bi_key)
        if tenant_id is not None:
            set_request_tenant_id(tenant_id)
            owner = bi_service.user_for_token(db, x_bi_key)
            if owner is not None:
                return owner
    raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                        "Butuh JWT pengguna atau header X-BI-Key "
                        "yang valid")


def _export_response(dataset, since, limit, format, db, user):
    try:
        result = bi_service.export_rows(db, user, dataset, since,
                                        limit)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            str(exc)) from exc
    if format == "csv":
        rows = result["rows"]
        fields = list(rows[0].keys()) if rows else ["employment_id"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return Response(
            content=buf.getvalue(), media_type="text/csv",
            headers={"Content-Disposition":
                     f"attachment; filename=bi-{dataset}.csv"})
    return result


@router.get("/bi/datasets", response_model=list[sch.BiDatasetOut])
def datasets(request: Request,
             x_bi_key: str | None = Header(default=None),
             db: Session = Depends(get_db)):
    user = _authenticate(request, db, x_bi_key)
    return bi_service.datasets_for(db, user)


@router.get("/bi/exports/{dataset}")
def export_dataset(
    dataset: str,
    request: Request,
    since: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=1000),
    format: str = Query(default="json", pattern="^(json|csv)$"),
    x_bi_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    user = _authenticate(request, db, x_bi_key)
    return _export_response(dataset, since, limit, format, db, user)


@router.get("/bi/keys", response_model=list[sch.BiKeyOut])
def list_keys(user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return bi_service.list_keys(db, user)


@router.post("/bi/keys", response_model=sch.BiKeyCreatedOut,
             status_code=status.HTTP_201_CREATED)
def create_key(body: sch.BiKeyCreate, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    key, token = bi_service.create_key(db, user, body.name)
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="insert", object_type="bi_api_key", object_id=key.id,
        old_values=None, new_values={"name": key.name},
        reason=None, channel="api", ip=client_ip(request))
    db.commit()
    return {"id": key.id, "name": key.name,
            "last_used_at": key.last_used_at,
            "revoked_at": key.revoked_at,
            "created_at": key.created_at,
            "token": token,
            "token_hint": "Simpan token ini sekarang: token hanya "
                          "ditampilkan satu kali."}


@router.delete("/bi/keys/{key_id}", response_model=sch.BiKeyOut)
def delete_key(key_id: uuid.UUID, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    key = bi_service.revoke_key(db, user, key_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Kunci tidak ditemukan")
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="update", object_type="bi_api_key", object_id=key.id,
        old_values=None, new_values={"revoked": True},
        reason=None, channel="api", ip=client_ip(request))
    db.commit()
    return key
