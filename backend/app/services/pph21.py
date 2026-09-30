"""Engine PPh 21 pegawai tetap (Sprint 4).

Metode (sesuai wording PRD PAY-003 versi ringkas tugas Sprint 4):
  PPh 21 bulanan = pajak tahunan progresif atas bruto tahunan / 12;
  penyesuaian Desember = pajak tahunan aktual - akumulasi Jan-Nov.

PENTING (kejujuran, lihat ADR-0007): ini BUKAN tarif TER bulanan
PMK 168/2023 (yang dipakai PRD 11.3 untuk Jan-Nov). Metode ini dipilih
agar angka bisa dihitung tangan dan direkonsiliasi pada demo Sprint 4;
TER + 200 golden test konsultan pajak adalah pekerjaan lanjutan (S9).

Aturan yang dipakai:
- Lapisan tarif progresif UU HPP: 5% (s.d. 60jt), 15% (60-250jt),
  25% (250-500jt), 30% (500jt-5M), 35% (>5M).
- PTKP tahunan sesuai daftar resmi.
- Biaya jabatan 5% bruto, maks Rp500rb/bln (Rp6jt/thn).
- Pengurang iuran karyawan: JHT 2% + JP 1% dari upah.
- PKP dibulatkan ke bawah ke ribuan penuh.
- Metode: gross (karyawan menanggung), gross_up (tunjangan pajak
  diiterasi hingga konvergen), net (pajak ditanggung pemberi kerja;
  angka pajaknya sama dengan gross_up, penyajiannya beda).
"""

from __future__ import annotations

from app.services.formula import rupiah

# PTKP tahunan (rupiah).
PTKP_ANNUAL: dict[str, int] = {
    "TK/0": 54_000_000,
    "TK/1": 58_500_000,
    "TK/2": 63_000_000,
    "TK/3": 67_500_000,
    "K/0": 58_500_000,
    "K/1": 63_000_000,
    "K/2": 67_500_000,
    "K/3": 72_000_000,
}

# (batas_atas_lapisan, tarif)
TAX_BRACKETS: list[tuple[float, float]] = [
    (60_000_000, 0.05),
    (250_000_000, 0.15),
    (500_000_000, 0.25),
    (5_000_000_000, 0.30),
    (float("inf"), 0.35),
]

BIAYA_JABATAN_RATE = 0.05
BIAYA_JABATAN_MAX_ANNUAL = 6_000_000  # Rp500rb x 12
# Pengurang iuran pensiun karyawan: JHT 2% + JP 1%.
EMPLOYEE_PENSION_RATE = 0.03

PPH21_METHODS = ("gross", "gross_up", "net")


def validate_ptkp(ptkp: str) -> str:
    code = (ptkp or "").strip().upper()
    if code not in PTKP_ANNUAL:
        raise ValueError(
            f"PTKP '{ptkp}' tidak dikenal (daftar: {sorted(PTKP_ANNUAL)})"
        )
    return code


def progressive_tax(pkp: int) -> int:
    """Pajak progresif atas Penghasilan Kena Pajak (integer rupiah)."""
    remaining = max(0, pkp)
    tax = 0.0
    lower = 0.0
    for upper, rate in TAX_BRACKETS:
        if remaining <= 0:
            break
        taxable = min(remaining, upper - lower)
        tax += taxable * rate
        remaining -= taxable
        lower = upper
    return rupiah(tax)


def annual_tax(
    gross_annual: int,
    ptkp: str,
    pension_annual: int = 0,
) -> int:
    """Pajak tahunan: (bruto - biaya jabatan - iuran pensiun - PTKP) progresif."""
    ptkp_code = validate_ptkp(ptkp)
    biaya_jabatan = min(BIAYA_JABATAN_RATE * gross_annual, BIAYA_JABATAN_MAX_ANNUAL)
    neto = gross_annual - biaya_jabatan - pension_annual
    pkp = max(0, neto - PTKP_ANNUAL[ptkp_code])
    pkp = int(pkp // 1000 * 1000)  # ribuan penuh ke bawah
    return progressive_tax(pkp)


def _pension_annual(gross_monthly: int) -> int:
    return rupiah(EMPLOYEE_PENSION_RATE * gross_monthly * 12)


def monthly_tax(
    gross_monthly: int,
    ptkp: str,
    method: str = "gross",
    irregular: int = 0,
) -> int:
    """PPh 21 satu bulan.

    ``irregular`` = penghasilan tidak teratur bulan itu (THR, retro, bonus):
    masuk bruto tahunan lalu dibagi 12 (penyederhanaan, lihat ADR-0007).

    gross_up/net: iterasi tunjangan pajak hingga konvergen (maks 100x);
    tunjangan itu sendiri menambah dasar pengenaan.
    """
    if method not in PPH21_METHODS:
        raise ValueError(f"Metode PPh 21 '{method}' tidak dikenal {PPH21_METHODS}")
    validate_ptkp(ptkp)

    def tax_for(base_monthly: int) -> int:
        annual_gross = base_monthly * 12 + irregular
        return rupiah(
            annual_tax(annual_gross, ptkp, _pension_annual(base_monthly)) / 12
        )

    if method == "gross":
        return tax_for(gross_monthly)

    # gross_up & net: cari tunjangan A sehingga A = tax(gross + A).
    allowance = 0
    for _ in range(100):
        nxt = tax_for(gross_monthly + allowance)
        if nxt == allowance:
            return nxt
        allowance = nxt
    raise ValueError("Iterasi gross-up tidak konvergen")


def december_adjustment(
    gross_ytd_actual: int,
    ptkp: str,
    tax_paid_ytd: int,
    pension_ytd_actual: int = 0,
) -> int:
    """Penyesuaian Desember = pajak tahunan aktual - akumulasi Jan-Nov.

    Bisa negatif (kelebihan bayar) — dikembalikan apa adanya agar
    rekonsiliasi tahunan pas; penanganan kelebihan bayar adalah
    kebijakan perusahaan (lihat ADR-0007).
    """
    actual = annual_tax(gross_ytd_actual, ptkp, pension_ytd_actual)
    return actual - tax_paid_ytd


# ---------------------------------------------------------------------------
# Iuran BPJS — info beban perusahaan (tidak memotong take-home).
# Nilai 2026 sebagai konstanta; tarif/batas berubah tiap tahun sehingga
# pada produksi harus menjadi rule pack bertanggal efektif (ADR-0007).
# ---------------------------------------------------------------------------
BPJS_KES_CAP = 12_000_000
BPJS_JP_CAP = 10_547_300


def employer_bpjs(upah: int) -> dict[str, int]:
    """Iuran BPJS porsi pemberi kerja dari upah (gaji_pokok+tunjangan_tetap)."""
    kes_base = min(upah, BPJS_KES_CAP)
    jp_base = min(upah, BPJS_JP_CAP)
    return {
        "bpjs_kesehatan_perusahaan": rupiah(0.04 * kes_base),
        # JKK 0,54% = tengah kelompok risiko; aktual 0,24%-1,74% per entitas.
        "jkk_perusahaan": rupiah(0.0054 * upah),
        "jkm_perusahaan": rupiah(0.003 * upah),
        "jht_perusahaan": rupiah(0.037 * upah),
        "jp_perusahaan": rupiah(0.02 * jp_base),
    }
