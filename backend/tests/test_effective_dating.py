"""Uji layanan effective dating (level service)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import MAX_DATE, JobInfo
from app.services import effective_dating as ed


def _insert(db, ctx, emp_id, valid_from, job_id, event="Mutasi", reason="Uji"):
    return ed.insert_record(
        db=db,
        tenant_id=ctx["ta"].id,
        model=JobInfo,
        identity_field="employment_id",
        identity_value=emp_id,
        valid_from=valid_from,
        values={"job_id": job_id, "org_unit_id": ctx["ou"].id,
                "location_id": ctx["loc_b"].id, "manager_employment_id": None},
        event=event,
        event_reason=reason,
        created_by=_admin_id(db, ctx),
    )


def _admin_id(db, ctx):
    from app.models import User
    from sqlalchemy import select
    return db.execute(
        select(User.id).where(User.email == "admin_a@x.id")
    ).scalar_one()


def _asof(db, ctx, emp_id, d):
    return ed.as_of(
        db=db, tenant_id=ctx["ta"].id, model=JobInfo,
        identity_field="employment_id", identity_value=emp_id, as_of_date=d,
    )


def test_insert_otomatis_menutup_record_lama(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    r1 = _insert(db, ctx, emp, date(2024, 1, 1), ctx["job_stf"].id)
    r2 = _insert(db, ctx, emp, date(2024, 6, 1), ctx["job_mgr"].id)
    db.refresh(r1)
    assert r1.valid_to == date(2024, 5, 31)
    assert r2.valid_from == date(2024, 6, 1)
    assert r2.valid_to == MAX_DATE


def test_insert_mundur_memotong_dan_mengisi_celah(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    _insert(db, ctx, emp, date(2024, 1, 1), ctx["job_stf"].id)
    _insert(db, ctx, emp, date(2024, 9, 1), ctx["job_mgr"].id)
    tengah = _insert(db, ctx, emp, date(2024, 4, 1), ctx["job_stf"].id,
                     event="Koreksi historis")
    db.refresh(tengah)
    # Record pertama tertutup H-1, record baru berakhir sebelum record berikut.
    first = _asof(db, ctx, emp, date(2024, 3, 31))
    assert first.valid_to == date(2024, 3, 31)
    assert tengah.valid_from == date(2024, 4, 1)
    assert tengah.valid_to == date(2024, 8, 31)


def test_seq_no_untuk_dua_perubahan_sehari(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    d = date(2024, 5, 5)
    r1 = _insert(db, ctx, emp, d, ctx["job_stf"].id)
    r2 = _insert(db, ctx, emp, d, ctx["job_mgr"].id)
    assert (r1.seq_no, r2.seq_no) == (1, 2)
    assert r1.valid_to == r2.valid_to  # satu rantai tanggal yang sama
    aktif = _asof(db, ctx, emp, d)
    assert aktif.id == r2.id  # seq_no terbesar yang berlaku


def test_as_of_deterministik(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    _insert(db, ctx, emp, date(2024, 1, 1), ctx["job_stf"].id)
    a = _asof(db, ctx, emp, date(2024, 3, 15))
    b = _asof(db, ctx, emp, date(2024, 3, 15))
    assert a is not None and b is not None and a.id == b.id


def test_record_masa_depan_tak_mempengaruhi_hari_ini(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    _insert(db, ctx, emp, date(2024, 1, 1), ctx["job_stf"].id)
    masa_depan = date.today() + timedelta(days=60)
    _insert(db, ctx, emp, masa_depan, ctx["job_mgr"].id, event="Promosi")
    hari_ini = _asof(db, ctx, emp, date.today())
    assert hari_ini.job_id == ctx["job_stf"].id
    nanti = _asof(db, ctx, emp, masa_depan)
    assert nanti.job_id == ctx["job_mgr"].id


def test_correct_mengubah_tanpa_menambah_riwayat(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    r1 = _insert(db, ctx, emp, date(2024, 1, 1), ctx["job_stf"].id)
    n_before = len(ed.timeline(db=db, tenant_id=ctx["ta"].id, model=JobInfo,
                               identity_field="employment_id",
                               identity_value=emp))
    rec, old = ed.correct_record(
        db=db, tenant_id=ctx["ta"].id, model=JobInfo, record_id=r1.id,
        values={"location_id": ctx["loc_c"].id},
    )
    assert old["location_id"] == ctx["loc_b"].id
    assert rec.location_id == ctx["loc_c"].id
    n_after = len(ed.timeline(db=db, tenant_id=ctx["ta"].id, model=JobInfo,
                              identity_field="employment_id",
                              identity_value=emp))
    assert n_after == n_before  # correct tidak menambah riwayat


def test_correct_menolak_ubah_kunci_riwayat(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    r1 = _insert(db, ctx, emp, date(2024, 1, 1), ctx["job_stf"].id)
    with pytest.raises(ValueError):
        ed.correct_record(
            db=db, tenant_id=ctx["ta"].id, model=JobInfo, record_id=r1.id,
            values={"valid_from": date(2024, 2, 1)},
        )


def test_timeline_terurut_kronologis(ctx):
    db = ctx["db"]
    emp = ctx["e_staff"].id
    for d in (date(2024, 1, 1), date(2024, 6, 1), date(2024, 3, 1)):
        _insert(db, ctx, emp, d, ctx["job_stf"].id)
    tl = ed.timeline(db=db, tenant_id=ctx["ta"].id, model=JobInfo,
                     identity_field="employment_id", identity_value=emp)
    tanggal = [r.valid_from for r in tl]
    assert tanggal == sorted(tanggal)


def test_detect_retro_impact():
    period = ed.detect_retro_impact(date(2026, 6, 15), today=date(2026, 9, 30))
    assert period == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert ed.detect_retro_impact(date(2026, 10, 1), today=date(2026, 9, 30)) == []


def test_event_reason_wajib(ctx):
    db = ctx["db"]
    with pytest.raises(ValueError):
        ed.insert_record(
            db=db, tenant_id=ctx["ta"].id, model=JobInfo,
            identity_field="employment_id", identity_value=ctx["e_staff"].id,
            valid_from=date(2024, 1, 1),
            values={"job_id": ctx["job_stf"].id, "org_unit_id": ctx["ou"].id,
                    "location_id": ctx["loc_b"].id},
            event="", event_reason="", created_by=_admin_id(db, ctx),
        )
