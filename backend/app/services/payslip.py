"""Slip gaji PDF + file transfer bank (PAY-007, PAY-010).

- PDF: reportlab (gratis, BSD). Tanpa tanda tangan (sesuai scope Sprint 4).
- Transfer: CSV generik (nama, rekening, nominal, berita). Parameter bank
  dicadangkan untuk format spesifik bank (BCA/Mandiri/BRI/BNI) — lihat ADR-0007.
"""

from __future__ import annotations

import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle


def _rp(n: int) -> str:
    return f"Rp{n:,}".replace(",", ".")


# Kode -> label Indonesia untuk baris slip.
_LABELS = {
    "gaji_pokok": "Gaji Pokok",
    "tunjangan_tetap": "Tunjangan Tetap",
    "tunjangan_transport": "Tunjangan Transport",
    "uang_makan": "Uang Makan",
    "lembur": "Upah Lembur",
    "tunjangan_pajak": "Tunjangan Pajak (gross-up)",
    "potongan_bpjs_kes": "Potongan BPJS Kesehatan",
    "potongan_jht": "Potongan JHT",
    "potongan_jp": "Potongan JP",
    "potongan_mangkir": "Potongan Mangkir",
    # Sprint 8 (BEN-001/BEN-003)
    "reimbursement": "Reimbursement Klaim (non-pajak)",
    "cicilan_pinjaman": "Cicilan Pinjaman",
}


def _label(code: str) -> str:
    return _LABELS.get(code, code.replace("_", " ").title())


def render_payslip_pdf(*, line, period: str, company_name: str) -> bytes:
    """Render slip gaji satu karyawan -> bytes PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Slip Gaji {period}",
    )
    title = ParagraphStyle("title", fontSize=16, leading=20,
                           fontName="Helvetica-Bold", alignment=1)
    h2 = ParagraphStyle("h2", fontSize=11, leading=14, fontName="Helvetica-Bold",
                        spaceBefore=10, spaceAfter=4)
    normal = ParagraphStyle("normal", fontSize=9, leading=12)
    small = ParagraphStyle("small", fontSize=8, leading=10,
                           textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("right", fontSize=9, leading=12, alignment=2)

    story = [
        Paragraph(company_name, title),
        Paragraph(f"SLIP GAJI — Periode {period}", ParagraphStyle(
            "sub", parent=title, fontSize=12, spaceBefore=2)),
        Spacer(1, 6),
    ]

    info = [
        [Paragraph("<b>Nama</b>", normal), Paragraph(line.person_name, normal),
         Paragraph("<b>NIK</b>", normal), Paragraph(line.nik, normal)],
        [Paragraph("<b>PTKP</b>", normal), Paragraph(line.ptkp, normal),
         Paragraph("<b>Rekening</b>", normal),
         Paragraph(f"{line.bank_name or '-'} / {line.bank_account_no or '-'}",
                   normal)],
    ]
    t_info = Table(info, colWidths=[28 * mm, 55 * mm, 28 * mm, 55 * mm])
    t_info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_info)

    story.append(Paragraph("Penghasilan", h2))
    breakdown: dict = line.breakdown or {}
    kinds: dict = (line.inputs_snapshot or {}).get("kinds", {})
    earn_rows = [[Paragraph("<b>Komponen</b>", normal),
                 Paragraph("<b>Jumlah</b>", right)]]
    for code, amount in breakdown.items():
        if kinds.get(code, "earning") != "earning":
            continue
        earn_rows.append([Paragraph(_label(code), normal),
                          Paragraph(_rp(amount), right)])
    if line.thr_amount:
        earn_rows.append([Paragraph("THR", normal),
                          Paragraph(_rp(line.thr_amount), right)])
    if line.retro_amount:
        earn_rows.append([Paragraph("Selisih Retro", normal),
                          Paragraph(_rp(line.retro_amount), right)])
    t_earn = Table(earn_rows, colWidths=[110 * mm, 56 * mm])
    t_earn.setStyle(_table_style())
    story.append(t_earn)

    story.append(Paragraph("Potongan", h2))
    ded_rows = [[Paragraph("<b>Komponen</b>", normal),
                 Paragraph("<b>Jumlah</b>", right)]]
    for code, amount in breakdown.items():
        if kinds.get(code) != "deduction":
            continue
        ded_rows.append([Paragraph(_label(code), normal),
                         Paragraph(_rp(amount), right)])
    if line.pph21 and line.pph21_borne_by == "employee":
        ded_rows.append([Paragraph("PPh 21", normal),
                         Paragraph(_rp(line.pph21), right)])
    t_ded = Table(ded_rows, colWidths=[110 * mm, 56 * mm])
    t_ded.setStyle(_table_style())
    story.append(t_ded)

    story.append(Paragraph("Ringkasan", h2))
    gross_total = (line.gross or 0) + (line.thr_amount or 0) + (
        line.retro_amount or 0)
    summary = [
        [Paragraph("Total Bruto", normal), Paragraph(_rp(gross_total), right)],
        [Paragraph("Total Potongan", normal),
         Paragraph(_rp(line.total_deductions or 0), right)],
        [Paragraph("PPh 21", normal),
         Paragraph(f"{_rp(line.pph21 or 0)}"
                   f"{' (ditanggung perusahaan)' if line.pph21_borne_by == 'employer' else ''}",
                   right)],
    ]
    if getattr(line, "reimbursement_amount", 0):
        summary.append(
            [Paragraph("Reimbursement Klaim (non-pajak)", normal),
             Paragraph(_rp(line.reimbursement_amount or 0), right)])
    summary.append(
        [Paragraph("<b>Take-Home Pay</b>", normal),
         Paragraph(f"<b>{_rp(line.take_home_pay or 0)}</b>", right)])
    t_sum = Table(summary, colWidths=[110 * mm, 56 * mm])
    t_sum.setStyle(_table_style())
    story.append(t_sum)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Dokumen ini dihasilkan otomatis oleh HRIS-X dari data payroll "
        "yang terkunci. Total take-home = total penghasilan - total potongan"
        + (" - PPh 21" if line.pph21_borne_by == "employee" else "")
        + ".",
        small,
    ))
    doc.build(story)
    return buf.getvalue()


def _table_style() -> TableStyle:
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2f2f2")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ])


def render_transfer_csv(*, lines, period: str, bank: str = "bca") -> str:
    """File transfer: CSV (nama, rekening, nominal, berita).

    ``bank`` dicadangkan untuk format spesifik bank (saat ini semua bank
    memakai format generik yang sama; lihat ADR-0007).
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["nama", "no_rekening", "nominal", "berita"])
    for line in lines:
        w.writerow([
            line.person_name,
            line.bank_account_no or "",
            line.take_home_pay or 0,
            f"Gaji {period}",
        ])
    return buf.getvalue()
