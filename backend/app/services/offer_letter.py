"""Surat penawaran kerja (e-offer) PDF (Sprint 6).

- PDF: reportlab, mengikuti pola app/services/payslip.py.
- Tanpa tanda tangan digital (penyederhanaan, lihat ADR-0009).
"""

from __future__ import annotations

import io
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _rp(n: int) -> str:
    return f"Rp{n:,}".replace(",", ".")


_BULAN = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei",
    6: "Juni", 7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober",
    11: "November", 12: "Desember",
}


def _tgl(d) -> str:
    if d is None:
        return "-"
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {_BULAN[d.month]} {d.year}"


def render_offer_letter_pdf(
    *,
    company_name: str,
    candidate_name: str,
    position_title: str,
    salary: int,
    start_date: date,
    contract_type: str,
    expires_at: datetime,
    offer_no: str,
) -> bytes:
    """Render surat penawaran kerja satu kandidat -> bytes PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Surat Penawaran Kerja - {candidate_name}",
    )
    title = ParagraphStyle("title", fontSize=16, leading=20,
                           fontName="Helvetica-Bold", alignment=1)
    sub = ParagraphStyle("sub", fontSize=11, leading=14,
                         fontName="Helvetica", alignment=1,
                         spaceBefore=2, textColor=colors.HexColor("#444444"))
    normal = ParagraphStyle("normal", fontSize=10, leading=15)
    small = ParagraphStyle("small", fontSize=8, leading=11,
                           textColor=colors.HexColor("#555555"))
    bold = ParagraphStyle("bold", fontSize=10, leading=15,
                          fontName="Helvetica-Bold")

    story = [
        Paragraph(company_name, title),
        Paragraph("SURAT PENAWARAN KERJA", sub),
        Paragraph(f"Nomor: {offer_no}", small),
        Spacer(1, 8),
        Paragraph(f"Jakarta, {_tgl(date.today())}", normal),
        Spacer(1, 4),
        Paragraph("Kepada Yth.", normal),
        Paragraph(f"<b>{candidate_name}</b>", bold),
        Paragraph("di tempat", normal),
        Spacer(1, 6),
        Paragraph(
            "Dengan hormat,<br/>Berdasarkan hasil proses rekrutmen, kami "
            "dengan senang hati menawarkan posisi berikut kepada Saudara/i:",
            normal,
        ),
        Spacer(1, 6),
    ]

    rows = [
        [Paragraph("<b>Posisi</b>", normal), Paragraph(position_title, normal)],
        [Paragraph("<b>Jenis kontrak</b>", normal), Paragraph(contract_type, normal)],
        [Paragraph("<b>Gaji pokok</b>", normal), Paragraph(_rp(salary), normal)],
        [Paragraph("<b>Tanggal mulai kerja</b>", normal), Paragraph(_tgl(start_date), normal)],
        [Paragraph("<b>Berlaku hingga</b>", normal),
         Paragraph(_tgl(expires_at) + " pukul " +
                   expires_at.strftime("%H:%M") + " WIB", normal)],
    ]
    t = Table(rows, colWidths=[55 * mm, 105 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#cccccc")),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.extend([
        Paragraph(
            "Penawaran ini berlaku hingga tanggal yang tertera di atas. "
            "Apabila Saudara/i menerima penawaran ini, harap melakukan "
            "konfirmasi melalui tautan penerimaan yang kami kirimkan "
            "sebelum batas waktu berakhir.", normal),
        Spacer(1, 8),
        Paragraph(
            "Demikian surat penawaran ini kami sampaikan. Atas perhatian "
            "Saudara/i, kami ucapkan terima kasih.", normal),
        Spacer(1, 20),
        Paragraph("Hormat kami,", normal),
        Spacer(1, 24),
        Paragraph(f"<b>{company_name}</b>", bold),
        Paragraph("Departemen SDM", normal),
        Spacer(1, 12),
        Paragraph(
            "Dokumen ini dibuat secara elektronik dan sah tanpa tanda "
            "tangan basah (Sprint 6: tanpa e-sign).", small),
    ])
    doc.build(story)
    return buf.getvalue()
