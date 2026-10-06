"""PAY-014: perhitungan final pay & pesangon per alasan terminasi.

Tabel bracket masa kerja dan faktor per alasan TERKONFIGURASI per
tenant; nilai bawaan mengikuti PP 35/2021 Pasal 40 (pesangon 1-9
bulan, UPMK 2-10 bulan mulai masa kerja 3 tahun) dan faktor pengali
alasan PHK pada pasal-pasal terkait (resign -> tanpa pesangon/UPMK,
pensiun 1,75x, meninggal 2x, efisiensi merugi 0,5x, dst. dapat diganti
dari UI). Upah dasar = gaji pokok + tunjangan tetap (komponen
CompInfo terakhir berlaku pada tanggal terminasi).

Komponen final pay:
- sisa gaji: prorata hari kerja (Senin-Jumat) bulan terminasi.
- UPH sisa cuti: saldo cuti tahunan tahun berjalan x upah/25
  (konvensi tarif harian yang sama dengan potongan mangkir).
- pesangon / UPMK: bracket masa kerja x faktor alasan x upah.
- kompensasi PKWT (bila faktor alasan menandainya): masa kerja
  (tahun) x upah, menggantikan pesangon & UPMK.
- penyesuaian manual (+/-).
Potongan: sisa pinjaman aktif (BEN-003) dan PPh 21 final atas
pesangon+UPMK+kompensasi yang dibayar sekaligus (lapisan 0/5/15/25
persen di atas 50/100/500 juta). Sisa gaji & UPH tidak dipajaki di
modul ini (dapat masuk payroll reguler terakhir).
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CompInfo,
    Employment,
    FinalPay,
    JobInfo,
    LeaveBalance,
    LeaveType,
    Loan,
    SeveranceBracket,
    SeveranceReasonFactor,
)

# Bracket bawaan PP 35/2021 Pasal 40 ayat (2) dan (3):
# (min_years, max_years|None, bulan upah).
DEFAULT_BRACKETS: dict[str, list[tuple[float, float | None, int]]] = {
    "pesangon": [
        (0, 1, 1), (1, 2, 2), (2, 3, 3), (3, 4, 4), (4, 5, 5),
        (5, 6, 6), (6, 7, 7), (7, 8, 8), (8, None, 9),
    ],
    "upmk": [
        (3, 6, 2), (6, 9, 3), (9, 12, 4), (12, 15, 5),
        (15, 18, 6), (18, 21, 7), (21, 24, 8), (24, None, 10),
    ],
}

# Faktor bawaan per alasan katalog lifecycle tenant:
# (faktor pesangon, faktor UPMK, UPH termasuk, kompensasi PKWT).
DEFAULT_REASON_FACTORS: dict[str, tuple[float, float, bool, bool]] = {
    "Pengunduran diri": (0.0, 0.0, True, False),
    "PHK": (1.0, 1.0, True, False),
    "Kontrak berakhir": (0.0, 0.0, True, True),
    "Lainnya": (1.0, 1.0, True, False),
}
FALLBACK_FACTOR = (1.0, 1.0, True, False)

# Lapisan PPh 21 final pembayaran sekaligus (batas atas, tarif).
TAX_LAYERS: list[tuple[int, float]] = [
    (50_000_000, 0.0),
    (100_000_000, 0.05),
    (500_000_000, 0.15),
    (10**15, 0.25),
]


def ensure_defaults(db: Session, tenant_id: uuid.UUID) -> None:
    """Seed tabel konfigurasi tenant bila masih kosong (idempotent)."""
    has_brackets = db.scalar(
        select(SeveranceBracket.id)
        .where(SeveranceBracket.tenant_id == tenant_id)
        .limit(1)
    )
    if has_brackets is None:
        for component, rows in DEFAULT_BRACKETS.items():
            for min_y, max_y, months in rows:
                db.add(SeveranceBracket(
                    tenant_id=tenant_id, component=component,
                    min_years=min_y, max_years=max_y, months=months,
                ))
    has_factors = db.scalar(
        select(SeveranceReasonFactor.id)
        .where(SeveranceReasonFactor.tenant_id == tenant_id)
        .limit(1)
    )
    if has_factors is None:
        for reason, (fp, fu, uph, pkwt) in DEFAULT_REASON_FACTORS.items():
            db.add(SeveranceReasonFactor(
                tenant_id=tenant_id, reason=reason,
                pesangon_factor=fp, upmk_factor=fu,
                uph_included=uph, pkwt_compensation=pkwt,
            ))
    db.flush()


def get_config(db: Session, tenant_id: uuid.UUID) -> dict:
    ensure_defaults(db, tenant_id)
    brackets = db.scalars(
        select(SeveranceBracket)
        .where(SeveranceBracket.tenant_id == tenant_id)
        .order_by(SeveranceBracket.component, SeveranceBracket.min_years)
    ).all()
    factors = db.scalars(
        select(SeveranceReasonFactor)
        .where(SeveranceReasonFactor.tenant_id == tenant_id)
        .order_by(SeveranceReasonFactor.reason)
    ).all()
    return {"brackets": list(brackets), "reason_factors": list(factors)}


def replace_config(
    db: Session,
    tenant_id: uuid.UUID,
    brackets: list[dict],
    reason_factors: list[dict],
) -> dict:
    """Ganti seluruh tabel konfigurasi tenant (PUT semantik)."""
    for row in db.scalars(
        select(SeveranceBracket).where(SeveranceBracket.tenant_id == tenant_id)
    ).all():
        db.delete(row)
    for row in db.scalars(
        select(SeveranceReasonFactor).where(
            SeveranceReasonFactor.tenant_id == tenant_id
        )
    ).all():
        db.delete(row)
    db.flush()
    for b in brackets:
        db.add(SeveranceBracket(tenant_id=tenant_id, **b))
    for f in reason_factors:
        db.add(SeveranceReasonFactor(tenant_id=tenant_id, **f))
    db.flush()
    return get_config(db, tenant_id)


def _bracket_months(
    brackets: list[SeveranceBracket], component: str, years: float
) -> int:
    for b in brackets:
        if b.component != component:
            continue
        lo = float(b.min_years)
        hi = float(b.max_years) if b.max_years is not None else float("inf")
        if lo <= years < hi:
            return int(b.months)
    return 0


def _working_days(start: date, end: date) -> int:
    """Hari kerja Senin-Jumat inklusif di antara dua tanggal."""
    days = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def termination_info(db: Session, employment_id: uuid.UUID) -> dict | None:
    """Kejadian terminasi terakhir pada JobInfo employment (bila ada)."""
    row = db.scalars(
        select(JobInfo)
        .where(
            JobInfo.employment_id == employment_id,
            JobInfo.event == "termination",
        )
        .order_by(JobInfo.valid_from.desc(), JobInfo.seq_no.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return {"date": row.valid_from, "reason": row.event_reason}


def _monthly_wage(db: Session, employment_id: uuid.UUID, on: date) -> int:
    """Upah dasar sebulan: gaji pokok + tunjangan tetap versi CompInfo
    yang berlaku pada tanggal terminasi."""
    row = db.scalars(
        select(CompInfo)
        .where(
            CompInfo.employment_id == employment_id,
            CompInfo.valid_from <= on,
        )
        .order_by(CompInfo.valid_from.desc(), CompInfo.seq_no.desc())
        .limit(1)
    ).first()
    if row is None:
        return 0
    comps = row.components or {}
    total = 0
    for key in ("gaji_pokok", "tunjangan_tetap"):
        val = comps.get(key, 0)
        if isinstance(val, (int, float)):
            total += int(val)
    return total


def _leave_remaining(db: Session, tenant_id: uuid.UUID, employment_id: uuid.UUID,
                     year: int) -> int:
    """Sisa cuti tahunan (hari) pada tahun terminasi."""
    annual = db.scalar(
        select(LeaveType.id).where(
            LeaveType.tenant_id == tenant_id,
            LeaveType.code == "cuti_tahunan",
        )
    )
    if annual is None:
        return 0
    total = db.scalar(
        select(LeaveBalance.remaining).where(
            LeaveBalance.tenant_id == tenant_id,
            LeaveBalance.employment_id == employment_id,
            LeaveBalance.leave_type_id == annual,
            LeaveBalance.year == year,
        )
    )
    return int(total or 0)


def _loan_outstanding(db: Session, employment_id: uuid.UUID) -> int:
    rows = db.scalars(
        select(Loan.remaining_total).where(
            Loan.employment_id == employment_id,
            Loan.status == "active",
        )
    ).all()
    return int(sum(rows))


def final_tax(amount: int) -> int:
    """PPh 21 final progresif atas pembayaran pesangon sekaligus."""
    tax = 0.0
    prev = 0
    for cap, rate in TAX_LAYERS:
        if amount <= prev:
            break
        taxable = min(amount, cap) - prev
        tax += taxable * rate
        prev = cap
    return int(round(tax))


def compute(
    db: Session,
    tenant_id: uuid.UUID,
    employment: Employment,
    reason: str,
    termination_date: date,
    adjustments: list[dict] | None = None,
) -> dict:
    """Hitung rincian final pay (tanpa menyimpan)."""
    cfg = get_config(db, tenant_id)
    brackets: list[SeveranceBracket] = cfg["brackets"]
    factors: list[SeveranceReasonFactor] = cfg["reason_factors"]

    factor_row = next((f for f in factors if f.reason == reason), None)
    if factor_row is not None:
        f_pes = float(factor_row.pesangon_factor)
        f_upmk = float(factor_row.upmk_factor)
        uph_included = bool(factor_row.uph_included)
        pkwt = bool(factor_row.pkwt_compensation)
        factor_source = "config"
    else:
        f_pes, f_upmk, uph_included, pkwt = FALLBACK_FACTOR
        factor_source = "default"

    wage = _monthly_wage(db, employment.id, termination_date)
    days_total = (termination_date - employment.start_date).days
    years = max(days_total, 0) / 365.25

    # Sisa gaji: prorata hari kerja bulan terminasi.
    month_start = termination_date.replace(day=1)
    last_day = calendar.monthrange(
        termination_date.year, termination_date.month
    )[1]
    month_end = termination_date.replace(day=last_day)
    worked = _working_days(month_start, termination_date)
    total_wd = _working_days(month_start, month_end)
    sisa_gaji = int(round(wage * worked / total_wd)) if total_wd else 0

    pesangon = upmk = kompensasi = 0
    pes_months = upmk_months = 0
    if pkwt:
        kompensasi = int(round(years * wage))
    else:
        pes_months = _bracket_months(brackets, "pesangon", years)
        upmk_months = _bracket_months(brackets, "upmk", years)
        pesangon = int(round(f_pes * pes_months * wage))
        upmk = int(round(f_upmk * upmk_months * wage))

    leave_days = 0
    sisa_cuti = 0
    if uph_included:
        leave_days = _leave_remaining(
            db, tenant_id, employment.id, termination_date.year
        )
        sisa_cuti = int(round(leave_days * wage / 25)) if wage else 0

    adj = adjustments or []
    adj_total = sum(int(a.get("amount", 0)) for a in adj)

    gross = sisa_gaji + sisa_cuti + pesangon + upmk + kompensasi + adj_total
    loan = _loan_outstanding(db, employment.id)
    tax = final_tax(pesangon + upmk + kompensasi)
    net = gross - loan - tax

    breakdown = {
        "sisa_gaji": sisa_gaji,
        "hari_kerja_terpakai": worked,
        "hari_kerja_sebulan": total_wd,
        "sisa_cuti_hari": leave_days,
        "sisa_cuti": sisa_cuti,
        "pesangon_bulan": pes_months,
        "pesangon_faktor": f_pes,
        "pesangon": pesangon,
        "upmk_bulan": upmk_months,
        "upmk_faktor": f_upmk,
        "upmk": upmk,
        "kompensasi_pkwt": kompensasi,
        "uph_termasuk": uph_included,
        "faktor_sumber": factor_source,
        "adjustments": adj,
    }
    return {
        "termination_date": termination_date,
        "reason": reason,
        "years_of_service": round(years, 3),
        "monthly_wage": wage,
        "breakdown": breakdown,
        "gross_total": gross,
        "loan_deduction": loan,
        "tax_amount": tax,
        "net_amount": net,
    }


def active_final_pay(db: Session, employment_id: uuid.UUID) -> FinalPay | None:
    """Final pay yang sedang berjalan (draft/finalized/paid) per employment."""
    return db.scalars(
        select(FinalPay)
        .where(FinalPay.employment_id == employment_id)
        .order_by(FinalPay.created_at.desc())
        .limit(1)
    ).first()
