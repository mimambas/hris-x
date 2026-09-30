"""Layanan effective dating generik (PRD 15.2, PLT-010 s.d. PLT-013).

Satu library untuk semua blok bertanggal efektif (JobInfo, CompInfo, ...).
Tidak ada implementasi ganda di modul lain.

Semantik:
- Setiap record: valid_from, valid_to (default 9999-12-31), seq_no.
- insert_record: record baru menutup record yang tercakup pada
  (valid_from_baru - 1 hari). Record masa depan tidak memengaruhi
  tampilan hari ini (dijamin oleh as_of).
- >1 perubahan di hari yang sama: seq_no bertambah, record terbaru
  (seq_no terbesar) yang berlaku.
- correct_record: membetulkan record yang salah TANPA menambah riwayat.
  Aksi berbeda dari insert, izin berbeda (PRD 15.2).
- detect_retro_impact: stub daftar periode payroll bulanan yang terdampak
  perubahan bertanggal mundur; dipakai modul payroll (S8).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MAX_DATE

# Kolom yang tidak boleh diubah lewat correct_record (kunci riwayat).
_PROTECTED_FIELDS = frozenset(
    {"id", "tenant_id", "valid_from", "valid_to", "seq_no", "created_by_user_id"}
)


def insert_record(
    *,
    db: Session,
    tenant_id,
    model,
    identity_field: str,
    identity_value,
    valid_from: date,
    values: dict,
    event: str,
    event_reason: str,
    created_by,
) :
    """Sisipkan record bertanggal efektif baru; otomatis menutup record lama.

    Mengembalikan record baru yang sudah di-flush (belum commit).
    """
    if not event or not event_reason:
        raise ValueError("event dan event_reason wajib diisi (CHR-004)")

    ident = getattr(model, identity_field) == identity_value
    in_tenant = model.tenant_id == tenant_id

    # Rantai perubahan di tanggal yang sama? -> seq_no bertambah.
    same_day = (
        db.execute(
            select(model)
            .where(ident, in_tenant, model.valid_from == valid_from)
            .order_by(model.seq_no.desc())
        )
        .scalars()
        .all()
    )
    if same_day:
        latest = same_day[0]
        seq_no = latest.seq_no + 1
        valid_to = latest.valid_to
    else:
        # Tutup semua record yang tercakup tanggal baru (H-1).
        covering = (
            db.execute(
                select(model).where(
                    ident, in_tenant, model.valid_from <= valid_from, model.valid_to >= valid_from
                )
            )
            .scalars()
            .all()
        )
        for rec in covering:
            rec.valid_to = valid_from - timedelta(days=1)
        # valid_to record baru = sehari sebelum record berikutnya (jika ada).
        nxt = (
            db.execute(
                select(model)
                .where(ident, in_tenant, model.valid_from > valid_from)
                .order_by(model.valid_from.asc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        valid_to = (nxt.valid_from - timedelta(days=1)) if nxt else MAX_DATE
        seq_no = 1

    record = model(
        tenant_id=tenant_id,
        valid_from=valid_from,
        valid_to=valid_to,
        seq_no=seq_no,
        event=event,
        event_reason=event_reason,
        created_by_user_id=created_by,
        **{identity_field: identity_value},
        **values,
    )
    db.add(record)
    db.flush()
    return record


def correct_record(
    *,
    db: Session,
    tenant_id,
    model,
    record_id,
    values: dict,
) :
    """Betulkan record yang salah tanpa menambah riwayat.

    Mengembalikan (record, old_values). Melempar KeyError bila record
    tidak ada di tenant ini; ValueError bila mencoba mengubah kunci riwayat.
    """
    record = db.get(model, record_id)
    if record is None or record.tenant_id != tenant_id:
        raise KeyError(f"{model.__tablename__} id={record_id} tidak ditemukan")

    forbidden = _PROTECTED_FIELDS.intersection(values.keys())
    if forbidden:
        raise ValueError(
            f"Field {sorted(forbidden)} tidak boleh diubah via correct; gunakan insert."
        )

    old_values = {}
    for key, new_value in values.items():
        if not hasattr(record, key):
            raise ValueError(f"Field '{key}' tidak dikenal di {model.__tablename__}")
        old_values[key] = getattr(record, key)
        setattr(record, key, new_value)
    db.flush()
    return record, old_values


def as_of(
    *,
    db: Session,
    tenant_id,
    model,
    identity_field: str,
    identity_value,
    as_of_date: date,
):
    """Record yang berlaku pada tanggal tertentu; None bila tidak ada.

    Deterministik: hasil untuk tanggal yang sama selalu sama (PLT-012).
    """
    stmt = (
        select(model)
        .where(
            getattr(model, identity_field) == identity_value,
            model.tenant_id == tenant_id,
            model.valid_from <= as_of_date,
            model.valid_to >= as_of_date,
        )
        .order_by(model.valid_from.desc(), model.seq_no.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def timeline(
    *,
    db: Session,
    tenant_id,
    model,
    identity_field: str,
    identity_value,
) -> list:
    """Riwayat lengkap untuk satu identitas, terurut kronologis (PLT-011)."""
    stmt = (
        select(model)
        .where(
            getattr(model, identity_field) == identity_value,
            model.tenant_id == tenant_id,
        )
        .order_by(model.valid_from.asc(), model.seq_no.asc())
    )
    return db.execute(stmt).scalars().all()


def detect_retro_impact(backdated_from: date, today: date | None = None) -> list[str]:
    """Daftar periode payroll bulanan ("YYYY-MM") yang terdampak perubahan
    bertanggal mundur (PLT-013).

    Stub siap dipakai modul payroll S8: payroll yang terkunci pada periode
    tersebut harus dihitung ulang via retro. Belum memeriksa status kunci
    periode (belum ada modul payroll di S1).
    """
    today = today or date.today()
    if backdated_from > today:
        return []
    periods: list[str] = []
    y, m = backdated_from.year, backdated_from.month
    while (y, m) <= (today.year, today.month):
        periods.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return periods
