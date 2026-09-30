"""Validasi data kepegawaian Indonesia (Sprint 3, CHR-005).

Dipakai di dua tempat: API (skema Pydantic memanggil helper ini) dan
impor Excel (validasi per baris). Semua helper mengembalikan nilai yang
sudah dinormalisasi, atau mengangkat ValueError dengan pesan Indonesia.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# Status PTKP sesuai PMK 168/2023: TK/K/KI × tanggungan 0-3.
PTKP_STATUSES = [
    "TK/0",
    "TK/1",
    "TK/2",
    "TK/3",
    "K/0",
    "K/1",
    "K/2",
    "K/3",
    "KI/0",
    "KI/1",
    "KI/2",
    "KI/3",
]

_NIK_RE = re.compile(r"^\d{16}$")
_DIGITS_RE = re.compile(r"^\d+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _blank(value: str | None) -> bool:
    return value is None or not str(value).strip()


def validate_nik(nik: str) -> str:
    """NIK: wajib 16 digit angka."""
    nik = str(nik or "").strip()
    if not _NIK_RE.match(nik):
        raise ValueError("NIK harus 16 digit angka")
    return nik


def validate_npwp(npwp: str | None) -> str | None:
    """NPWP format baru: 16 digit. Boleh kosong. Titik/strip/spasi diabaikan."""
    if _blank(npwp):
        return None
    digits = re.sub(r"\D", "", str(npwp))
    if not _NIK_RE.match(digits):
        raise ValueError("NPWP harus 16 digit angka (format baru)")
    return digits


def validate_ptkp(ptkp: str | None) -> str:
    """Status PTKP; kosong -> default 'TK/0'."""
    if _blank(ptkp):
        return "TK/0"
    ptkp = str(ptkp).strip().upper().replace(" ", "")
    if ptkp not in PTKP_STATUSES:
        raise ValueError(
            f"Status PTKP '{ptkp}' tidak dikenal. Pilihan: {', '.join(PTKP_STATUSES)}"
        )
    return ptkp


def validate_email(email: str | None) -> str | None:
    """Email opsional; bila diisi harus berformat valid. Dinormalisasi lowercase."""
    if _blank(email):
        return None
    email = str(email).strip()
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Format email '{email}' tidak valid")
    return email.lower()


def validate_bpjs(number: str | None, label: str) -> str | None:
    """Nomor BPJS: digit saja, 10-16 karakter. Boleh kosong."""
    if _blank(number):
        return None
    digits = re.sub(r"\D", "", str(number))
    if not _DIGITS_RE.match(digits) or not 10 <= len(digits) <= 16:
        raise ValueError(f"Nomor {label} harus 10-16 digit angka")
    return digits


def validate_bank_account(number: str | None) -> str | None:
    """Nomor rekening: digit saja, 4-32 karakter. Boleh kosong."""
    if _blank(number):
        return None
    digits = re.sub(r"\D", "", str(number))
    if not _DIGITS_RE.match(digits) or not 4 <= len(digits) <= 32:
        raise ValueError("Nomor rekening harus 4-32 digit angka")
    return digits


def parse_id_date(value) -> date | None:
    """Tanggal fleksibel: objek date/datetime, atau string DD/MM/YYYY,
    DD-MM-YYYY, YYYY-MM-DD. Kosong -> None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Tanggal '{text}' tidak dikenali. Format: DD/MM/YYYY atau YYYY-MM-DD"
    )


def validate_birth_date(value) -> date | None:
    """Tanggal lahir: valid & tidak di masa depan."""
    d = parse_id_date(value)
    if d is not None and d > date.today():
        raise ValueError("Tanggal lahir tidak boleh di masa depan")
    return d


def validate_gender(value: str | None) -> str | None:
    """Jenis kelamin: 'L' (laki-laki) atau 'P' (perempuan); None = tak diisi."""
    if value is None:
        return None
    v = value.strip().upper()
    if v not in ("L", "P"):
        raise ValueError("Jenis kelamin harus 'L' atau 'P'")
    return v
