"""Roster tim & tukar shift (EXP-012, PRD 13.2).

Roster menampilkan shift per anggota tim per hari dari
ShiftAssignment. Tukar shift satu hari: karyawan mengajukan tukar
dengan partner pada tanggal yang sama; partner menyetujui, lalu
atasan pengaju menyetujui; penerapan memecah rentang penugasan dan
menyisipkan penugasan satu hari berisi shift lawan. Konflik roster
(istirahat < 8 jam antara shift berurutan, bentrok lembur/cuti
yang sudah disetujui) dihitung saat pengajuan dan disampaikan
sebagai peringatan, bukan penolakan (kriteria PRD: diperingatkan).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip
from app.api.v1.team import _team_members
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models import (
    Employment,
    LeaveRequest,
    OvertimeRequest,
    Person,
    Shift,
    ShiftAssignment,
    ShiftSwapRequest,
    User,
)
from app.schemas.schemas import (
    RosterDayOut,
    RosterMemberOut,
    RosterOut,
    ShiftSwapCreate,
    ShiftSwapDecision,
    ShiftSwapOut,
    SwapCandidateOut,
)
from app.services import attendance as att
from app.services import effective_dating as ed
from app.services import leave as leave_service
from app.services import notify as notify_service
from app.services import population as population_service
from app.services.audit import write_audit

router = APIRouter(tags=["roster"])

MIN_REST_HOURS = 8
ACTIVE_SWAP_STATUSES = ("menunggu_partner", "menunggu_atasan")


def _own(db: Session, user: User) -> Employment:
    own = population_service.get_user_employment(db, user)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Akun tidak terikat employment aktif")
    return own


def _name(db: Session, employment_id) -> str:
    emp = db.get(Employment, employment_id)
    if emp is None:
        return "(tidak dikenal)"
    person = db.get(Person, emp.person_id)
    return person.full_name if person else "(tanpa nama)"


def _audit(db: Session, user: User, request: Request, action: str,
           swap: ShiftSwapRequest, reason: str | None = None) -> None:
    write_audit(db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
                action=action, object_type="shift_swap_request",
                object_id=swap.id, old_values=None,
                new_values={"status": swap.status,
                            "swap_date": str(swap.swap_date)},
                reason=reason, channel="api", ip=client_ip(request))


def _week_range(start: date | None, end: date | None) -> tuple[date, date]:
    if start is None:
        today = date.today()
        start = today - timedelta(days=today.weekday())
    if end is None:
        end = start + timedelta(days=6)
    if end < start or (end - start).days > 30:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Rentang roster tidak valid (maksimal 31 hari)")
    return start, end


def _roster_days(db: Session, user: User, employment_id,
                 start: date, end: date) -> list[RosterDayOut]:
    days: list[RosterDayOut] = []
    day = start
    while day <= end:
        shift, _s, _e = att.get_shift_for(db, user.tenant_id,
                                          employment_id, day)
        if shift is None:
            days.append(RosterDayOut(date=day))
        else:
            days.append(RosterDayOut(
                date=day, shift_code=shift.code, shift_name=shift.name,
                start_time=shift.start_time.strftime("%H:%M"),
                end_time=shift.end_time.strftime("%H:%M"),
                is_overnight=shift.is_overnight))
        day += timedelta(days=1)
    return days


# ---------------------------------------------------------------- roster
@router.get("/roster/me", response_model=RosterOut)
def my_roster(start: date | None = Query(default=None),
              end: date | None = Query(default=None),
              user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    own = _own(db, user)
    start, end = _week_range(start, end)
    return RosterOut(start_date=start, end_date=end, members=[
        RosterMemberOut(employment_id=own.id,
                        person_name=_name(db, own.id),
                        days=_roster_days(db, user, own.id, start, end))])


@router.get("/roster/team", response_model=RosterOut)
def team_roster(start: date | None = Query(default=None),
                end: date | None = Query(default=None),
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    own = _own(db, user)
    team = _team_members(db, user, own.id)
    if not team:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Roster tim hanya untuk atasan dengan bawahan langsung.")
    start, end = _week_range(start, end)
    members = [RosterMemberOut(
        employment_id=own.id, person_name=_name(db, own.id) + " (Anda)",
        days=_roster_days(db, user, own.id, start, end))]
    for emp in sorted(team, key=lambda e: _name(db, e.id)):
        members.append(RosterMemberOut(
            employment_id=emp.id, person_name=_name(db, emp.id),
            days=_roster_days(db, user, emp.id, start, end)))
    return RosterOut(start_date=start, end_date=end, members=members)


# ------------------------------------------------------------- tukar shift
def _rest_warnings(db: Session, user: User, employment_id,
                   day: date, new_shift: Shift) -> list[str]:
    """Peringatan istirahat kurang bila shift baru dipasang di `day`."""
    out: list[str] = []
    name = _name(db, employment_id)
    new_start = datetime.combine(day, new_shift.start_time.time())
    new_end = new_start + timedelta(
        days=1) if new_shift.is_overnight else datetime.combine(
        day, new_shift.end_time.time())
    prev_shift, _ps, prev_end = att.get_shift_for(
        db, user.tenant_id, employment_id, day - timedelta(days=1))
    if prev_shift is not None and prev_end is not None:
        rest = (new_start - prev_end).total_seconds() / 3600
        if rest < MIN_REST_HOURS:
            out.append(
                f"Istirahat {name} hanya {rest:.1f} jam sebelum shift "
                f"hasil tukar (minimum dianjurkan {MIN_REST_HOURS} jam).")
    next_shift, next_start, _ne = att.get_shift_for(
        db, user.tenant_id, employment_id, day + timedelta(days=1))
    if next_shift is not None and next_start is not None:
        rest = (next_start - new_end).total_seconds() / 3600
        if rest < MIN_REST_HOURS:
            out.append(
                f"Istirahat {name} hanya {rest:.1f} jam setelah shift "
                f"hasil tukar (minimum dianjurkan {MIN_REST_HOURS} jam).")
    return out


def _conflict_warnings(db: Session, user: User, body: ShiftSwapCreate,
                       own: Employment, partner: Employment,
                       own_shift: Shift, partner_shift: Shift) -> list[str]:
    warnings: list[str] = []
    day = body.swap_date
    for emp, new_shift in ((own, partner_shift), (partner, own_shift)):
        warnings.extend(_rest_warnings(db, user, emp.id, day, new_shift))
        overtime = db.execute(
            select(OvertimeRequest).where(
                OvertimeRequest.tenant_id == user.tenant_id,
                OvertimeRequest.employment_id == emp.id,
                OvertimeRequest.date == day,
                OvertimeRequest.status == "approved")
        ).scalars().first()
        if overtime is not None:
            warnings.append(
                f"{_name(db, emp.id)} memiliki lembur yang sudah "
                f"disetujui pada tanggal tukar.")
        leave = db.execute(
            select(LeaveRequest).where(
                LeaveRequest.tenant_id == user.tenant_id,
                LeaveRequest.employment_id == emp.id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= day,
                LeaveRequest.end_date >= day)
        ).scalars().first()
        if leave is not None:
            warnings.append(
                f"{_name(db, emp.id)} sedang cuti yang disetujui pada "
                f"tanggal tukar.")
    return warnings


def _swap_out(db: Session, swap: ShiftSwapRequest) -> ShiftSwapOut:
    out = ShiftSwapOut.model_validate(swap)
    out.requester_name = _name(db, swap.requester_employment_id)
    out.partner_name = _name(db, swap.partner_employment_id)
    req_shift = db.get(Shift, swap.requester_shift_id)
    par_shift = db.get(Shift, swap.partner_shift_id)
    out.requester_shift_name = req_shift.name if req_shift else None
    out.partner_shift_name = par_shift.name if par_shift else None
    return out


def _get_swap(db: Session, user: User,
              swap_id: uuid.UUID) -> ShiftSwapRequest:
    swap = db.get(ShiftSwapRequest, swap_id)
    if swap is None or swap.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tukar shift tidak ditemukan")
    return swap


@router.get("/shift-swaps/candidates",
            response_model=list[SwapCandidateOut])
def swap_candidates(day: date = Query(..., alias="date"),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    own = _own(db, user)
    rows = db.execute(
        select(Employment).where(
            Employment.tenant_id == user.tenant_id,
            Employment.status == "active",
            Employment.id != own.id)
    ).scalars().all()
    out = []
    for emp in rows:
        shift, _s, _e = att.get_shift_for(db, user.tenant_id, emp.id, day)
        out.append(SwapCandidateOut(
            employment_id=emp.id, person_name=_name(db, emp.id),
            shift_name=shift.name if shift else None))
    out.sort(key=lambda c: c.person_name)
    return out


@router.post("/shift-swaps", response_model=ShiftSwapOut,
             status_code=status.HTTP_201_CREATED)
def create_swap(body: ShiftSwapCreate, request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    own = _own(db, user)
    if body.swap_date < date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tanggal tukar tidak boleh di masa lalu")
    if str(body.partner_employment_id) == str(own.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Tidak bisa bertukar shift dengan diri sendiri")
    partner = db.get(Employment, body.partner_employment_id)
    if partner is None or partner.tenant_id != user.tenant_id \
            or partner.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Partner tukar tidak ditemukan")
    own_shift, _s, _e = att.get_shift_for(db, user.tenant_id, own.id,
                                          body.swap_date)
    partner_shift, _s2, _e2 = att.get_shift_for(
        db, user.tenant_id, partner.id, body.swap_date)
    if own_shift is None or partner_shift is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Kedua pihak harus memiliki shift pada tanggal tukar")
    if str(own_shift.id) == str(partner_shift.id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Kedua pihak sudah berada di shift yang sama pada tanggal itu")
    dup = db.execute(
        select(ShiftSwapRequest).where(
            ShiftSwapRequest.tenant_id == user.tenant_id,
            ShiftSwapRequest.swap_date == body.swap_date,
            ShiftSwapRequest.status.in_(ACTIVE_SWAP_STATUSES),
            (ShiftSwapRequest.requester_employment_id.in_([own.id,
                                                           partner.id])
             | ShiftSwapRequest.partner_employment_id.in_([own.id,
                                                           partner.id])))
    ).scalars().first()
    if dup is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Sudah ada permintaan tukar aktif yang melibatkan salah "
            "satu pihak pada tanggal ini")
    warnings = _conflict_warnings(db, user, body, own, partner,
                                  own_shift, partner_shift)
    swap = ShiftSwapRequest(
        tenant_id=user.tenant_id, requester_employment_id=own.id,
        partner_employment_id=partner.id, swap_date=body.swap_date,
        requester_shift_id=own_shift.id, partner_shift_id=partner_shift.id,
        reason=body.reason, warnings=warnings, status="menunggu_partner")
    db.add(swap)
    db.flush()
    notify_service.notify_employment(
        db, tenant_id=user.tenant_id, employment_id=partner.id,
        category="persetujuan",
        title=f"🔁 Permintaan tukar shift dari {user.full_name}",
        body=f"Tukar shift tanggal {body.swap_date.isoformat()}: "
             f"{own_shift.name} ↔ {partner_shift.name}.",
        link="/roster")
    _audit(db, user, request, "create", swap)
    out = _swap_out(db, swap)
    db.commit()
    return out


@router.get("/shift-swaps/mine", response_model=list[ShiftSwapOut])
def my_swaps(user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    own = _own(db, user)
    rows = db.execute(
        select(ShiftSwapRequest).where(
            ShiftSwapRequest.tenant_id == user.tenant_id,
            (ShiftSwapRequest.requester_employment_id == own.id)
            | (ShiftSwapRequest.partner_employment_id == own.id))
        .order_by(ShiftSwapRequest.created_at.desc())
    ).scalars().all()
    return [_swap_out(db, s) for s in rows]


@router.get("/shift-swaps/approvals", response_model=list[ShiftSwapOut])
def swap_approvals(user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Antrean atasan: tukar yang menunggu persetujuan atasan pengaju."""
    own = _own(db, user)
    rows = db.execute(
        select(ShiftSwapRequest).where(
            ShiftSwapRequest.tenant_id == user.tenant_id,
            ShiftSwapRequest.status == "menunggu_atasan")
        .order_by(ShiftSwapRequest.created_at)
    ).scalars().all()
    out = []
    for swap in rows:
        if leave_service.is_manager_of(db, user.tenant_id, own.id,
                                       swap.requester_employment_id) \
                or user.is_superadmin:
            out.append(_swap_out(db, swap))
    return out


