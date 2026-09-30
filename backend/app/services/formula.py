"""Formula engine AMAN untuk komponen gaji (PAY-003).

Prinsip keamanan (PRD 18.x):
- TIDAK PERNAH memakai eval()/exec()/compile().
- Ekspresi diurai dengan ``ast`` dan dievaluasi node-per-node dengan
  whitelist ketat: operator aritmetika + - * /, fungsi min/max/round/abs,
  konstanta angka, dan referensi nama (kode komponen / variabel bawaan).
- Node APAPUN di luar whitelist (atribut, subscript, lambda, comprehension,
  import, pemanggilan fungsi lain, string, dsb.) ditolak dengan FormulaError.

Contoh valid:  "hari_kerja * 50000", "0.02 * (gaji_pokok + tunjangan_tetap)",
               "min(gaji, 12000000) * 0.01".
Contoh ditolak: "__import__('os').system('x')", "[x for x in y]", "gaji.__class__".
"""

from __future__ import annotations

import ast
import operator
from decimal import Decimal, ROUND_HALF_UP


class FormulaError(ValueError):
    """Formula tidak valid / tidak aman / referensi tak dikenal."""


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCS = {
    "min": min,
    "max": max,
    "abs": abs,
    # round(x) dan round(x, ndigits) — perilaku Python standar.
    "round": round,
}


def rupiah(value) -> int:
    """Bulatkan ke integer rupiah (half-up), bukan banker's rounding."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _eval(node: ast.AST, variables: dict) :
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(
                f"Konstanta {node.value!r} tidak diizinkan; hanya angka."
            )
        return node.value
    if isinstance(node, ast.Name):
        try:
            return variables[node.id]
        except KeyError:
            raise FormulaError(
                f"Variabel '{node.id}' tidak dikenal "
                f"(daftar: {sorted(variables)})"
            )
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise FormulaError(
                f"Operator '{type(node.op).__name__}' tidak diizinkan "
                "(hanya + - * /)."
            )
        left = _eval(node.left, variables)
        right = _eval(node.right, variables)
        try:
            return op(left, right)
        except ZeroDivisionError:
            raise FormulaError("Pembagian dengan nol.")
    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            raise FormulaError(
                f"Operator uner '{type(node.op).__name__}' tidak diizinkan."
            )
        return op(_eval(node.operand, variables))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            name = getattr(node.func, "id", type(node.func).__name__)
            raise FormulaError(
                f"Fungsi '{name}' tidak diizinkan "
                f"(hanya: {sorted(_ALLOWED_FUNCS)})."
            )
        if node.keywords:
            raise FormulaError("Argumen bernama (keyword) tidak diizinkan.")
        if not node.args:
            raise FormulaError(f"Fungsi '{node.func.id}' butuh argumen.")
        args = [_eval(a, variables) for a in node.args]
        try:
            return _ALLOWED_FUNCS[node.func.id](*args)
        except (TypeError, ValueError) as e:
            raise FormulaError(f"Fungsi '{node.func.id}' gagal: {e}")
    # Semua yang lain — Attribute, Subscript, Lambda, ListComp, IfExp,
    # NamedExpr, JoinedStr, ... — DITOLAK.
    raise FormulaError(
        f"Konstruksi '{type(node).__name__}' tidak diizinkan dalam formula."
    )


def evaluate(formula: str, variables: dict) -> float:
    """Evaluasi formula terhadap variabel; kembalikan angka (belum dibulatkan)."""
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaError("Formula kosong.")
    if len(formula) > 2000:
        raise FormulaError("Formula terlalu panjang (maks 2000 karakter).")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"Sintaks formula salah: {e}")
    result = _eval(tree, variables)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise FormulaError("Formula harus menghasilkan angka.")
    return result


def referenced_names(formula: str) -> set[str]:
    """Kumpulkan semua nama (Name) yang dirujuk formula."""
    tree = ast.parse(formula, mode="eval")
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def topo_order(formulas: dict[str, str]) -> list[str]:
    """Urutkan evaluasi komponen formula; tolak circular reference.

    ``formulas``: {code: formula}. Dependensi = nama yang juga merupakan
    kode komponen lain. Mengembalikan urutan kode yang aman dievaluasi.
    ValueError bila ada siklus (dipetakan ke 422 saat simpan).
    """
    codes = set(formulas)
    deps: dict[str, set[str]] = {}
    for code, formula in formulas.items():
        try:
            names = referenced_names(formula)
        except SyntaxError as e:
            raise FormulaError(f"Formula '{code}' sintaks salah: {e}")
        deps[code] = {n for n in names if n in codes and n != code}
        unknown_self = {n for n in names if n == code}
        if unknown_self:
            raise FormulaError(f"Formula '{code}' merujuk dirinya sendiri.")

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(code: str, stack: list[str]):
        if code in visited:
            return
        if code in visiting:
            cycle = " -> ".join(stack + [code])
            raise FormulaError(f"Circular reference terdeteksi: {cycle}")
        visiting.add(code)
        for dep in sorted(deps[code]):
            visit(dep, stack + [code])
        visiting.discard(code)
        visited.add(code)
        ordered.append(code)

    for code in sorted(formulas):
        visit(code, [])
    return ordered


def validate_formula_names(formula: str, allowed: set[str]) -> None:
    """Pastikan semua nama di formula dikenal (kode komponen / variabel bawaan)."""
    unknown = referenced_names(formula) - allowed - set(_ALLOWED_FUNCS)
    if unknown:
        raise FormulaError(
            f"Nama tak dikenal di formula: {sorted(unknown)} "
            f"(yang dikenal: {sorted(allowed)})"
        )


# Variabel bawaan yang boleh dipakai formula (selain kode komponen).
# Sprint 5 menambah: hari_hadir, hari_mangkir, upah_lembur,
# potongan_mangkir_aktif (integrasi absensi/lembur -> payroll, ATT-010).
BUILTIN_VARS = frozenset({
    "hari_kerja", "gaji", "jam_lembur", "upah_per_jam",
    "hari_hadir", "hari_mangkir", "upah_lembur", "potongan_mangkir_aktif",
})


class _ZeroDefault(dict):
    """Mapping yang mengembalikan 0 untuk nama apa pun.

    Dipakai untuk cek keamanan SINTAKS formula pra-simpan: nama yang
    belum dikenal (mis. komponen yang baru dibuat) tidak boleh menggagalkan
    parse; validasi nama dilakukan terpisah via validate_formula_names.
    """

    def __missing__(self, key):
        return 0


def check_syntax_only(formula: str) -> None:
    """Pastikan formula ter-parse dan hanya memakai konstruksi aman.

    Tidak memvalidasi nama variabel (lihat validate_formula_names).
    """
    evaluate(formula, _ZeroDefault({v: 0 for v in BUILTIN_VARS}))

