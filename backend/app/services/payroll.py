"""Orkestrasi payroll Sprint 4: komponen gaji, run, kunci, retro, THR, BPJS.

Alur per karyawan per periode:
  1. Resolve versi komponen & assignment yang berlaku akhir periode
     (effective dating generik, ADR-0001).
  2. Komponen fixed: override assignment -> CompInfo.components (warisan
     Sprint 3) -> default katalog. Formula: dievaluasi topological order
     via app/services/formula.py (tanpa eval/exec).
  3. Bruto -> PPh 21 (app/services/pph21.py) -> THR -> retro -> take-home.
  4. Setiap baris menyimpan snapshot input + breakdown agar bisa
     direkonsiliasi (slip total = jumlah baris).

Uang selalu integer rupiah (PRD 18.4 aturan 3).
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CompAssignment,
    CompAssignmentInfo,
    CompInfo,
    Employment,
    PayrollLine,
    PayrollPolicy,
    PayrollRun,
    Person,
    SalaryComponent,
    SalaryComponentInfo,
)
from app.services import effective_dating as ed
from app.services import lifecycle as lc_service
from app.services import pph21 as pph21_service
from app.services.formula import (
    BUILTIN_VARS,
    FormulaError,
    check_syntax_only,
    evaluate,
    referenced_names,
    rupiah,
    topo_order,
    validate_formula_names,
)

# Variabel bawaan didefinisikan di formula.BUILTIN_VARS (sumber tunggal).

COMPONENT_KINDS = ("earning", "deduction")
CALC_TYPES = ("fixed", "formula")

# Kode pseudo-komponen yang ditambahkan engine (bukan dari katalog).
TUNJANGAN_PAJAK = "tunjangan_pajak"

# Event katalog untuk perubahan struktur gaji (di-seed per tenant).
SALARY_EVENT = "salary_structure"


# ---------------------------------------------------------------------------
# Seed katalog
# ---------------------------------------------------------------------------
# (code, name, kind, calc_type, amount_or_formula, is_taxable, is_bpjs_base, seq)
SALARY_COMPONENTS_SEED: list[tuple] = [
    ("gaji_pokok", "Gaji Pokok", "earning", "fixed", "0",
     True, True, 10),
    ("tunjangan_tetap", "Tunjangan Tetap", "earning", "fixed", "0",
     True, True, 20),
    ("tunjangan_transport", "Tunjangan Transport", "earning", "fixed", "0",
     True, False, 30),
    ("uang_makan", "Uang Makan", "earning", "formula", "hari_kerja * 50000",
     True, False, 40),
    ("lembur", "Upah Lembur", "earning", "formula", "jam_lembur * upah_per_jam",
     True, False, 50),
    ("potongan_bpjs_kes", "Potongan BPJS Kesehatan (1%)", "deduction",
     "formula", "0.01 * min(gaji, 12000000)", False, False, 110),
    ("potongan_jht", "Potongan JHT (2%)", "deduction",
     "formula", "0.02 * gaji", False, False, 120),
    ("potongan_jp", "Potongan JP (1%)", "deduction",
     "formula", "0.01 * min(gaji, 10547300)", False, False, 130),
]


def seed_payroll_catalog(db: Session, tenant_id, created_by=None,
                         valid_from: date | None = None) -> None:
    """Seed 8 komponen gaji standar + policy default. Idempoten."""
    valid_from = valid_from or date(2020, 1, 1)
    get_policy(db, tenant_id)  # pastikan policy ada
    for (code, name, kind, calc_type, amount_or_formula,
         is_taxable, is_bpjs_base, seq) in SALARY_COMPONENTS_SEED:
        comp = (
            db.execute(
                select(SalaryComponent).where(
                    SalaryComponent.tenant_id == tenant_id,
                    SalaryComponent.code == code,
                )
            )
            .scalars()
            .first()
        )
        if comp is None:
            comp = SalaryComponent(tenant_id=tenant_id, code=code, name=name)
            db.add(comp)
            db.flush()
            ed.insert_record(
                db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
                identity_field="component_id", identity_value=comp.id,
                valid_from=valid_from,
                values={
                    "kind": kind, "calc_type": calc_type,
                    "amount_or_formula": amount_or_formula,
                    "is_taxable": is_taxable, "is_bpjs_base": is_bpjs_base,
                    "sequence": seq,
                },
                event=SALARY_EVENT, event_reason="Komponen baru",
                created_by=created_by, event_applies_to="lifecycle",
            )
    db.flush()


def get_policy(db: Session, tenant_id) -> PayrollPolicy:
    """Kebijakan payroll tenant; buat default bila belum ada."""
    policy = (
        db.execute(
            select(PayrollPolicy).where(PayrollPolicy.tenant_id == tenant_id)
        )
        .scalars()
        .first()
    )
    if policy is None:
        policy = PayrollPolicy(tenant_id=tenant_id)
        db.add(policy)
        db.flush()
    return policy


# ---------------------------------------------------------------------------
# Komponen: create / version / validasi formula
# ---------------------------------------------------------------------------
def _slug_code(name: str) -> str:
    code = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return code or "komponen"


def _ensure_unique_code(db: Session, tenant_id, code: str,
                        exclude_id=None) -> str:
    base, i = code, 2
    while True:
        stmt = select(SalaryComponent.id).where(
            SalaryComponent.tenant_id == tenant_id,
            func.lower(SalaryComponent.code) == code.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(SalaryComponent.id != exclude_id)
        if db.execute(stmt.limit(1)).first() is None:
            return code
        code, i = f"{base}_{i}", i + 1


def _tenant_formulas(db: Session, tenant_id, as_of: date,
                     override: tuple | None = None) -> dict[str, str]:
    """{code: formula} seluruh komponen formula tenant per tanggal.

    ``override`` = (component_id, formula_baru) untuk validasi pra-simpan.
    """
    formulas: dict[str, str] = {}
    comps = (
        db.execute(
            select(SalaryComponent).where(SalaryComponent.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    )
    for comp in comps:
        info = ed.as_of(
            db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
            identity_field="component_id", identity_value=comp.id,
            as_of_date=as_of,
        )
        if info is None or info.calc_type != "formula":
            continue
        formula = override[1] if override and override[0] == comp.id else info.amount_or_formula
        formulas[comp.code] = formula
    return formulas


def _validate_component_graph(db: Session, tenant_id, as_of: date,
                              override: tuple | None = None) -> None:
    """Validasi seluruh graf formula tenant: nama dikenal + tanpa siklus."""
    formulas = _tenant_formulas(db, tenant_id, as_of, override)
    codes = {c.code for c in db.execute(
        select(SalaryComponent).where(SalaryComponent.tenant_id == tenant_id)
    ).scalars().all()}
    allowed = codes | set(BUILTIN_VARS)
    for code, formula in formulas.items():
        try:
            validate_formula_names(formula, allowed)
        except FormulaError as e:
            raise ValueError(f"Formula '{code}' tidak valid: {e}")
    try:
        topo_order(formulas)
    except FormulaError as e:
        raise ValueError(str(e))


def create_component(
    *, db: Session, tenant_id, name: str, code: str | None,
    kind: str, calc_type: str, amount_or_formula: str,
    is_taxable: bool = True, is_bpjs_base: bool = False,
    sequence: int = 100, valid_from: date,
    event: str, event_reason: str, created_by,
) -> SalaryComponent:
    """Buat komponen gaji baru (PAY-001). Kode boleh kosong -> otomatis."""
    if kind not in COMPONENT_KINDS:
        raise ValueError(f"kind harus salah satu {COMPONENT_KINDS}")
    if calc_type not in CALC_TYPES:
        raise ValueError(f"calc_type harus salah satu {CALC_TYPES}")
    if calc_type == "fixed":
        try:
            amount = int(str(amount_or_formula).strip())
        except (TypeError, ValueError):
            raise ValueError("Komponen fixed butuh amount integer rupiah")
        if amount < 0:
            raise ValueError("Amount fixed tidak boleh negatif")
        amount_or_formula = str(amount)
    else:
        try:
            check_syntax_only(amount_or_formula)
        except FormulaError as e:
            raise ValueError(f"Formula tidak valid: {e}")

    code = _ensure_unique_code(db, tenant_id, (code or _slug_code(name)).strip())
    comp = SalaryComponent(tenant_id=tenant_id, code=code, name=name.strip())
    db.add(comp)
    db.flush()
    ed.insert_record(
        db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
        identity_field="component_id", identity_value=comp.id,
        valid_from=valid_from,
        values={
            "kind": kind, "calc_type": calc_type,
            "amount_or_formula": amount_or_formula,
            "is_taxable": is_taxable, "is_bpjs_base": is_bpjs_base,
            "sequence": sequence,
        },
        event=event, event_reason=event_reason,
        created_by=created_by, event_applies_to="lifecycle",
    )
    # Validasi graf SETELAH insert agar referensi ke kode baru ikut dicek;
    # rollback oleh pemanggil bila gagal (ValueError -> 422).
    _validate_component_graph(db, tenant_id, valid_from,
                              override=(comp.id, amount_or_formula)
                              if calc_type == "formula" else None)
    return comp


def update_component(
    *, db: Session, tenant_id, component_id, kind: str | None = None,
    calc_type: str | None = None, amount_or_formula: str | None = None,
    is_taxable: bool | None = None, is_bpjs_base: bool | None = None,
    sequence: int | None = None, valid_from: date,
    event: str, event_reason: str, created_by,
) -> SalaryComponentInfo:
    """Versi baru komponen (perubahan rumus/nominal bertanggal efektif)."""
    comp = db.get(SalaryComponent, component_id)
    if comp is None or comp.tenant_id != tenant_id:
        raise KeyError("Komponen tidak ditemukan")
    current = ed.as_of(
        db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
        identity_field="component_id", identity_value=comp.id,
        as_of_date=valid_from,
    )
    values: dict = {}
    new_kind = kind or (current.kind if current else "earning")
    new_calc = calc_type or (current.calc_type if current else "fixed")
    if new_kind not in COMPONENT_KINDS:
        raise ValueError(f"kind harus salah satu {COMPONENT_KINDS}")
    if new_calc not in CALC_TYPES:
        raise ValueError(f"calc_type harus salah satu {CALC_TYPES}")
    new_formula = (
        amount_or_formula
        if amount_or_formula is not None
        else (current.amount_or_formula if current else "0")
    )
    if new_calc == "fixed":
        try:
            amt = int(str(new_formula).strip())
        except (TypeError, ValueError):
            raise ValueError("Komponen fixed butuh amount integer rupiah")
        if amt < 0:
            raise ValueError("Amount fixed tidak boleh negatif")
        new_formula = str(amt)
    else:
        try:
            check_syntax_only(new_formula)
        except FormulaError as e:
            raise ValueError(f"Formula tidak valid: {e}")
    values.update({
        "kind": new_kind, "calc_type": new_calc,
        "amount_or_formula": new_formula,
        "is_taxable": current.is_taxable if current and is_taxable is None else bool(is_taxable),
        "is_bpjs_base": current.is_bpjs_base if current and is_bpjs_base is None else bool(is_bpjs_base),
        "sequence": current.sequence if current and sequence is None else int(sequence or 100),
    })
    record = ed.insert_record(
        db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
        identity_field="component_id", identity_value=comp.id,
        valid_from=valid_from, values=values,
        event=event, event_reason=event_reason,
        created_by=created_by, event_applies_to="lifecycle",
    )
    if new_calc == "formula":
        _validate_component_graph(db, tenant_id, valid_from,
                                  override=(comp.id, new_formula))
    else:
        _validate_component_graph(db, tenant_id, valid_from)
    return record


# ---------------------------------------------------------------------------
# Assignment komponen -> employment
# ---------------------------------------------------------------------------
def assign_component(
    *, db: Session, tenant_id, employment_id, component_id,
    valid_from: date, override_amount: int | None = None,
    is_enabled: bool = True,
    event: str, event_reason: str, created_by,
) -> CompAssignment:
    emp = db.get(Employment, employment_id)
    if emp is None or emp.tenant_id != tenant_id:
        raise KeyError("Employment tidak ditemukan")
    comp = db.get(SalaryComponent, component_id)
    if comp is None or comp.tenant_id != tenant_id:
        raise KeyError("Komponen tidak ditemukan")
    if override_amount is not None and override_amount < 0:
        raise ValueError("override_amount tidak boleh negatif")

    assignment = (
        db.execute(
            select(CompAssignment).where(
                CompAssignment.tenant_id == tenant_id,
                CompAssignment.employment_id == employment_id,
                CompAssignment.component_id == component_id,
            )
        )
        .scalars()
        .first()
    )
    if assignment is None:
        assignment = CompAssignment(
            tenant_id=tenant_id, employment_id=employment_id,
            component_id=component_id,
        )
        db.add(assignment)
        db.flush()
    ed.insert_record(
        db=db, tenant_id=tenant_id, model=CompAssignmentInfo,
        identity_field="assignment_id", identity_value=assignment.id,
        valid_from=valid_from,
        values={"override_amount": override_amount, "is_enabled": is_enabled},
        event=event, event_reason=event_reason,
        created_by=created_by, event_applies_to="lifecycle",
    )
    return assignment


def _active_components(db: Session, tenant_id, as_of: date):
    """[(component, info)] versi berlaku per tanggal, terurut sequence."""
    rows = (
        db.execute(
            select(SalaryComponent).where(SalaryComponent.tenant_id == tenant_id)
            .order_by(SalaryComponent.code)
        )
        .scalars()
        .all()
    )
    out = []
    for comp in rows:
        info = ed.as_of(
            db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
            identity_field="component_id", identity_value=comp.id,
            as_of_date=as_of,
        )
        if info is not None:
            out.append((comp, info))
    out.sort(key=lambda ci: (ci[1].sequence, ci[0].code))
    return out


def _active_assignments(db: Session, tenant_id, employment_id, as_of: date):
    """{component_id: CompAssignmentInfo} yang aktif per tanggal."""
    assigns = (
        db.execute(
            select(CompAssignment).where(
                CompAssignment.tenant_id == tenant_id,
                CompAssignment.employment_id == employment_id,
            )
        )
        .scalars()
        .all()
    )
    out = {}
    for a in assigns:
        info = ed.as_of(
            db=db, tenant_id=tenant_id, model=CompAssignmentInfo,
            identity_field="assignment_id", identity_value=a.id,
            as_of_date=as_of,
        )
        if info is not None and info.is_enabled:
            out[a.component_id] = info
    return out


# ---------------------------------------------------------------------------
# Kalkulasi satu baris
# ---------------------------------------------------------------------------
def working_days(year: int, month: int) -> int:
    """Hari kerja = Senin-Jumat dalam bulan (penyederhanaan: tanpa kalender
    libur nasional; modul kalender libur = pekerjaan lanjutan, ADR-0007)."""
    n = 0
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        if date(year, month, day).weekday() < 5:
            n += 1
    return n


def thr_amount(start_date: date, holiday_date: date, basis: int) -> int:
    """THR Permenaker 6/2016: >=12 bln -> 1x upah; 1-11 bln -> proporsional.

    ``basis`` = gaji_pokok atau total fixed (kebijakan tenant).
    """
    months = (holiday_date.year - start_date.year) * 12 + (
        holiday_date.month - start_date.month
    )
    if holiday_date.day < start_date.day:
        months -= 1
    if months < 1:
        return 0
    if months >= 12:
        return basis
    return rupiah(basis * months / 12)


def _period_bounds(period: str) -> tuple[date, date]:
    try:
        y, m = int(period[0:4]), int(period[5:7])
        assert len(period) == 7 and period[4] == "-"
        assert 1 <= m <= 12
    except (ValueError, AssertionError, IndexError):
        raise ValueError("period harus format 'YYYY-MM'")
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


def evaluate_employment(
    *, db: Session, tenant_id, employment: Employment,
    period: str, method: str, include_thr: bool = False,
    thr_holiday_date: date | None = None,
    overtime_hours: int = 0,
    is_december: bool = False,
    ytd_gross: int = 0, ytd_tax: int = 0, ytd_pension_base: int = 0,
    retro_amount: int = 0, retro_detail: dict | None = None,
) -> dict:
    """Hitung satu baris payroll; kembalikan dict siap simpan ke PayrollLine."""
    if method not in pph21_service.PPH21_METHODS:
        raise ValueError(f"Metode PPh 21 '{method}' tidak dikenal")
    period_start, period_end = _period_bounds(period)
    year, month = period_start.year, period_start.month

    person = db.get(Person, employment.person_id)
    comp_rec = ed.as_of(
        db=db, tenant_id=tenant_id, model=CompInfo,
        identity_field="employment_id", identity_value=employment.id,
        as_of_date=period_end,
    )
    legacy = dict(comp_rec.components) if comp_rec and comp_rec.components else {}
    ptkp = comp_rec.ptkp if comp_rec and comp_rec.ptkp else (person.ptkp if person else "TK/0")
    pph21_service.validate_ptkp(ptkp)

    assigns = _active_assignments(db, tenant_id, employment.id, period_end)
    hari_kerja = working_days(year, month)

    # 1. Fixed dulu (untuk variabel `gaji`), lalu formula topological order.
    values: dict[str, int] = {}
    breakdown: dict[str, int] = {}
    kinds: dict[str, str] = {}
    formulas: dict[str, str] = {}
    ordered_codes: list[str] = []

    for comp, info in _active_components(db, tenant_id, period_end):
        if comp.id not in assigns:
            continue  # tidak di-assign ke karyawan ini
        kinds[comp.code] = info.kind
        ainfo = assigns[comp.id]
        if info.calc_type == "fixed":
            if ainfo.override_amount is not None:
                val = ainfo.override_amount
            elif comp.code in legacy:
                val = int(legacy[comp.code])
            else:
                val = int(info.amount_or_formula)
            values[comp.code] = val
            breakdown[comp.code] = val
            ordered_codes.append(comp.code)
        else:
            formulas[comp.code] = info.amount_or_formula

    gaji = values.get("gaji_pokok", 0) + values.get("tunjangan_tetap", 0)
    variables: dict = {
        "hari_kerja": hari_kerja,
        "jam_lembur": overtime_hours,
        "gaji": gaji,
        "upah_per_jam": (gaji / 173) if gaji else 0,
        **values,
    }
    try:
        for code in topo_order(formulas):
            val = rupiah(evaluate(formulas[code], variables))
            values[code] = val
            breakdown[code] = val
            variables[code] = val
            ordered_codes.append(code)
    except FormulaError as e:
        raise ValueError(f"Formula komponen gagal dievaluasi: {e}")

    base_gross = sum(v for c, v in breakdown.items() if kinds[c] == "earning")
    deductions = sum(v for c, v in breakdown.items() if kinds[c] == "deduction")

    # 2. THR (masuk bruto tahunan -> kena pajak via penyesuaian).
    thr = 0
    if include_thr:
        if thr_holiday_date is None:
            raise ValueError("thr_holiday_date wajib bila include_thr=True")
        policy = get_policy(db, tenant_id)
        if policy.thr_basis == "total_fixed":
            basis = sum(
                v for c, v in breakdown.items()
                if kinds[c] == "earning"
                and _is_fixed_earning(db, tenant_id, c, period_end)
            )
        else:
            basis = values.get("gaji_pokok", 0)
        if employment.status in ("active", "probation"):
            thr = thr_amount(employment.start_date, thr_holiday_date, basis)

    # 3. PPh 21.
    irregular = thr + retro_amount
    if is_december:
        if method == "gross_up":
            # Iterasi titik-tetap: tunjangan pajak Desember = pajak
            # Desember itu sendiri (tunjangan ikut kena pajak).
            dec_tax = 0
            for _ in range(10):
                dec_gross = base_gross + dec_tax
                pension_actual = rupiah(
                    0.03 * (ytd_pension_base + dec_gross))
                new_tax = pph21_service.december_adjustment(
                    ytd_gross + dec_gross + irregular, ptkp, ytd_tax,
                    pension_actual,
                )
                if new_tax == dec_tax:
                    break
                dec_tax = new_tax
            tax = dec_tax
        else:
            pension_actual = rupiah(
                0.03 * (ytd_pension_base + base_gross))
            tax = pph21_service.december_adjustment(
                ytd_gross + base_gross + irregular, ptkp, ytd_tax,
                pension_actual,
            )
        borne_by = "employee" if method == "gross" else "employer"
    else:
        tax = pph21_service.monthly_tax(base_gross, ptkp, method, irregular)
        borne_by = "employee" if method == "gross" else "employer"

    if method == "gross_up":
        # Tunjangan pajak = PPh 21-nya sendiri (iterasi sudah konvergen di engine).
        breakdown[TUNJANGAN_PAJAK] = tax
        kinds[TUNJANGAN_PAJAK] = "earning"
        gross = base_gross + tax
    else:
        gross = base_gross

    take_home = gross + thr + retro_amount - deductions - (
        tax if borne_by == "employee" else 0
    )

    employer_cost = pph21_service.employer_bpjs(gaji)

    validation_errors: list[str] = []
    if not (person and person.bank_account_no):
        validation_errors.append("Rekening bank karyawan belum diisi")
    if take_home < 0:
        validation_errors.append("Take-home pay negatif — periksa komponen")

    return {
        "person_name": person.full_name if person else "?",
        "nik": person.nik if person else "",
        "ptkp": ptkp,
        "breakdown": breakdown,
        "kinds": kinds,
        "inputs_snapshot": {
            "period": period,
            "ptkp": ptkp,
            "hari_kerja": hari_kerja,
            "jam_lembur": overtime_hours,
            "gaji": gaji,
            "pph21_method": method,
        },
        "gross": gross,
        "total_deductions": deductions,
        "pph21": tax,
        "pph21_borne_by": borne_by,
        "thr_amount": thr,
        "retro_amount": retro_amount,
        "retro_detail": retro_detail or {},
        "take_home_pay": take_home,
        "employer_cost": employer_cost,
        "bank_name": person.bank_name if person else None,
        "bank_account_no": person.bank_account_no if person else None,
        "validation_errors": validation_errors,
    }


def _is_fixed_earning(db: Session, tenant_id, code: str, as_of: date) -> bool:
    comp = (
        db.execute(
            select(SalaryComponent).where(
                SalaryComponent.tenant_id == tenant_id,
                SalaryComponent.code == code,
            )
        )
        .scalars()
        .first()
    )
    if comp is None:
        return False
    info = ed.as_of(
        db=db, tenant_id=tenant_id, model=SalaryComponentInfo,
        identity_field="component_id", identity_value=comp.id,
        as_of_date=as_of,
    )
    return bool(info and info.calc_type == "fixed" and info.kind == "earning")


# ---------------------------------------------------------------------------
# Retro: selisih periode terkunci yang berubah setelah dikunci
# ---------------------------------------------------------------------------
def detect_retro(
    *, db: Session, tenant_id, employment: Employment, current_period: str,
    ref_run: PayrollRun, ref_inputs: dict,
) -> tuple[int, dict]:
    """Bandingkan hitung-ulang periode terkunci (data KINI) vs snapshot.

    Mengembalikan (selisih_total, detail). Sudah dikurangi retro yang
    pernah dibayarkan untuk periode acuan tersebut (anti double-count).
    """
    ref_start, ref_end = _period_bounds(ref_run.period)
    if employment.start_date > ref_end:
        return 0, {}
    stored = (
        db.execute(
            select(PayrollLine).where(
                PayrollLine.payroll_run_id == ref_run.id,
                PayrollLine.employment_id == employment.id,
            )
        )
        .scalars()
        .first()
    )
    if stored is None:
        return 0, {}

    # Hitung ulang periode acuan dengan data kini (tanpa THR/retro/PPh21).
    fresh = evaluate_employment(
        db=db, tenant_id=tenant_id, employment=employment,
        period=ref_run.period, method=ref_run.pph21_method,
        overtime_hours=(ref_inputs.get("overtime_hours") or {}).get(
            str(employment.id), 0),
    )
    diffs: dict[str, int] = {}
    kinds = fresh["kinds"]
    for code, new_val in fresh["breakdown"].items():
        if code == TUNJANGAN_PAJAK:
            continue
        old_val = (stored.breakdown or {}).get(code, 0)
        if new_val != old_val:
            diffs[code] = new_val - old_val
    # Kode yang hilang dari katalog kini tapi ada di snapshot -> selisih negatif.
    for code, old_val in (stored.breakdown or {}).items():
        if code not in fresh["breakdown"] and code != TUNJANGAN_PAJAK and old_val:
            diffs[code] = diffs.get(code, 0) - old_val

    # Konvensi tanda: earning menambah hak karyawan, deduction mengurangi.
    # (retro_amount dijumlahkan ke take-home di evaluate_employment.)
    total = sum(
        -v if kinds.get(code) == "deduction" else v
        for code, v in diffs.items()
    )
    # Kurangi yang sudah pernah dibayar untuk periode acuan ini.
    already = 0
    later = (
        db.execute(
            select(PayrollLine).where(
                PayrollLine.tenant_id == tenant_id,
                PayrollLine.employment_id == employment.id,
            )
            .join(PayrollRun, PayrollLine.payroll_run_id == PayrollRun.id)
            .where(PayrollRun.period > ref_run.period,
                   PayrollRun.period < current_period)
        )
        .scalars()
        .all()
    )
    for line in later:
        det = line.retro_detail or {}
        if det.get("ref_period") == ref_run.period:
            already += det.get("amount", 0)
    net = total - already
    if net == 0:
        return 0, {}
    return net, {
        "ref_period": ref_run.period,
        "diff_per_component": diffs,
        "already_applied": already,
        "amount": net,
    }


# ---------------------------------------------------------------------------
# Payroll run: create & lock
# ---------------------------------------------------------------------------
def _eligible_employments(db: Session, tenant_id, period: str):
    start, end = _period_bounds(period)
    rows = (
        db.execute(
            select(Employment).where(
                Employment.tenant_id == tenant_id,
                Employment.status.in_(["active", "probation"]),
                Employment.start_date <= end,
            )
        )
        .scalars()
        .all()
    )
    return [e for e in rows if e.end_date is None or e.end_date >= start]


def _latest_reference_run(db: Session, tenant_id, current_period: str):
    """Run TERKUNCI terakhir sebelum periode berjalan (acuan retro)."""
    return (
        db.execute(
            select(PayrollRun).where(
                PayrollRun.tenant_id == tenant_id,
                PayrollRun.period < current_period,
                PayrollRun.status == "locked",
            )
            .order_by(PayrollRun.period.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _ytd_sums(db: Session, tenant_id, employment_id, year: int,
              before_period: str) -> tuple[int, int, int]:
    """(ytd_gross_total, ytd_tax, ytd_pension_base) dari run-run tahun ini."""
    lines = (
        db.execute(
            select(PayrollLine)
            .join(PayrollRun, PayrollLine.payroll_run_id == PayrollRun.id)
            .where(
                PayrollLine.tenant_id == tenant_id,
                PayrollLine.employment_id == employment_id,
                PayrollRun.period >= f"{year:04d}-01",
                PayrollRun.period < before_period,
            )
        )
        .scalars()
        .all()
    )
    ytd_gross = sum(
        (l.gross or 0) + (l.thr_amount or 0) + (l.retro_amount or 0) for l in lines
    )
    ytd_tax = sum(l.pph21 or 0 for l in lines)
    ytd_base = sum(l.inputs_snapshot.get("gross_regular", l.gross or 0)
                   for l in lines)
    return ytd_gross, ytd_tax, ytd_base


def create_run(
    *, db: Session, tenant_id, period: str,
    method: str | None = None, include_thr: bool = False,
    thr_holiday_date: date | None = None,
    overtime_hours: dict | None = None, notes: str | None = None,
    created_by,
) -> PayrollRun:
    """Buat payroll run draft untuk satu periode (PAY-001/008/009)."""
    period_start, period_end = _period_bounds(period)
    today = date.today()
    if period_start > date(today.year, today.month, 1):
        raise ValueError("Periode tidak boleh di masa depan")
    exists = db.execute(
        select(PayrollRun.id).where(
            PayrollRun.tenant_id == tenant_id, PayrollRun.period == period
        ).limit(1)
    ).first()
    if exists:
        raise ValueError(f"Payroll run periode {period} sudah ada")
    # Disiplin periode: run baru hanya boleh dibuat bila semua run
    # periode sebelumnya sudah terkunci (mencegah retro double-count).
    open_prev = db.execute(
        select(PayrollRun.period).where(
            PayrollRun.tenant_id == tenant_id,
            PayrollRun.period < period,
            PayrollRun.status != "locked",
        ).limit(1)
    ).first()
    if open_prev:
        raise ValueError(
            f"Kunci dulu payroll periode {open_prev[0]} sebelum membuat {period}"
        )

    policy = get_policy(db, tenant_id)
    method = method or policy.pph21_method
    if method not in pph21_service.PPH21_METHODS:
        raise ValueError(f"Metode PPh 21 '{method}' tidak dikenal")
    if include_thr and thr_holiday_date is None:
        raise ValueError("thr_holiday_date wajib bila include_thr=True")

    overtime_hours = overtime_hours or {}
    is_december = period_end.month == 12
    ref_run = _latest_reference_run(db, tenant_id, period)

    run = PayrollRun(
        tenant_id=tenant_id, period=period, status="draft",
        pph21_method=method, include_thr=include_thr,
        thr_holiday_date=thr_holiday_date,
        inputs={"overtime_hours": overtime_hours},
        notes=notes, created_by_user_id=created_by,
    )
    db.add(run)
    db.flush()

    employments = _eligible_employments(db, tenant_id, period)
    totals = {"total_gross": 0, "total_thr": 0, "total_retro": 0,
              "total_deductions": 0, "total_pph21": 0,
              "total_take_home": 0, "total_employer_bpjs": 0}

    for emp in employments:
        ot = overtime_hours.get(str(emp.id), 0)
        retro, retro_detail = (0, {})
        if ref_run is not None:
            retro, retro_detail = detect_retro(
                db=db, tenant_id=tenant_id, employment=emp,
                current_period=period, ref_run=ref_run,
                ref_inputs=ref_run.inputs or {},
            )
        ytd = (0, 0, 0)
        if is_december:
            ytd = _ytd_sums(db, tenant_id, emp.id, period_end.year, period)
        calc = evaluate_employment(
            db=db, tenant_id=tenant_id, employment=emp, period=period,
            method=method, include_thr=include_thr,
            thr_holiday_date=thr_holiday_date, overtime_hours=ot,
            is_december=is_december,
            ytd_gross=ytd[0], ytd_tax=ytd[1], ytd_pension_base=ytd[2],
            retro_amount=retro, retro_detail=retro_detail,
        )
        # Simpan gross (termasuk tunjangan pajak bila gross_up) sebagai basis
        # pensiun YTD untuk penyesuaian Desember berikutnya, dan peta kind
        # agar slip bisa memisah penghasilan/potongan.
        calc["inputs_snapshot"]["gross_regular"] = calc["gross"]
        calc["inputs_snapshot"]["kinds"] = calc["kinds"]
        line = PayrollLine(
            tenant_id=tenant_id, payroll_run_id=run.id,
            employment_id=emp.id,
            person_name=calc["person_name"], nik=calc["nik"], ptkp=calc["ptkp"],
            breakdown=calc["breakdown"],
            inputs_snapshot=calc["inputs_snapshot"],
            gross=calc["gross"], total_deductions=calc["total_deductions"],
            pph21=calc["pph21"], pph21_borne_by=calc["pph21_borne_by"],
            thr_amount=calc["thr_amount"], retro_amount=calc["retro_amount"],
            retro_detail=calc["retro_detail"],
            take_home_pay=calc["take_home_pay"],
            employer_cost=calc["employer_cost"],
            bank_name=calc["bank_name"],
            bank_account_no=calc["bank_account_no"],
            validation_errors=calc["validation_errors"],
        )
        db.add(line)
        totals["total_gross"] += calc["gross"]
        totals["total_thr"] += calc["thr_amount"]
        totals["total_retro"] += calc["retro_amount"]
        totals["total_deductions"] += calc["total_deductions"]
        totals["total_pph21"] += calc["pph21"]
        totals["total_take_home"] += calc["take_home_pay"]
        totals["total_employer_bpjs"] += sum(calc["employer_cost"].values())

    run.totals = totals
    run.headcount = len(employments)
    db.flush()
    return run


def lock_run(*, db: Session, tenant_id, run_id, locked_by) -> PayrollRun:
    """Kunci run (PAY-009): tolak bila ada error blocking di baris mana pun."""
    run = db.get(PayrollRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise KeyError("Payroll run tidak ditemukan")
    if run.status == "locked":
        raise ValueError(f"Periode {run.period} sudah terkunci")
    lines = (
        db.execute(
            select(PayrollLine).where(PayrollLine.payroll_run_id == run.id)
        )
        .scalars()
        .all()
    )
    blocking = [
        {"employment_id": str(l.employment_id), "person_name": l.person_name,
         "errors": l.validation_errors}
        for l in lines if l.validation_errors
    ]
    if blocking:
        detail = "; ".join(
            f"{b['person_name']}: {', '.join(b['errors'])}" for b in blocking[:5]
        )
        raise ValueError(
            f"Run tidak bisa dikunci: {len(blocking)} karyawan punya error "
            f"blocking. {detail}"
        )
    from datetime import datetime, timezone

    run.status = "locked"
    run.locked_at = datetime.now(timezone.utc)
    run.locked_by_user_id = locked_by
    db.flush()
    return run