@router.post("/shift-swaps/{swap_id}/partner-decision",
             response_model=ShiftSwapOut)
def partner_decision(swap_id: uuid.UUID, body: ShiftSwapDecision,
                     request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    own = _own(db, user)
    swap = _get_swap(db, user, swap_id)
    if str(swap.partner_employment_id) != str(own.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tukar shift tidak ditemukan")
    if swap.status != "menunggu_partner":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan sudah diputuskan partner")
    if body.approve:
        swap.status = "menunggu_atasan"
        swap.partner_decided_at = datetime.now(timezone.utc)
    else:
        if not (body.reason or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Alasan penolakan wajib diisi")
        swap.status = "ditolak"
        swap.decision_reason = body.reason
        swap.decided_at = datetime.now(timezone.utc)
    db.flush()
    if body.approve:
        # Kabari atasan pengaju bahwa ada tukar menunggu persetujuannya.
        requester_job_manager = None
        from app.models import JobInfo
        job = ed.as_of(db=db, tenant_id=user.tenant_id, model=JobInfo,
                           identity_field="employment_id",
                           identity_value=swap.requester_employment_id,
                           as_of_date=date.today())
        if job is not None:
            requester_job_manager = job.manager_employment_id
        if requester_job_manager is not None:
            notify_service.notify_employment(
                db, tenant_id=user.tenant_id,
                employment_id=requester_job_manager,
                category="persetujuan",
                title="🔁 Tukar shift menunggu persetujuan atasan",
                body=f"{_name(db, swap.requester_employment_id)} ↔ "
                     f"{_name(db, swap.partner_employment_id)} pada "
                     f"{swap.swap_date.isoformat()}.",
                link="/roster")
    else:
        notify_service.notify_employment(
            db, tenant_id=user.tenant_id,
            employment_id=swap.requester_employment_id,
            category="persetujuan",
            title="❌ Permintaan tukar shift ditolak partner",
            body=body.reason or "", link="/roster")
    _audit(db, user, request, "partner_decision", swap,
           reason=body.reason)
    out = _swap_out(db, swap)
    db.commit()
    return out


def _apply_one_day(db: Session, user: User, employment_id,
                   day: date, new_shift_id) -> None:
    """Jadikan shift pada `day` = new_shift_id dengan memecah rentang."""
    assignment = db.execute(
        select(ShiftAssignment).where(
            ShiftAssignment.tenant_id == user.tenant_id,
            ShiftAssignment.employment_id == employment_id,
            ShiftAssignment.valid_from <= day,
            ShiftAssignment.valid_to >= day)
        .order_by(ShiftAssignment.valid_from.desc())
    ).scalars().first()
    if assignment is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Penugasan shift pada tanggal tukar sudah berubah; "
            "batalkan dan ajukan ulang")
    if str(assignment.shift_id) == str(new_shift_id):
        return
    old_shift_id = assignment.shift_id
    if assignment.valid_from == day and assignment.valid_to == day:
        assignment.shift_id = new_shift_id
        db.flush()
        return
    if assignment.valid_from < day:
        before = ShiftAssignment(
            tenant_id=user.tenant_id, employment_id=employment_id,
            shift_id=old_shift_id, valid_from=assignment.valid_from,
            valid_to=day - timedelta(days=1))
        db.add(before)
    if assignment.valid_to > day:
        after = ShiftAssignment(
            tenant_id=user.tenant_id, employment_id=employment_id,
            shift_id=old_shift_id, valid_from=day + timedelta(days=1),
            valid_to=assignment.valid_to)
        db.add(after)
    assignment.valid_from = day
    assignment.valid_to = day
    assignment.shift_id = new_shift_id
    db.flush()


@router.post("/shift-swaps/{swap_id}/manager-decision",
             response_model=ShiftSwapOut)
def manager_decision(swap_id: uuid.UUID, body: ShiftSwapDecision,
                     request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    own = _own(db, user)
    swap = _get_swap(db, user, swap_id)
    if swap.status != "menunggu_atasan":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan tidak sedang menunggu atasan")
    if not (user.is_superadmin or leave_service.is_manager_of(
            db, user.tenant_id, own.id, swap.requester_employment_id)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Persetujuan tukar shift hanya oleh atasan langsung pengaju")
    now = datetime.now(timezone.utc)
    if body.approve:
        _apply_one_day(db, user, swap.requester_employment_id,
                       swap.swap_date, swap.partner_shift_id)
        _apply_one_day(db, user, swap.partner_employment_id,
                       swap.swap_date, swap.requester_shift_id)
        swap.status = "disetujui"
        swap.applied_at = now
    else:
        if not (body.reason or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Alasan penolakan wajib diisi")
        swap.status = "ditolak"
        swap.decision_reason = body.reason
    swap.decided_by_user_id = user.id
    swap.decided_at = now
    db.flush()
    for emp_id in (swap.requester_employment_id,
                   swap.partner_employment_id):
        notify_service.notify_employment(
            db, tenant_id=user.tenant_id, employment_id=emp_id,
            category="persetujuan",
            title=("✅ Tukar shift disetujui atasan" if body.approve
                   else "❌ Tukar shift ditolak atasan"),
            body=f"Tukar shift tanggal {swap.swap_date.isoformat()}"
                 + ("" if body.approve else f": {body.reason or ''}"),
            link="/roster")
    _audit(db, user, request, "manager_decision", swap,
           reason=body.reason)
    out = _swap_out(db, swap)
    db.commit()
    return out


@router.post("/shift-swaps/{swap_id}/cancel", response_model=ShiftSwapOut)
def cancel_swap(swap_id: uuid.UUID, request: Request,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    own = _own(db, user)
    swap = _get_swap(db, user, swap_id)
    if str(swap.requester_employment_id) != str(own.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Permintaan tukar shift tidak ditemukan")
    if swap.status not in ACTIVE_SWAP_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Permintaan sudah diputuskan")
    swap.status = "dibatalkan"
    db.flush()
    _audit(db, user, request, "cancel", swap)
    out = _swap_out(db, swap)
    db.commit()
    return out
