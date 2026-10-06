"""BPA1: bukti potong PPh 21 tahunan pegawai tetap (PAY-011/PAY-006).

Agregasi satu tahun pajak per karyawan dari PayrollLine, lalu:
- PDF dokumen karyawan (diunduh di balik PIN slip yang sama), dan
- ekspor XML massal mengikuti struktur template resmi DJP
  (A1Bulk, diunduh dari pajak.go.id 2026-10-06; urutan elemen
  dicocokkan persis dengan berkas template bpa1.xml).

Pemetaan komponen bersifat eksplisit dan dinyatakan terbuka:
breakdown baris slip memakai kode komponen (gaji_pokok,
tunjangan_pajak, lembur, potongan_jht, potongan_jp, ...). Kolom
yang tidak punya sumber data jujur diisi 0/kosong (honorarium,
zakat, bukti potong sebelumnya), bukan angka karangan.

Batasan: uji unggah nyata ke Coretax tidak dapat dilakukan tanpa
akun DJP; validasi kami adalah parse ulang + kecocokan struktur
dengan template resmi. NIK yang tidak 16 digit memblokir ekspor
(kriteria PAY-006).
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Employment,
    JobInfo,
    LegalEntityInfo,
    PayrollLine,
    PayrollRun,
    Person,
)
from app.services import effective_dating as ed

NIK_RE = re.compile(r"^\d{16}$")
TAX_OBJECT_CODE = "21-100-01"


def valid_nik(nik: str | None) -> bool:
    return bool(nik) and bool(NIK_RE.match(nik.strip()))


def _sum_code(breakdown: dict, *needles: str) -> int:
    total = 0
    for code, amount in (breakdown or {}).items():
        low = str(code).lower()
        if any(n in low for n in needles):
            total += int(amount or 0)
    return total


def _employer_npwp(db: Session, tenant_id, legal_entity_id,
                   as_of: date) -> str | None:
    if legal_entity_id is None:
        return None
    if isinstance(legal_entity_id, str):
        legal_entity_id = uuid.UUID(legal_entity_id)
    info = ed.as_of(db=db, tenant_id=tenant_id, model=LegalEntityInfo,
                    identity_field="legal_entity_id",
                    identity_value=legal_entity_id, as_of_date=as_of)
    if info is None or not info.npwp:
        return None
    return re.sub(r"\D", "", info.npwp) or None


def aggregate_year(db: Session, tenant_id, year: int) -> list[dict]:
    """Satu baris agregat per karyawan yang punya PayrollLine di tahun itu."""
    runs = db.execute(
        select(PayrollRun).where(
            PayrollRun.tenant_id == tenant_id,
            PayrollRun.period.like(f"{year:04d}-%"))
    ).scalars().all()
    run_by_id = {str(r.id): r for r in runs}
    if not runs:
        return []
    lines = db.execute(
        select(PayrollLine).where(
            PayrollLine.tenant_id == tenant_id,
            PayrollLine.payroll_run_id.in_([r.id for r in runs]))
    ).scalars().all()

    emps: dict[str, Employment] = {}
    persons: dict[str, Person] = {}
    grouped: dict[str, list[PayrollLine]] = {}
    for line in lines:
        grouped.setdefault(str(line.employment_id), []).append(line)

    dec31 = date(year, 12, 31)
    out: list[dict] = []
    for employment_id, emp_lines in grouped.items():
        emp = emps.get(employment_id)
        if emp is None:
            emp = db.get(Employment, emp_lines[0].employment_id)
            emps[employment_id] = emp
        person = None
        if emp is not None:
            person = persons.get(str(emp.person_id))
            if person is None:
                person = db.get(Person, emp.person_id)
                persons[str(emp.person_id)] = person
        emp_lines.sort(key=lambda ln: run_by_id[str(ln.payroll_run_id)].period)
        months = sorted({run_by_id[str(ln.payroll_run_id)].period
                         for ln in emp_lines})
        month_nums = [int(m.split("-")[1]) for m in months]
        last_line = emp_lines[-1]

        salary = sum(_sum_code(ln.breakdown, "gaji_pokok")
                     for ln in emp_lines)
        if salary == 0:
            salary = sum(int((ln.inputs_snapshot or {}).get(
                "gaji_pokok", 0) or 0) for ln in emp_lines)
        tax_benefit = sum(_sum_code(ln.breakdown, "tunjangan_pajak")
                          for ln in emp_lines)
        bonus_thr = sum((ln.thr_amount or 0) for ln in emp_lines) + sum(
            _sum_code(ln.breakdown, "bonus", "tantiem", "gratifikasi")
            for ln in emp_lines)
        insurance = sum(
            _sum_code(ln.breakdown, "asuransi", "insurance")
            for ln in emp_lines)
        natura = sum(_sum_code(ln.breakdown, "natura") for ln in emp_lines)
        honorarium = sum(_sum_code(ln.breakdown, "honor") for ln in emp_lines)
        gross = sum(int(ln.gross or 0) for ln in emp_lines)
        other = max(0, gross - salary - tax_benefit - bonus_thr
                    - insurance - natura - honorarium)
        pension = sum(_sum_code(ln.breakdown, "potongan_jht",
                                "potongan_jp") for ln in emp_lines)
        position = ""
        if emp is not None:
            from app.services import dashboard as dash_service
            position = (dash_service.job_title(
                db, tenant_id, emp.id, dec31) or "")[:50]
        full_year = month_nums == list(range(1, 13))
        out.append({
            "employment_id": employment_id,
            "person_name": (person.full_name if person
                            else last_line.person_name),
            "nik": (person.nik if person else last_line.nik) or "",
            "ptkp": last_line.ptkp or "TK/0",
            "position": position,
            "legal_entity_id": str(emp.legal_entity_id) if emp else None,
            "month_start": min(month_nums),
            "month_end": max(month_nums),
            "months_count": len(months),
            "status": "FullYear" if full_year else "Annualized",
            "salary": salary,
            "gross_up": any(
                (run_by_id[str(ln.payroll_run_id)].pph21_method
                 == "gross_up") for ln in emp_lines),
            "tax_benefit": tax_benefit,
            "other_benefit": other,
            "honorarium": honorarium,
            "insurance": insurance,
            "natura": natura,
            "bonus_thr": bonus_thr,
            "pension": pension,
            "gross_total": gross,
            "pph21_withheld": sum(int(ln.pph21 or 0) for ln in emp_lines),
            "take_home_total": sum(int(ln.take_home_pay or 0)
                                   for ln in emp_lines),
        })
    out.sort(key=lambda r: r["person_name"])
    return out


def employers(db: Session, tenant_id, year: int) -> list[dict]:
    rows = aggregate_year(db, tenant_id, year)
    dec31 = date(year, 12, 31)
    by_entity: dict[str | None, dict] = {}
    for row in rows:
        key = row["legal_entity_id"]
        entry = by_entity.setdefault(key, {
            "legal_entity_id": key, "employees": 0, "npwp": None})
        entry["employees"] += 1
    for key, entry in by_entity.items():
        if key:
            entry["npwp"] = _employer_npwp(db, tenant_id, key, dec31)
    return sorted(by_entity.values(), key=lambda e: -e["employees"])


def build_xml(db: Session, tenant_id, year: int,
              legal_entity_id: str | None) -> tuple[bytes, dict]:
    """Bangun XML A1Bulk untuk satu pemberi kerja.

    Mengembalikan (xml_bytes, info). Melempar ValueError dengan
    pesan ramah pengguna untuk NPWP kosong / NIK tidak valid.
    """
    dec31 = date(year, 12, 31)
    npwp = _employer_npwp(db, tenant_id, legal_entity_id, dec31)
    if not npwp or len(npwp) != 16:
        raise ValueError(
            "NPWP pemberi kerja (16 digit) belum diatur pada data "
            "badan hukum untuk karyawan terkait; lengkapi dulu di "
            "menu Organisasi sebelum mengekspor BPA1.")
    rows = [r for r in aggregate_year(db, tenant_id, year)
            if r["legal_entity_id"] == str(legal_entity_id)]
    invalid = [r["person_name"] for r in rows if not valid_nik(r["nik"])]
    if invalid:
        raise ValueError(
            "Ekspor diblokir: NIK tidak valid (harus 16 digit) untuk "
            + ", ".join(sorted(invalid))
            + ". Perbaiki data karyawan dulu (kriteria PAY-006).")
    nitku = npwp + "000000"
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<A1Bulk xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
             f"\t<TIN>{npwp}</TIN>", "\t<ListOfA1>"]
    for r in rows:
        parts.append("\t\t<A1>")
        parts.append("\t\t\t<WorkForSecondEmployer>No"
                     "</WorkForSecondEmployer>")
        parts.append(f"\t\t\t<TaxPeriodMonthStart>{r['month_start']}"
                     "</TaxPeriodMonthStart>")
        parts.append(f"\t\t\t<TaxPeriodMonthEnd>{r['month_end']}"
                     "</TaxPeriodMonthEnd>")
        parts.append(f"\t\t\t<TaxPeriodYear>{year}</TaxPeriodYear>")
        parts.append("\t\t\t<CounterpartOpt>Resident</CounterpartOpt>")
        parts.append('\t\t\t<CounterpartPassport xsi:nil="true"/>')
        parts.append(f"\t\t\t<CounterpartTin>{r['nik']}</CounterpartTin>")
        parts.append(f"\t\t\t<TaxExemptOpt>{escape(r['ptkp'])}"
                     "</TaxExemptOpt>")
        parts.append(f"\t\t\t<StatusOfWithholding>{r['status']}"
                     "</StatusOfWithholding>")
        parts.append(f"\t\t\t<CounterpartPosition>"
                     f"{escape(r['position'] or '-')}"
                     "</CounterpartPosition>")
        parts.append(f"\t\t\t<TaxObjectCode>{TAX_OBJECT_CODE}"
                     "</TaxObjectCode>")
        months_el = r["months_count"] if r["status"] == "Annualized" else 0
        parts.append(f"\t\t\t<NumberOfMonths>{months_el}"
                     "</NumberOfMonths>")
        parts.append(f"\t\t\t<SalaryPensionJhtTht>{r['salary']}"
                     "</SalaryPensionJhtTht>")
        parts.append(f"\t\t\t<GrossUpOpt>"
                     f"{'Yes' if r['gross_up'] else 'No'}</GrossUpOpt>")
        parts.append(f"\t\t\t<IncomeTaxBenefit>{r['tax_benefit']}"
                     "</IncomeTaxBenefit>")
        parts.append(f"\t\t\t<OtherBenefit>{r['other_benefit']}"
                     "</OtherBenefit>")
        parts.append(f"\t\t\t<Honorarium>{r['honorarium']}</Honorarium>")
        parts.append(f"\t\t\t<InsurancePaidByEmployer>{r['insurance']}"
                     "</InsurancePaidByEmployer>")
        parts.append(f"\t\t\t<Natura>{r['natura']}</Natura>")
        parts.append(f"\t\t\t<TantiemBonusThr>{r['bonus_thr']}"
                     "</TantiemBonusThr>")
        parts.append(f"\t\t\t<PensionContributionJhtThtFee>{r['pension']}"
                     "</PensionContributionJhtThtFee>")
        parts.append("\t\t\t<Zakat>0</Zakat>")
        parts.append('\t\t\t<PrevWhTaxSlip xsi:nil="true"/>')
        parts.append("\t\t\t<TaxCertificate>N/A</TaxCertificate>")
        parts.append("\t\t\t<Article21IncomeTax>0</Article21IncomeTax>")
        parts.append(f"\t\t\t<IDPlaceOfBusinessActivity>{nitku}"
                     "</IDPlaceOfBusinessActivity>")
        parts.append(f"\t\t\t<WithholdingDate>{year}-12-31"
                     "</WithholdingDate>")
        parts.append("\t\t</A1>")
    parts.append("\t</ListOfA1>")
    parts.append("</A1Bulk>")
    xml = "\n".join(parts) + "\n"
    info = {"npwp": npwp, "employees": len(rows), "year": year}
    return xml.encode("utf-8"), info


def render_bpa1_pdf(row: dict, year: int, employer_name: str,
                    employer_npwp: str | None) -> bytes:
    """Dokumen BPA1 satu karyawan (format formulir A1 yang ringkas)."""
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table)

    from app.services.payslip import _rp, _table_style

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    bold = styles["Heading3"]

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm,
                            bottomMargin=16 * mm, leftMargin=16 * mm,
                            rightMargin=16 * mm,
                            title=f"BPA1 {year} - {row['person_name']}")
    story = []
    story.append(Paragraph(
        f"<b>BUKTI PEMOTONGAN PAJAK PENGHASILAN PASAL 21 BAGI PEGAWAI "
        f"TETAP (BPA1)</b>", bold))
    story.append(Paragraph(
        f"Tahun Pajak {year} &nbsp;|&nbsp; Pemotong: "
        f"{escape(employer_name)}"
        + (f" (NPWP {employer_npwp})" if employer_npwp else ""), normal))
    story.append(Spacer(1, 6 * mm))
    identity = [
        ["Nama", row["person_name"]],
        ["NIK", row["nik"]],
        ["PTKP", row["ptkp"]],
        ["Jabatan", row["position"] or "-"],
        ["Masa bekerja", f"Bulan {row['month_start']} s.d. "
                         f"{row['month_end']} ({row['months_count']} bulan)"],
        ["Status bukti potong", row["status"]],
    ]
    t = Table(identity, colWidths=[48 * mm, 110 * mm])
    t.setStyle(_table_style())
    story.append(t)
    story.append(Spacer(1, 6 * mm))
    amounts = [
        ["Gaji setahun", _rp(row["salary"])],
        ["Tunjangan PPh", _rp(row["tax_benefit"])],
        ["Tunjangan lainnya / lembur", _rp(row["other_benefit"])],
        ["Honorarium", _rp(row["honorarium"])],
        ["Asuransi dibayar pemberi kerja", _rp(row["insurance"])],
        ["Natura", _rp(row["natura"])],
        ["Tantiem, bonus, gratifikasi, THR", _rp(row["bonus_thr"])],
        ["Penghasilan bruto setahun", _rp(row["gross_total"])],
        ["Iuran pensiun / JHT (pengurang)", _rp(row["pension"])],
        ["PPh Pasal 21 telah dipotong setahun",
         _rp(row["pph21_withheld"])],
        ["Take home pay setahun (total slip)", _rp(row["take_home_total"])],
    ]
    t2 = Table(amounts, colWidths=[90 * mm, 68 * mm])
    t2.setStyle(_table_style())
    story.append(t2)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Dokumen ini dihasilkan HRIS-X dari data payroll yang tercatat. "
        "PPh terutang setahun dihitung pemberi kerja dengan metode yang "
        "sama pada slip gaji bulanan; angka di atas adalah agregat slip "
        "Januari-Desember tahun pajak berjalan. Simpan sebagai bukti "
        "potong untuk pelaporan SPT Tahunan Anda.", normal))
    doc.build(story)
    return buf.getvalue()
