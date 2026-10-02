"""Guard statis: nama class di schemas.py tidak boleh ganda.

Regresi 2026-10-03: skema LRN `AssignmentCreate` menimpa `AssignmentCreate`
milik RBAC (Sprint 1) karena nama class yang sama di modul yang sama — endpoint
POST /roles/{id}/assign jadi memvalidasi body dengan skema pelatihan dan
selalu 422. Uji statis ini mencegah tabrakan nama terulang diam-diam.
"""

import ast
import pathlib

SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "app" / "schemas" / "schemas.py"


def test_nama_class_schema_unik():
    tree = ast.parse(SCHEMAS.read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert not duplicates, f"Nama class ganda di schemas.py: {duplicates}"
