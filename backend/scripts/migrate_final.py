"""Migrasi final Sprint 10 (go-live rehearsal).

Alur: DB SQLite FRESH di /tmp -> seed -> dry-run karyawan_500.xlsx ->
commit -> laporan kualitas -> demo/migration_report.json.

Verifikasi: tepat 500 karyawan terimpor, NIK duplikat = 0.
Catatan: ini rehearsal di SQLite; migrasi produksi memakai Postgres
(lihat docs/DEPLOYMENT.md).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = "/tmp/hrisx_migrate_final.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
Path(DB_PATH).unlink(missing_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.db import new_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Person  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "sample_data" / "karyawan_500.xlsx"


def main() -> int:
    print("1) Seed database fresh ...")
    seed.main()

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/api/v1/auth/login", json={
            "tenant_slug": "hashiru", "email": "admin@hashiru.id",
            "password": "Password123!"})
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        tenant_id = r.json()["tenant_id"]

        print("2) Dry-run impor ...")
        with open(XLSX, "rb") as f:
            r = client.post("/api/v1/imports/employees/dry-run",
                            files={"file": ("karyawan_500.xlsx", f,
                                             "application/vnd.openxmlformats-"
                                             "officedocument.spreadsheetml.sheet")},
                            headers=headers)
        assert r.status_code == 200, r.text[:500]
        dry = r.json()
        print(f"   total={dry['total_rows']} valid={dry['valid_rows']} "
              f"invalid={dry['invalid_rows']}")

        print("3) Commit impor ...")
        with open(XLSX, "rb") as f:
            r = client.post("/api/v1/imports/employees/commit",
                            files={"file": ("karyawan_500.xlsx", f,
                                             "application/vnd.openxmlformats-"
                                             "officedocument.spreadsheetml.sheet")},
                            headers=headers)
        assert r.status_code == 200, r.text[:500]
        committed = r.json()["imported"]
        print(f"   imported={committed}")

    print("4) Pemeriksaan kualitas ...")
    db = new_session()
    try:
        tid = uuid.UUID(tenant_id)
        persons = db.execute(
            select(Person).where(Person.tenant_id == tid)).scalars().all()
        niks = [p.nik for p in persons]
        dup_nik = len(niks) - len(set(niks))
        empty_email = sum(1 for p in persons if not (p.email or "").strip())
        invalid_nik = sum(
            1 for p in persons
            if not (p.nik or "").isdigit() or len(p.nik or "") != 16)
        dup_rows = db.execute(
            select(Person.nik, func.count(Person.id))
            .where(Person.tenant_id == tid)
            .group_by(Person.nik).having(func.count(Person.id) > 1)).all()
    finally:
        db.close()

    report = {
        "tanggal": datetime.now(timezone.utc).isoformat(),
        "database": "SQLite fresh (/tmp) — rehearsal migrasi; produksi = Postgres",
        "file": "sample_data/karyawan_500.xlsx",
        "dry_run": {
            "total_baris": dry["total_rows"],
            "valid": dry["valid_rows"],
            "invalid": dry["invalid_rows"],
        },
        "commit": {"imported": committed},
        "kualitas": {
            "total_person_tenant": len(persons),
            "nik_duplikat": dup_nik,
            "nik_duplikat_detail": [n for n, _ in dup_rows][:10],
            "email_kosong": empty_email,
            "nik_invalid": invalid_nik,
        },
        "verifikasi": {
            "tepat_500_terimpor": committed == 500,
            "nik_duplikat_nol": dup_nik == 0,
        },
    }
    out = ROOT / "demo" / "migration_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nLaporan: {out}")
    ok = committed == 500 and dup_nik == 0 and dry["invalid_rows"] == 0
    print("HASIL:", "LOLOS" if ok else "GAGAL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
