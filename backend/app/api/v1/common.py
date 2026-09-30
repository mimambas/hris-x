"""Helper kecil untuk endpoint API v1."""

from __future__ import annotations

from fastapi import Request


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def snapshot(obj, fields: list[str]) -> dict:
    return {f: getattr(obj, f) for f in fields if hasattr(obj, f)}
