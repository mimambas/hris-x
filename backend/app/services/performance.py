"""Penilaian kinerja & pelatihan (Sprint 7, PRD 24.2 S7).

Aturan inti:
- Siklus: draft → goal_setting → mid_year → year_end → calibration →
  closed. Hanya maju satu langkah; lompat/mundur ditolak. Status closed =
  immutable (semua mutasi goal/appraisal/enrollment terkait ditolak).
- Bobot: total weight goal APPROVED per (employment, cycle) harus == 100
  saat approve goal maupun submit self-assessment.
- Appraisal: self (fase goal_setting..year_end) → manager score (hanya
  fase year_end, wajib self sudah submit) → potential (hanya fase
  calibration) → final_score = Σ(weight_i × manager_score_i)/100.
- Matriks 9-box & rekomendasi pelatihan: RULE-BASED deterministik, BUKAN
  AI (lihat ADR-0010).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appraisal, PerformanceGoal, ReviewCycle, TenantPerformancePolicy

CYCLE_ORDER = ("draft", "goal_setting", "mid_year", "year_end",
               "calibration", "closed")

# Kategori & label kotak 9-box: (performance, potential) → (box_key, id, en).
_BOXES = {
    ("High", "High"): ("star", "Bintang", "Star"),
    ("High", "Medium"): ("high_performer", "Berkinerja Tinggi",
                         "High Performer"),
    ("High", "Low"): ("trusted_professional", "Profesional Andal",
                      "Trusted Professional"),
    ("Medium", "High"): ("high_potential", "Potensi Tinggi", "High Potential"),
    ("Medium", "Medium"): ("key_player", "Pemain Kunci", "Key Player"),
    ("Medium", "Low"): ("average_performer", "Kinerja Rata-rata",
                        "Average Performer"),
    ("Low", "High"): ("rough_diamond", "Berlian Mentah", "Rough Diamond"),
    ("Low", "Medium"): ("inconsistent_player", "Kinerja Tidak Konsisten",
                        "Inconsistent Player"),
    ("Low", "Low"): ("low_performer", "Kinerja Rendah", "Low Performer"),
}

# Rekomendasi pelatihan per kotak — pemetaan deterministik (bukan AI).
TRAINING_RECOMMENDATIONS: dict[str, list[str]] = {
    "star": ["Leadership Development", "Mentoring"],
    "high_performer": ["Pengembangan Kepemimpinan", "Manajemen Proyek Lanjutan"],
    "trusted_professional": ["Mentoring", "Berbagi Pengetahuan"],
    "high_potential": ["Program Akselerasi Karier", "Kepemimpinan Dasar"],
    "key_player": ["Pengembangan Kompetensi Teknis", "Kolaborasi Tim"],
    "average_performer": ["Pelatihan Keterampilan Inti", "Manajemen Waktu"],
    "rough_diamond": ["Kepemimpinan Dasar", "Komunikasi Efektif"],
    "inconsistent_player": ["Coaching Kinerja", "Keterampilan Inti"],
    "low_performer": ["Pembinaan Kinerja (PIP)", "Keterampilan Inti"],
}


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def ensure_cycle_mutable(cycle: ReviewCycle) -> None:
    """Tolak mutasi apa pun bila siklus sudah closed (immutable)."""
    if cycle.status == "closed":
        raise _unprocessable(
            f"Siklus '{cycle.name}' sudah closed dan tidak bisa diubah")


def check_transition(current: str, to: str) -> None:
    """Validasi transisi fase siklus; raise 422 bila tidak valid."""
    if current == "closed":
        raise _unprocessable("Siklus sudah closed dan tidak bisa diubah")
    if to not in CYCLE_ORDER:
        raise _unprocessable(f"Status '{to}' tidak dikenal")
    expected = CYCLE_ORDER[CYCLE_ORDER.index(current) + 1]
    if to != expected:
        raise _unprocessable(
            f"Transisi '{current}' → '{to}' tidak valid; "
            f"langkah berikutnya adalah '{expected}'")


def get_policy(db: Session, tenant_id) -> dict:
    """Ambang 9-box tenant; fallback ke default bila belum diatur."""
    row = db.execute(
        select(TenantPerformancePolicy).where(
            TenantPerformancePolicy.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if row is None:
        return {"perf_low_max": 2.5, "perf_med_max": 3.75,
                "pot_low_max": 2.5, "pot_med_max": 3.5}
    return {"perf_low_max": float(row.perf_low_max),
            "perf_med_max": float(row.perf_med_max),
            "pot_low_max": float(row.pot_low_max),
            "pot_med_max": float(row.pot_med_max)}


def approved_goals(db: Session, tenant_id, employment_id,
                   cycle_id) -> list[PerformanceGoal]:
    return (
        db.execute(
            select(PerformanceGoal).where(
                PerformanceGoal.tenant_id == tenant_id,
                PerformanceGoal.employment_id == employment_id,
                PerformanceGoal.cycle_id == cycle_id,
                PerformanceGoal.status == "approved",
            )
        )
        .scalars()
        .all()
    )


def approved_weight_total(db: Session, tenant_id, employment_id,
                          cycle_id) -> int:
    return sum(g.weight for g in approved_goals(db, tenant_id, employment_id,
                                               cycle_id))


def ensure_weight_100(db: Session, tenant_id, employment_id,
                      cycle_id) -> None:
    """Total bobot goal APPROVED harus == 100; raise 422 bila tidak."""
    total = approved_weight_total(db, tenant_id, employment_id, cycle_id)
    if total != 100:
        raise _unprocessable(
            f"Total bobot goal yang disetujui = {total}%, harus tepat 100%")


def nine_box(final_score, potential_score: int, policy: dict) -> dict:
    """Petakan (final, potential) ke kotak 9-box.

    final_score: skor kinerja 1..5 (boleh desimal).
    potential_score: skor potensi 1..5 (integer).
    """
    final = float(final_score)
    if not 1 <= potential_score <= 5:
        raise ValueError("potential_score harus 1..5")
    perf = ("Low" if final <= policy["perf_low_max"]
            else "Medium" if final <= policy["perf_med_max"] else "High")
    pot = ("Low" if potential_score <= policy["pot_low_max"]
           else "Medium" if potential_score <= policy["pot_med_max"]
           else "High")
    box_key, label_id, label_en = _BOXES[(perf, pot)]
    return {"perf_category": perf, "pot_category": pot, "box_key": box_key,
            "label_id": label_id, "label_en": label_en}


def compute_final_score(manager_scores: list[dict],
                        weight_by_goal: dict[str, int]) -> Decimal:
    """final = Σ(weight_i × manager_score_i) / 100."""
    total = sum(Decimal(weight_by_goal[str(s["goal_id"])])
                * Decimal(s["score"]) for s in manager_scores)
    return (total / Decimal(100)).quantize(Decimal("0.01"))


def training_recommendations(box_key: str) -> list[str]:
    """Daftar kategori kursus yang direkomendasikan untuk satu kotak.

    Deterministik & rule-based — BUKAN rekomendasi AI.
    """
    return list(TRAINING_RECOMMENDATIONS.get(box_key, []))


def appraisal_box(db: Session, appraisal: Appraisal) -> dict | None:
    """Kotak 9-box untuk satu appraisal yang sudah dikalibrasi."""
    if appraisal.final_score is None or appraisal.potential_score is None:
        return None
    policy = get_policy(db, appraisal.tenant_id)
    return nine_box(appraisal.final_score, appraisal.potential_score, policy)
