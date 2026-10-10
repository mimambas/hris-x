"""Jurnal payroll per cost center (PAY-015).

Dari snapshot PayrollLine satu run dibuat jurnal akuntansi berpasangan
per cost center: total debit = total kredit per cost center dan per
run (kriteria penerimaan PRD). Dihitung live dari snapshot tersimpan —
tanpa tabel baru; run tetap sumber kebenaran.

Cost center karyawan = cost center aktif yang terhubung ke unit
organisasi pada JobInfo berlaku di akhir periode run; karyawan tanpa
pemetaan masuk ember "TANPA-CC" agar jurnal tetap seimbang.

Peta akun baku (dapat dibaca akuntansi; kode akun tetap):
  Debit  6101 Beban Gaji & Tunjangan        (bruto - reimbursement)
         6102 Beban THR
         6103 Beban Retro (penyesuaian)
         6104 Beban Reimbursement
         6105 Beban BPJS Perusahaan
         6106 Beban PPh 21 Ditanggung Perusahaan
  Kredit 2101 Hutang Gaji Bersih            (take-home pay)
         2102 Hutang PPh 21
         2103 Hutang BPJS Kesehatan         (karyawan + perusahaan)
         2104 Hutang BPJS Ketenagakerjaan   (karyawan + perusahaan)
         2105 Hutang Pinjaman Karyawan     (cicilan dipotong)
         2106 Hutang Potongan Lainnya
"""

from __future__ import annotations

import calendar
import csv
import io
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CostCenterInfo, JobInfo, PayrollLine
from app.services import effective_dating as ed

NO_CC_CODE = "TANPA-CC"
NO_CC_NAME = "Tanpa cost center"

# (kode, nama, sisi wajar)
_ACCOUNTS: list[tuple[str, str, str]] = [
    ("6101", "Beban Gaji & Tunjangan", "debit"),
    ("6102", "Beban THR", "debit"),
    ("6103", "Beban Retro (penyesuaian)", "debit"),
    ("6104", "Beban Reimbursement", "debit"),
    ("6105", "Beban BPJS Perusahaan", "debit"),
    ("6106", "Beban PPh 21 Ditanggung Perusahaan", "debit"),
    ("2101", "Hutang Gaji Bersih", "kredit"),
    ("2102", "Hutang PPh 21", "kredit"),
    ("2103", "Hutang BPJS Kesehatan", "kredit"),
    ("2104", "Hutang BPJS Ketenagakerjaan", "kredit"),
    ("2105", "Hutang Pinjaman Karyawan", "kredit"),
    ("2106", "Hutang Potongan Lainnya", "kredit"),
]


