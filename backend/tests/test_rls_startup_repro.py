"""Repro: create_app di Postgres yang SUDAH punya tabel + RLS + data.

Meniru kondisi staging Neon: tabel lama sudah ada, RLS aktif, lalu
create_all dijalankan lagi (menambah 4 tabel onboarding). Bila gagal,
traceback-nya = jawaban kenapa Vercel 500.

Jalankan HANYA bila HRISX_TEST_PG_URL ter-set (CI Postgres asli).
"""

from __future__ import annotations

import os

import pytest

pg = pytest.mark.skipif(
    not os.environ.get("HRISX_TEST_PG_URL"),
    reason="butuh HRISX_TEST_PG_URL (Postgres asli)",
)


@pg
def test_create_app_di_pg_berrls():
    from sqlalchemy import create_engine, text

    from app.main import create_app

    url = os.environ["HRISX_TEST_PG_URL"]

    # 1) Buat skema dari NOL via create_all (seperti deployment pertama).
    eng = create_engine(url)
    from app.models import Base
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)

    # 2) Terapkan RLS (whitelist penuh, termasuk onboarding_*).
    mig = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "migrations" / "001_rls.sql"
    ).read_text()
    with eng.begin() as conn:
        for stmt in _split(mig):
            conn.exec_driver_sql(stmt)

    # 2b) HAPUS tabel onboarding untuk meniru kondisi staging:
    #     RLS sudah aktif, lalu create_all harus CREATE tabel baru.
    with eng.begin() as conn:
        for t in ("onboarding_template_tasks", "onboarding_tasks",
                  "onboarding_processes", "onboarding_templates"):
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS {t} CASCADE")

    # 3) Jalankan create_app penuh -> ini yang meledak di Vercel?
    os.environ["DATABASE_URL"] = url
    app = create_app(url)
    assert app is not None


def _split(sql_text: str) -> list[str]:
    stmts, buf = [], []
    i, n = 0, len(sql_text)
    in_dollar = False
    while i < n:
        if sql_text.startswith("$$", i):
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        if not in_dollar and sql_text.startswith("--", i):
            j = sql_text.find("\n", i)
            j = n if j == -1 else j
            buf.append(sql_text[i:j])
            i = j
            continue
        ch = sql_text[i]
        if ch == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    out = []
    for s in stmts:
        code = [ln for ln in s.splitlines()
                if ln.strip() and not ln.strip().startswith("--")]
        if code:
            out.append(s)
    return out
