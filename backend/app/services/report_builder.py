"""Report builder self-service (ANL-002, PRD 13.4).

Objek laporan adalah katalog terkurasi (bukan tabel mentah):
setiap objek digerbang izin RBP view objeknya, dan field sensitif
(gaji pada objek payroll) digerbang izin objek payroll. Baris
dibatasi target population pemanggil melalui
population.get_visible_person_ids, konsisten dengan laporan
standar ANL-001. Filter/grup/agregasi divalidasi terhadap katalog;
tidak ada SQL yang dibangun dari input mentah pengguna.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRecord,
    Employment,
    LeaveRequest,
    LeaveType,
    OvertimeRequest,
    PayrollLine,
    PayrollRun,
    Person,
)
from app.services import dashboard as dash
from app.services import effective_dating as ed
from app.services import population as population_service
from app.services import rbp as rbp_service

MAX_ROWS = 1000


# ------------------------------------------------------------- katalog
def _f(label: str, type_: str, permission: tuple[str, str] | None = None):
    return {"label": label, "type": type_, "permission": permission}


OBJECTS: dict[str, dict] = {
    "karyawan": {
        "label": "Karyawan",
        "permission": ("person", "view"),
        "fields": {
            "nama": _f("Nama", "str"),
            "nik": _f("NIK", "str"),
            "unit_organisasi": _f("Unit organisasi", "str"),
            "jabatan": _f("Jabatan", "str"),
            "status": _f("Status employment", "str"),
            "jenis_kontrak": _f("Jenis kontrak", "str"),
            "tanggal_masuk": _f("Tanggal masuk", "date"),
            "jenis_kelamin": _f("Jenis kelamin", "str"),
            "ptkp": _f("PTKP", "str"),
        },
    },
    "absensi": {
        "label": "Absensi",
        "permission": ("attendance", "view"),
        "fields": {
            "nama": _f("Nama", "str"),
            "tanggal": _f("Tanggal", "date"),
            "status": _f("Status", "str"),
            "check_in": _f("Check-in", "str"),
            "check_out": _f("Check-out", "str"),
            "menit_telat": _f("Menit telat", "num"),
        },
    },
    "cuti": {
        "label": "Cuti",
        "permission": ("leave", "view"),
        "fields": {
            "nama": _f("Nama", "str"),
            "jenis_cuti": _f("Jenis cuti", "str"),
            "tanggal_mulai": _f("Tanggal mulai", "date"),
            "tanggal_selesai": _f("Tanggal selesai", "date"),
            "jumlah_hari": _f("Jumlah hari", "num"),
            "status": _f("Status", "str"),
        },
    },
    "lembur": {
        "label": "Lembur",
        "permission": ("overtime", "view"),
        "fields": {
            "nama": _f("Nama", "str"),
            "tanggal": _f("Tanggal", "date"),
            "jam": _f("Jam lembur", "num"),
            "status": _f("Status", "str"),
        },
    },
    "payroll": {
        "label": "Payroll",
        "permission": ("payroll", "view"),
        "fields": {
            "nama": _f("Nama", "str"),
            "periode": _f("Periode (YYYY-MM)", "str"),
            "gaji_kotor": _f("Gaji kotor", "num", ("payroll", "view")),
            "potongan": _f("Total potongan", "num", ("payroll", "view")),
            "gaji_bersih": _f("Gaji bersih", "num", ("payroll", "view")),
        },
    },
}


def _names(db: Session, tenant_id) -> dict[str, str]:
    rows = db.execute(
        select(Employment.id, Person.full_name).join(
            Person, Person.id == Employment.person_id)
        .where(Employment.tenant_id == tenant_id)
    ).all()
    return {str(eid): name for eid, name in rows}


def _visible_employment_ids(db: Session, user) -> set[str] | None:
    visible = population_service.get_visible_person_ids(db, user)
    if visible is None:
        return None
    rows = db.execute(
        select(Employment.id).where(
            Employment.tenant_id == user.tenant_id,
            Employment.person_id.in_(visible))
    ).scalars().all()
    return {str(r) for r in rows}


def _filter_scope(rows: list[dict], scope: set[str] | None) -> list[dict]:
    if scope is None:
        return rows
    return [r for r in rows if r["_employment_id"] in scope]


def _load_karyawan(db: Session, user) -> list[dict]:
    today = date.today()
    emps = dash.employments_active_as_of(db, user.tenant_id, today, None)
    persons = dash._person_map(db, user.tenant_id, emps)
    comp = {}
    rows = []
    from app.models import CompInfo

    for e in emps:
        p = persons.get(e.person_id)
        ci = ed.as_of(db=db, tenant_id=user.tenant_id, model=CompInfo,
                      identity_field="employment_id", identity_value=e.id,
                      as_of_date=today)
        rows.append({
            "_employment_id": str(e.id),
            "nama": p.full_name if p else "-",
            "nik": p.nik if p else "-",
            "unit_organisasi": dash.org_unit_name(db, user.tenant_id,
                                                  e.id, today),
            "jabatan": dash.job_title(db, user.tenant_id, e.id, today),
            "status": e.status,
            "jenis_kontrak": dash.contract_type(db, user.tenant_id,
                                                e.id, today),
            "tanggal_masuk": e.start_date.isoformat(),
            "jenis_kelamin": (p.gender if p else None) or "-",
            "ptkp": (ci.ptkp if ci else None) or "-",
        })
    return rows


def _load_absensi(db: Session, user) -> list[dict]:
    names = _names(db, user.tenant_id)
    recs = db.execute(
        select(AttendanceRecord).where(
            AttendanceRecord.tenant_id == user.tenant_id,
            AttendanceRecord.is_current.is_(True))
        .order_by(AttendanceRecord.date.desc())
    ).scalars().all()
    return [{
        "_employment_id": str(r.employment_id),
        "nama": names.get(str(r.employment_id), "-"),
        "tanggal": r.date.isoformat(),
        "status": r.status,
        "check_in": r.check_in.strftime("%H:%M") if r.check_in else "-",
        "check_out": (r.check_out.strftime("%H:%M")
                      if r.check_out else "-"),
        "menit_telat": r.late_minutes or 0,
    } for r in recs]


def _load_cuti(db: Session, user) -> list[dict]:
    names = _names(db, user.tenant_id)
    types = {str(t.id): t.name for t in db.execute(
        select(LeaveType).where(LeaveType.tenant_id == user.tenant_id)
    ).scalars().all()}
    reqs = db.execute(
        select(LeaveRequest).where(LeaveRequest.tenant_id == user.tenant_id)
        .order_by(LeaveRequest.start_date.desc())
    ).scalars().all()
    return [{
        "_employment_id": str(r.employment_id),
        "nama": names.get(str(r.employment_id), "-"),
        "jenis_cuti": types.get(str(r.leave_type_id), "-"),
        "tanggal_mulai": r.start_date.isoformat(),
        "tanggal_selesai": r.end_date.isoformat(),
        "jumlah_hari": r.days,
        "status": r.status,
    } for r in reqs]


def _load_lembur(db: Session, user) -> list[dict]:
    names = _names(db, user.tenant_id)
    reqs = db.execute(
        select(OvertimeRequest).where(
            OvertimeRequest.tenant_id == user.tenant_id)
        .order_by(OvertimeRequest.date.desc())
    ).scalars().all()
    return [{
        "_employment_id": str(r.employment_id),
        "nama": names.get(str(r.employment_id), "-"),
        "tanggal": r.date.isoformat(),
        "jam": float(r.hours or 0),
        "status": r.status,
    } for r in reqs]


def _load_payroll(db: Session, user) -> list[dict]:
    runs = {str(r.id): r for r in db.execute(
        select(PayrollRun).where(PayrollRun.tenant_id == user.tenant_id)
    ).scalars().all()}
    lines = db.execute(
        select(PayrollLine).where(PayrollLine.tenant_id == user.tenant_id)
    ).scalars().all()
    rows = []
    for r in lines:
        run = runs.get(str(r.payroll_run_id))
        rows.append({
            "_employment_id": str(r.employment_id),
            "nama": r.person_name or "-",
            "periode": (run.period if run else "-"),
            "gaji_kotor": float(r.gross or 0),
            "potongan": float(r.total_deductions or 0),
            "gaji_bersih": float(r.take_home_pay or 0),
        })
    rows.sort(key=lambda x: x["periode"], reverse=True)
    return rows


LOADERS = {
    "karyawan": _load_karyawan,
    "absensi": _load_absensi,
    "cuti": _load_cuti,
    "lembur": _load_lembur,
    "payroll": _load_payroll,
}


# ------------------------------------------------------------ katalog API
def can_use_object(db: Session, user, obj_key: str) -> bool:
    spec = OBJECTS.get(obj_key)
    if spec is None:
        return False
    obj, act = spec["permission"]
    return (user.is_superadmin
            or rbp_service.has_permission(db, user, obj, act))


def field_allowed(db: Session, user, obj_key: str, field_key: str) -> bool:
    meta = OBJECTS[obj_key]["fields"].get(field_key)
    if meta is None:
        return False
    perm = meta["permission"]
    if perm is None:
        return True
    obj, act = perm
    return (user.is_superadmin
            or rbp_service.has_permission(db, user, obj, act))


def catalog_for(db: Session, user) -> list[dict]:
    out = []
    for key, spec in OBJECTS.items():
        if not can_use_object(db, user, key):
            continue
        fields = []
        for fkey, meta in spec["fields"].items():
            if not field_allowed(db, user, key, fkey):
                continue
            fields.append({"key": fkey, "label": meta["label"],
                           "type": meta["type"],
                           "sensitive": meta["permission"] is not None})
        out.append({"key": key, "label": spec["label"], "fields": fields})
    return out


# ------------------------------------------------------------------ run
def _cast(value, type_: str):
    if value is None:
        return None
    if type_ == "num":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Nilai filter numerik tidak valid: {value!r}")
    return str(value)


def _match(cell, op: str, value, type_: str) -> bool:
    left = _cast(cell, type_)
    if op == "contains":
        return str(value).lower() in str(left).lower()
    if op == "antara":
        if not isinstance(value, list) or len(value) != 2:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Operator 'antara' butuh tepat dua nilai [dari, sampai]")
        lo, hi = _cast(value[0], type_), _cast(value[1], type_)
        return left is not None and lo <= left <= hi
    right = _cast(value, type_)
    if left is None:
        return op == "neq"
    return {
        "eq": left == right,
        "neq": left != right,
        "gt": left > right,
        "gte": left >= right,
        "lt": left < right,
        "lte": left <= right,
    }[op]


def run_report(db: Session, user, spec_in: dict) -> dict:
    obj_key = spec_in.get("object")
    if obj_key not in OBJECTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Objek laporan tidak dikenal")
    if not can_use_object(db, user, obj_key):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Anda tidak punya izin melihat objek {OBJECTS[obj_key]['label']}")
    fields_meta = OBJECTS[obj_key]["fields"]
    fields: list[str] = spec_in.get("fields") or []
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Pilih minimal satu field")
    for fkey in fields:
        if fkey not in fields_meta or not field_allowed(db, user, obj_key,
                                                         fkey):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Field {fkey!r} tidak tersedia untuk izin Anda")

    rows = _filter_scope(LOADERS[obj_key](db, user),
                         _visible_employment_ids(db, user))

    for flt in spec_in.get("filters") or []:
        fkey = flt.get("field")
        if fkey not in fields_meta or not field_allowed(db, user, obj_key,
                                                         fkey):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Field filter {fkey!r} tidak tersedia untuk izin Anda")
        op = flt.get("op") or "eq"
        if op not in ("eq", "neq", "gt", "gte", "lt", "lte", "contains",
                      "antara"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Operator tidak dikenal: {op}")
        type_ = fields_meta[fkey]["type"]
        rows = [r for r in rows
                if _match(r.get(fkey), op, flt.get("value"), type_)]

    group_by = spec_in.get("group_by")
    total = len(rows)
    if group_by:
        if group_by not in fields_meta or not field_allowed(
                db, user, obj_key, group_by):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Field pengelompokan tidak tersedia untuk izin Anda")
        fn = spec_in.get("aggregate_fn") or "count"
        agg_field = spec_in.get("aggregate_field")
        if fn not in ("count", "sum", "avg", "min", "max"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Fungsi agregasi tidak dikenal: {fn}")
        if fn != "count":
            if not agg_field or fields_meta.get(agg_field, {}).get(
                    "type") != "num" or not field_allowed(
                        db, user, obj_key, agg_field):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Agregasi sum/avg/min/max butuh field numerik yang "
                    "diizinkan")
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(str(r.get(group_by)), []).append(r)
        out_rows = []
        for gval in sorted(groups):
            members = groups[gval]
            if fn == "count":
                agg = len(members)
            else:
                vals = [_cast(m.get(agg_field), "num") for m in members]
                vals = [v for v in vals if v is not None]
                agg = {"sum": sum(vals), "avg": (sum(vals) / len(vals)
                                                 if vals else 0),
                       "min": min(vals) if vals else 0,
                       "max": max(vals) if vals else 0}[fn]
            out_rows.append({group_by: gval, "agregat": round(agg, 2)
                             if isinstance(agg, float) else agg})
        columns = [
            {"key": group_by, "label": fields_meta[group_by]["label"],
             "type": fields_meta[group_by]["type"]},
            {"key": "agregat",
             "label": (f"Jumlah baris" if fn == "count" else
                       f"{fn.upper()} "
                       f"{fields_meta[agg_field]['label']}"),
             "type": "num"},
        ]
        return {"columns": columns, "rows": out_rows,
                "total_rows": len(out_rows)}

    sort_by = spec_in.get("sort_by")
    if sort_by:
        if sort_by not in fields_meta:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Field urutan tidak dikenal")
        reverse = (spec_in.get("sort_dir") or "asc") == "desc"
        type_ = fields_meta[sort_by]["type"]
        rows.sort(key=lambda r: (_cast(r.get(sort_by), type_)
                                 if r.get(sort_by) is not None else ""),
                  reverse=reverse)
    limit = spec_in.get("limit") or 500
    limit = max(1, min(int(limit), MAX_ROWS))
    rows = rows[:limit]
    columns = [{"key": f, "label": fields_meta[f]["label"],
                "type": fields_meta[f]["type"]} for f in fields]
    out_rows = [{f: r.get(f) for f in fields} for r in rows]
    return {"columns": columns, "rows": out_rows, "total_rows": total}


def build_xlsx(columns: list[dict], rows: list[dict],
               sheet: str = "Laporan") -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31] or "Laporan"
    ws.append([c["label"] for c in columns])
    for r in rows:
        ws.append([r.get(c["key"]) for c in columns])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