def period_end(period: str) -> date:
    """Tanggal jurnal = hari terakhir bulan periode "YYYY-MM"."""
    year, month = (int(x) for x in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


def _cost_center_of(db: Session, tenant_id, line: PayrollLine,
                    on: date) -> tuple[str, str]:
    """(kode, nama) cost center karyawan pada tanggal jurnal."""
    job = ed.as_of(
        db=db, tenant_id=tenant_id, model=JobInfo,
        identity_field="employment_id", identity_value=line.employment_id,
        as_of_date=on)
    if job is None or job.org_unit_id is None:
        return NO_CC_CODE, NO_CC_NAME
    cc = db.execute(
        select(CostCenterInfo).where(
            CostCenterInfo.tenant_id == tenant_id,
            CostCenterInfo.org_unit_id == job.org_unit_id,
            CostCenterInfo.valid_from <= on,
            CostCenterInfo.valid_to >= on,
            CostCenterInfo.is_active.is_(True),
        ).order_by(
            CostCenterInfo.valid_from.desc(), CostCenterInfo.seq_no.desc())
    ).scalars().first()
    if cc is None:
        return NO_CC_CODE, NO_CC_NAME
    return cc.code, cc.name


def _line_amounts(line: PayrollLine) -> dict[str, int]:
    """Jumlah per kode akun dari satu snapshot baris payroll."""
    bd = line.breakdown or {}
    kes_ee = int(bd.get("potongan_bpjs_kes", 0) or 0)
    tk_ee = int(bd.get("potongan_jht", 0) or 0) + int(
        bd.get("potongan_jp", 0) or 0)
    cicilan = int(bd.get("cicilan_pinjaman", 0) or 0)
    if not cicilan:
        cicilan = int((line.inputs_snapshot or {}).get(
            "loan_installment", 0) or 0)
    other_ded = (int(line.total_deductions) - kes_ee - tk_ee - cicilan)
    er = line.employer_cost or {}
    kes_er = int(er.get("bpjs_kesehatan_perusahaan", 0) or 0)
    tk_er = sum(int(er.get(k, 0) or 0) for k in (
        "jkk_perusahaan", "jkm_perusahaan", "jht_perusahaan",
        "jp_perusahaan"))
    er_total = sum(int(v or 0) for v in er.values())
    reimb = int(line.reimbursement_amount)
    tax_er = int(line.pph21) if line.pph21_borne_by == "employer" else 0
    return {
        "6101": int(line.gross) - reimb,
        "6102": int(line.thr_amount),
        "6103": int(line.retro_amount),
        "6104": reimb,
        "6105": er_total,
        "6106": tax_er,
        "2101": int(line.take_home_pay),
        "2102": int(line.pph21),
        "2103": kes_ee + kes_er,
        "2104": tk_ee + tk_er,
        "2105": cicilan,
        "2106": other_ded,
    }


def build_journal(db: Session, tenant_id, run) -> dict:
    """Jurnal lengkap satu run: entri per (cost center, akun), agregat
    per cost center, dan status keseimbangan debit=kredit."""
    on = period_end(run.period)
    lines = db.execute(
        select(PayrollLine).where(PayrollLine.payroll_run_id == run.id)
    ).scalars().all()
    names = {code: (name, side) for code, name, side in _ACCOUNTS}
    # agg[(cc_code, cc_name, account_code)] = jumlah bertanda pada sisi
    # wajar akunnya (negatif artinya berbalik sisi saat disajikan).
    agg: dict[tuple[str, str, str], int] = {}
    for line in lines:
        cc_code, cc_name = _cost_center_of(db, tenant_id, line, on)
        for acc, amount in _line_amounts(line).items():
            if amount == 0:
                continue
            key = (cc_code, cc_name, acc)
            agg[key] = agg.get(key, 0) + amount

    entries: list[dict] = []
    per_cc: dict[tuple[str, str], dict] = {}
    for (cc_code, cc_name, acc), amount in sorted(agg.items()):
        name, side = names[acc]
        debit = credit = 0
        if side == "debit":
            debit, credit = (amount, 0) if amount >= 0 else (0, -amount)
        else:
            debit, credit = (0, amount) if amount >= 0 else (-amount, 0)
        if debit == 0 and credit == 0:
            continue
        entries.append({
            "cost_center_code": cc_code, "cost_center_name": cc_name,
            "account_code": acc, "account_name": name,
            "debit": debit, "credit": credit,
        })
        bucket = per_cc.setdefault((cc_code, cc_name), {
            "cost_center_code": cc_code, "cost_center_name": cc_name,
            "total_debit": 0, "total_credit": 0,
        })
        bucket["total_debit"] += debit
        bucket["total_credit"] += credit

    cc_rows = []
    for bucket in sorted(per_cc.values(),
                         key=lambda b: b["cost_center_code"]):
        bucket["balanced"] = (
            bucket["total_debit"] == bucket["total_credit"])
        cc_rows.append(bucket)
    total_debit = sum(e["debit"] for e in entries)
    total_credit = sum(e["credit"] for e in entries)
    return {
        "run_id": run.id,
        "period": run.period,
        "status": run.status,
        "journal_date": on,
        "entries": entries,
        "per_cost_center": cc_rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "balanced": total_debit == total_credit,
    }


def render_csv(journal: dict) -> str:
    """CSV jurnal (pemisah ';' ramah Excel Indonesia) siap impor ke
    sistem akuntansi; baris TOTAL menegaskan debit = kredit."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Periode", "Tanggal", "Kode Cost Center",
                "Nama Cost Center", "Kode Akun", "Nama Akun",
                "Debit", "Kredit", "Keterangan"])
    ket = f"Jurnal payroll {journal['period']}"
    for e in journal["entries"]:
        w.writerow([journal["period"],
                    journal["journal_date"].isoformat(),
                    e["cost_center_code"], e["cost_center_name"],
                    e["account_code"], e["account_name"],
                    e["debit"], e["credit"], ket])
    w.writerow([journal["period"], journal["journal_date"].isoformat(),
                "", "", "", "TOTAL", journal["total_debit"],
                journal["total_credit"],
                "Seimbang" if journal["balanced"] else "TIDAK SEIMBANG"])
    return buf.getvalue()
