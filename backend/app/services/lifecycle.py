"""Katalog event lifecycle + alasan per tenant, dan derivasi status employment.

Sprint 3, CHR-002 & CHR-004.

Aturan keras (PRD 9.x): setiap insert JobInfo / CompInfo / ContractInfo wajib
memakai event + event_reason yang terdaftar di katalog tenant. Validasi
dijalankan di ``effective_dating.insert_record`` lewat ``validate_event``,
sehingga berlaku untuk API, impor Excel, maupun seed.

Derivasi status (CHR-004): event terakhir pada JobInfo per hari ini
memetakan ke Employment.status. ``termination`` juga menutup employment
(end_date = tanggal berlaku). ``data_update`` tidak mengubah status.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Employment, EventReason, JobInfo, LifecycleEvent

# (code, nama, deskripsi, [alasan])
LIFECYCLE_EVENTS_SEED: list[tuple[str, str, str, list[str]]] = [
    ("hire", "Rekrutmen", "Karyawan mulai bekerja",
     ["Rekrutmen reguler", "Penetapan gaji awal", "Rekrutmen ulang karyawan lama",
      "Impor data massal", "Lainnya"]),
    ("probation_start", "Mulai Masa Percobaan", "Karyawan memasuki masa percobaan",
     ["Kontrak awal masa percobaan", "Lainnya"]),
    ("probation_end", "Akhir Masa Percobaan", "Masa percobaan selesai",
     ["Lulus masa percobaan", "Lainnya"]),
    ("promotion", "Promosi", "Kenaikan jabatan",
     ["Kenaikan jabatan reguler", "Pengisian posisi kosong",
      "Penyesuaian gaji promosi", "Lainnya"]),
    ("mutation", "Mutasi", "Perpindahan unit/lokasi/posisi setara",
     ["Rotasi internal", "Penugasan proyek", "Lainnya"]),
    ("demotion", "Demosi", "Penurunan jabatan",
     ["Evaluasi kinerja", "Restrukturisasi", "Lainnya"]),
    ("contract_extension", "Perpanjangan Kontrak", "Perpanjangan masa berlaku PKWT",
     ["Perpanjangan PKWT", "Lainnya"]),
    ("contract_conversion", "Konversi Kontrak", "Perubahan jenis kontrak",
     ["Konversi PKWT ke PKWTT", "Lainnya"]),
    ("unpaid_leave", "Cuti Tanpa Gaji", "Karyawan cuti di luar tanggungan",
     ["Permohonan karyawan", "Lainnya"]),
    ("termination", "Terminasi", "Hubungan kerja berakhir",
     ["Pengunduran diri", "PHK", "Kontrak berakhir", "Lainnya"]),
    ("rehire", "Rekrutmen Ulang", "Karyawan lama direkrut kembali",
     ["Rekrutmen ulang karyawan lama", "Lainnya"]),
    ("data_update", "Pembaruan Data", "Koreksi/pembaruan tanpa perubahan status",
     ["Koreksi data", "Pembaruan data", "Perubahan status PTKP", "Lainnya"]),
    # Sprint 4: perubahan struktur gaji (komponen/rumus/assignment).
    ("salary_structure", "Perubahan Struktur Gaji",
     "Perubahan komponen, rumus, atau assignment gaji",
     ["Komponen baru", "Perubahan rumus", "Perubahan nominal",
      "Nonaktifkan komponen", "Lainnya"]),
    # CMP-005: hasil siklus kompensasi masuk sebagai versi CompInfo baru.
    ("compensation_change", "Perubahan Kompensasi",
     "Perubahan kompensasi karyawan bertanggal efektif",
     ["Merit", "Promosi", "Penyesuaian pasar", "Penyesuaian berkala",
      "Lainnya"]),
]

ORG_EVENTS_SEED: list[tuple[str, str, str, list[str]]] = [
    ("org_founded", "Pendirian", "Pendirian entitas legal", ["Lainnya"]),
    ("org_unit_created", "Pembentukan", "Pembentukan unit organisasi", ["Lainnya"]),
    ("org_opened", "Pembukaan", "Pembukaan lokasi/unit", ["Lainnya"]),
    ("org_renamed", "Perubahan Nama", "Perubahan nama entitas/unit/lokasi", ["Lainnya"]),
    ("org_relocation", "Relokasi", "Perpindahan lokasi", ["Lainnya"]),
    ("org_restructure", "Restrukturisasi", "Perubahan struktur organisasi", ["Lainnya"]),
    ("org_closed", "Penutupan", "Penutupan unit/lokasi", ["Lainnya"]),
]

# Event -> Employment.status. "data_update" sengaja tidak ada: tak mengubah status.
EVENT_STATUS_MAP = {
    "hire": "active",
    "rehire": "active",
    "promotion": "active",
    "mutation": "active",
    "demotion": "active",
    "contract_extension": "active",
    "contract_conversion": "active",
    "probation_end": "active",
    "probation_start": "probation",
    "unpaid_leave": "inactive",
    "termination": "terminated",
}


def seed_lifecycle_catalog(
    db: Session, tenant_id, created_by_user_id=None
) -> None:
    """Seed katalog event default untuk satu tenant.

    Idempoten per kode: event yang belum ada ditambahkan, yang sudah ada
    dibiarkan (aman dipanggil ulang saat katalog bertambah, mis. Sprint 4).
    """
    for applies_to, seed in (("lifecycle", LIFECYCLE_EVENTS_SEED),
                             ("org", ORG_EVENTS_SEED)):
        for code, name, description, reasons in seed:
            ev = (
                db.execute(
                    select(LifecycleEvent).where(
                        LifecycleEvent.tenant_id == tenant_id,
                        LifecycleEvent.code == code,
                    )
                )
                .scalars()
                .first()
            )
            if ev is None:
                ev = LifecycleEvent(
                    tenant_id=tenant_id,
                    code=code,
                    name=name,
                    description=description,
                    applies_to=applies_to,
                    is_active=True,
                    created_by_user_id=created_by_user_id,
                )
                db.add(ev)
                db.flush()
            for reason in reasons:
                exists = (
                    db.execute(
                        select(EventReason.id).where(
                            EventReason.tenant_id == tenant_id,
                            EventReason.event_id == ev.id,
                            EventReason.reason == reason,
                        ).limit(1)
                    ).first()
                )
                if not exists:
                    db.add(EventReason(
                        tenant_id=tenant_id,
                        event_id=ev.id,
                        reason=reason,
                        is_active=True,
                    ))
    db.flush()


def find_event(db: Session, tenant_id, event: str, applies_to: str) -> LifecycleEvent | None:
    """Cari event aktif di katalog; cocok case-insensitive pada kode ATAU nama."""
    key = (event or "").strip().lower()
    if not key:
        return None
    return (
        db.execute(
            select(LifecycleEvent).where(
                LifecycleEvent.tenant_id == tenant_id,
                LifecycleEvent.applies_to == applies_to,
                LifecycleEvent.is_active == True,  # noqa: E712
                (func.lower(LifecycleEvent.code) == key)
                | (func.lower(LifecycleEvent.name) == key),
            )
        )
        .scalars()
        .first()
    )


def validate_event(
    db: Session, tenant_id, event: str, event_reason: str, applies_to: str = "lifecycle"
) -> str:
    """Validasi event + reason terhadap katalog tenant.

    Mengembalikan kode event kanonis (mis. 'Promosi' -> 'promotion').
    Mengangkat ValueError bila tidak valid (dipetakan ke 422 di API).
    """
    if not (event or "").strip():
        raise ValueError("Event wajib diisi")
    if not (event_reason or "").strip():
        raise ValueError("Alasan event (event_reason) wajib diisi")
    ev = find_event(db, tenant_id, event, applies_to)
    if ev is None:
        raise ValueError(
            f"Event '{event}' tidak terdaftar di katalog tenant ini "
            f"(lihat GET /lifecycle/events)"
        )
    reason = event_reason.strip()
    hit = (
        db.execute(
            select(EventReason).where(
                EventReason.tenant_id == tenant_id,
                EventReason.event_id == ev.id,
                EventReason.is_active == True,  # noqa: E712
                func.lower(EventReason.reason) == reason.lower(),
            )
        )
        .scalars()
        .first()
    )
    if hit is None:
        raise ValueError(
            f"Alasan '{reason}' tidak terdaftar untuk event '{ev.name}' "
            f"(lihat GET /lifecycle/events)"
        )
    return ev.code


def derive_employment_status(
    db: Session, employment: Employment, today: date | None = None
) -> str | None:
    """Terapkan aturan derivasi CHR-004 dari event JobInfo terakhir per hari ini.

    Mengembalikan status baru bila berubah, None bila tidak ada perubahan.
    Tidak commit; pemanggil yang commit.
    """
    today = today or date.today()
    latest = (
        db.execute(
            select(JobInfo).where(
                JobInfo.tenant_id == employment.tenant_id,
                JobInfo.employment_id == employment.id,
                JobInfo.valid_from <= today,
            )
            .order_by(JobInfo.valid_from.desc(), JobInfo.seq_no.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if latest is None:
        return None
    code = latest.event
    if code == "termination":
        new_status = "terminated"
        employment.end_date = latest.valid_from
    elif code in EVENT_STATUS_MAP:
        new_status = EVENT_STATUS_MAP[code]
    else:
        return None  # data_update / tak dikenal -> status tidak berubah
    if employment.status != new_status:
        employment.status = new_status
        return new_status
    return None
