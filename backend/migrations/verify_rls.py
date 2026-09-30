#!/usr/bin/env python3
"""Verifikasi RLS tenant (Sprint 2).

Membutuhkan Postgres yang bisa dijangkau + DATABASE_URL. Tidak merusak data:
membuat tenant + 1 person dummy, lalu memastikan tenant lain tidak bisa
melihatnya, lalu rollback.

Contoh:
    DATABASE_URL=postgresql+psycopg://app:secret@localhost:5432/hrisx \\
        python backend/migrations/verify_rls.py

Skrip:
  1. Terapkan 001_rls.sql bila policy belum ada.
  2. SET LOCAL app.tenant_id = A -> INSERT person -> SELECT terlihat.
  3. SET LOCAL app.tenant_id = B -> SELECT tidak melihat person milik A;
     INSERT dengan tenant_id=A ditolak policy.
  4. Rollback; tanpa SET app.tenant_id, SELECT mengembalikan 0 baris.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

SQL_FILE = Path(__file__).with_name("001_rls.sql")


def main() -> int:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        print("Butuh paket 'psycopg' (pip install psycopg[binary]).")
        return 2
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Set DATABASE_URL dulu, mis. "
              "postgresql+psycopg://app:secret@localhost:5432/hrisx")
        return 2

    engine = create_engine(db_url)
    with engine.begin() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM pg_policies "
            "WHERE schemaname='public' AND policyname='tenant_isolation'"
        )).scalar()
        if not n:
            print("Menerapkan 001_rls.sql ...")
            conn.execute(text(SQL_FILE.read_text()))
        else:
            print(f"Policy tenant_isolation sudah ada ({n} tabel).")

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    ok = True
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(
                "INSERT INTO tenants (id, name, slug) VALUES "
                "(:a, 'Tenant A', 'rls-a'), (:b, 'Tenant B', 'rls-b')"),
                {"a": tenant_a, "b": tenant_b})

            # Tenant A menulis & membaca datanya sendiri.
            conn.execute(text(f"SET LOCAL app.tenant_id = '{tenant_a}'"))
            conn.execute(text(
                "INSERT INTO persons (id, tenant_id, nik, full_name) VALUES "
                "(:id, :t, '0000000000000001', 'Orang A')"),
                {"id": uuid.uuid4(), "t": tenant_a})
            seen_a = conn.execute(
                text("SELECT count(*) FROM persons")).scalar()
            print(f"[A] melihat {seen_a} person (harap 1)")
            ok &= seen_a == 1

            # Tenant B tidak melihat data A.
            conn.execute(text(f"SET LOCAL app.tenant_id = '{tenant_b}'"))
            seen_b = conn.execute(
                text("SELECT count(*) FROM persons")).scalar()
            print(f"[B] melihat {seen_b} person (harap 0)")
            ok &= seen_b == 0

            # Tenant B tidak bisa menyelipkan baris milik A.
            try:
                conn.execute(text(
                    "INSERT INTO persons (id, tenant_id, nik, full_name) VALUES "
                    "(:id, :t, '0000000000000002', 'Serangan')"),
                    {"id": uuid.uuid4(), "t": tenant_a})
                print("[B] INSERT lintas tenant LOLOS — policy bermasalah!")
                ok = False
            except Exception as e:  # noqa: BLE001 - pesan policy Postgres
                print(f"[B] INSERT lintas tenant ditolak (benar): "
                      f"{type(e).__name__}")
        finally:
            trans.rollback()

        # Tanpa konteks tenant: tidak ada baris yang terlihat.
        conn.execute(text("RESET app.tenant_id"))
        seen_none = conn.execute(
            text("SELECT count(*) FROM persons")).scalar()
        print(f"[tanpa tenant] melihat {seen_none} person (harap 0)")
        ok &= seen_none == 0

    print("RLS OK — isolasi tenant terverifikasi." if ok
          else "RLS GAGAL — periksa policy.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
