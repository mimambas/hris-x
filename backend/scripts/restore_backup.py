#!/usr/bin/env python3
"""Restore uji dari file backup JSON (lihat GET /admin/backup/export).

Memuat dump ke DATABASE TARGET YANG KOSONG (mis. Neon branch baru untuk
uji restore). Menolak bila target berisi data, kecuali --force.

Contoh:
    DATABASE_URL=postgresql+psycopg://... python restore_backup.py \\
        backup-20261001-1200.json

Verifikasi: membandingkan jumlah baris per tabel dengan isi dump.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import Uuid, DateTime, Date, Time, Numeric, Integer, Boolean, LargeBinary

from app.models import Base


def _parse(col_type, value):
    if value is None:
        return None
    t = col_type
    if isinstance(t, (Uuid, PG_UUID)):
        return uuid.UUID(value)
    if isinstance(t, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(t, Date):
        return date.fromisoformat(value)
    if isinstance(t, Numeric):
        return Decimal(str(value))
    if isinstance(t, Integer):
        return int(value)
    if isinstance(t, Boolean):
        return bool(value)
    if isinstance(t, LargeBinary):
        return bytes.fromhex(value)
    return value


def _tenant_tables():
    return [t for t in Base.metadata.sorted_tables if "tenant_id" in t.c]


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore uji backup HRIS-X.")
    ap.add_argument("dump", help="File JSON hasil /admin/backup/export")
    ap.add_argument("--force", action="store_true",
                    help="Lewati pengecekan target kosong")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("Set DATABASE_URL target dulu.", file=sys.stderr)
        return 2
    dump = json.loads(Path(args.dump).read_text())
    if dump.get("format") != "hrisx-backup/1":
        print(f"Format dump tak dikenal: {dump.get('format')}", file=sys.stderr)
        return 2
    tenant_id = uuid.UUID(dump["tenant_id"])
    tables_data = dump["tables"]

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    tenants_table = Base.metadata.tables["tenants"]

    from sqlalchemy.orm import Session
    with Session(engine) as db:
        if not args.force:
            total = 0
            for table in _tenant_tables():
                total += db.execute(
                    select(table.c.id).limit(1)
                ).first() is not None
            if total:
                print("Target TIDAK kosong; batalkan (pakai --force untuk paksa).",
                      file=sys.stderr)
                return 3

        # Baris tenants WAJIB ada dulu: 63 tabel lain punya FK tenant_id ->
        # tenants.id. Tanpa ini Postgres menolak semua INSERT (di SQLite
        # lolos diam-diam karena FK tidak dienforce — bug 2026-10-02).
        tenant_payload = dump.get("tenant")
        if tenant_payload:
            values = {
                col.name: _parse(col.type, tenant_payload[col.name])
                for col in tenants_table.c
                if col.name in tenant_payload
            }
        else:
            # Dump lama (tanpa kunci "tenant"): buat baris minimal agar FK
            # valid. Slug asli tidak tersimpan -> koreksi manual setelahnya.
            values = {
                "id": tenant_id,
                "slug": f"restored-{str(tenant_id)[:8]}",
                "name": "Restored tenant",
            }
            print('  PERINGATAN: dump tanpa "tenant" (format lama); baris '
                  "tenants dibuat minimal, periksa slug manual.")
        already = db.execute(
            select(tenants_table.c.id).where(tenants_table.c.id == tenant_id)
        ).first()
        if not already:
            db.execute(tenants_table.insert().values(**values))
            db.commit()
        print(f"  tenants: 1 baris (id {str(tenant_id)[:8]}...)")

        for table in _tenant_tables():
            rows = tables_data.get(table.name, [])
            for r in rows:
                if r.get("tenant_id") != str(tenant_id):
                    continue
                values = {}
                for col in table.c:
                    if col.name not in r:
                        continue
                    values[col.name] = _parse(col.type, r[col.name])
                # Berkas dokumen: tulis ulang ke storage bila ikut dibackup.
                if table.name == "documents" and r.get("file_content_hex"):
                    from app.services import storage as storage_service
                    key = storage_service.get_storage().save(
                        str(tenant_id),
                        Path(r.get("file_name") or "dokumen").name,
                        bytes.fromhex(r["file_content_hex"]),
                        r.get("mime_type") or "application/octet-stream",
                    )
                    values["file_path"] = key
                db.execute(table.insert().values(**values))
            db.commit()
            print(f"  {table.name}: {len(rows)} baris")

        # Verifikasi jumlah baris.
        ok = True
        got_tenant = db.execute(
            select(tenants_table.c.id).where(tenants_table.c.id == tenant_id)
        ).first()
        print(f"verifikasi tenants: {'OK' if got_tenant else 'HILANG'}")
        if not got_tenant:
            ok = False
        for table in _tenant_tables():
            expected = sum(
                1 for r in tables_data.get(table.name, [])
                if r.get("tenant_id") == str(tenant_id)
            )
            got = db.execute(
                select(table.c.id).where(table.c.tenant_id == tenant_id)
            ).all()
            status = "OK" if len(got) == expected else "BEDA"
            if len(got) != expected:
                ok = False
            print(f"verifikasi {table.name}: dump={expected} db={len(got)} {status}")
        print("RESTORE OK" if ok else "RESTORE BERMASALAH")
        return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
