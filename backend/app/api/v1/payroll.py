"""API payroll Sprint 4: komponen gaji, assignment, policy, run/lock,
slip PDF, file transfer bank (PAY-001, PAY-007, PAY-008, PAY-009, PAY-010).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import client_ip, snapshot
from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models import (
    CompAssignment,
    CompAssignmentInfo,
    Employment,
    LegalEntityInfo,
    PayrollLine,
    PayrollRun,
    SalaryComponent,
    SalaryComponentInfo,
    User,
)
from app.schemas.schemas import (
    CompAssignmentCreate,
    CompAssignmentOut,
    PayrollLineOut,
    PayrollPolicyOut,
    PayrollPolicyUpdate,
    PayrollRunCreate,
    PayrollRunOut,
    SalaryComponentCreate,
    SalaryComponentOut,
    SalaryComponentVersionCreate,
)
from app.services import effective_dating as ed
from app.services import payroll as payroll_service
from app.services import payslip as payslip_service
from app.services import payslip_pin as pin_service
from app.services import population as population_service
from app.services import rbp as rbp_service
from app.services.audit import write_audit

router = APIRouter(tags=["payroll"])

_COMP_FIELDS = [
    "id", "code", "name", "kind", "calc_type", "amount_or_formula",
    "is_taxable", "is_bpjs_base", "sequence", "valid_from", "valid_to",
]


def _comp_or_404(db: Session, tenant_id, component_id: uuid.UUID) -> SalaryComponent:
    comp = db.get(SalaryComponent, component_id)
    if comp is None or comp.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Komponen tidak ditemukan")
    return comp


def _run_or_404(db: Session, tenant_id, run_id: uuid.UUID) -> PayrollRun:
    run = db.get(PayrollRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payroll run tidak ditemukan")
    return run


def _merge_comp(comp: SalaryComponent, info: SalaryComponentInfo | None,
                as_of: date) -> SalaryComponentOut:
    return SalaryComponentOut(
        id=comp.id, code=comp.code, name=comp.name,
        kind=info.kind if info else None,
        calc_type=info.calc_type if info else None,
        amount_or_formula=info.amount_or_formula if info else None,
        is_taxable=info.is_taxable if info else None,
        is_bpjs_base=info.is_bpjs_base if info else None,
        sequence=info.sequence if info else None,
        valid_from=info.valid_from if info else None,
        valid_to=info.valid_to if info else None,
    )


# ------------------------------------------------------------------ komponen
@router.post(
    "/payroll/components",
    response_model=SalaryComponentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("salary_component", "insert"))],
)
def create_component(
    body: SalaryComponentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        comp = payroll_service.create_component(
            db=db, tenant_id=user.tenant_id,
            name=body.name, code=body.code, kind=body.kind,
            calc_type=body.calc_type, amount_or_formula=body.amount_or_formula,
            is_taxable=body.is_taxable, is_bpjs_base=body.is_bpjs_base,
            sequence=body.sequence, valid_from=body.valid_from,
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    info = ed.as_of(
        db=db, tenant_id=user.tenant_id, model=SalaryComponentInfo,
        identity_field="component_id", identity_value=comp.id,
        as_of_date=body.valid_from,
    )
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="create", object_type="salary_component", object_id=comp.id,
        new_values={"code": comp.code, "name": comp.name},
        reason=body.reason, channel="api", ip=client_ip(request),
    )
    db.commit()
    return _merge_comp(comp, info, body.valid_from)


@router.get(
    "/payroll/components",
    response_model=list[SalaryComponentOut],
    dependencies=[Depends(require_permission("salary_component", "view"))],
)
def list_components(
    as_of: date = Query(default_factory=date.today),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comps = (
        db.execute(
            select(SalaryComponent)
            .where(SalaryComponent.tenant_id == user.tenant_id)
            .order_by(SalaryComponent.code)
        )
        .scalars()
        .all()
    )
    out = []
    for comp in comps:
        info = ed.as_of(
            db=db, tenant_id=user.tenant_id, model=SalaryComponentInfo,
            identity_field="component_id", identity_value=comp.id,
            as_of_date=as_of,
        )
        out.append(_merge_comp(comp, info, as_of))
    return out


@router.post(
    "/payroll/components/{component_id}/versions",
    response_model=SalaryComponentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("salary_component", "insert"))],
)
def version_component(
    component_id: uuid.UUID,
    body: SalaryComponentVersionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comp = _comp_or_404(db, user.tenant_id, component_id)
    try:
        info = payroll_service.update_component(
            db=db, tenant_id=user.tenant_id, component_id=comp.id,
            kind=body.kind, calc_type=body.calc_type,
            amount_or_formula=body.amount_or_formula,
            is_taxable=body.is_taxable, is_bpjs_base=body.is_bpjs_base,
            sequence=body.sequence, valid_from=body.valid_from,
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="insert", object_type="salary_component_info",
        object_id=info.id,
        new_values=snapshot(info, _COMP_FIELDS[3:]),
        reason=body.reason, channel="api", ip=client_ip(request),
    )
    db.commit()
    return _merge_comp(comp, info, body.valid_from)


# ------------------------------------------------------------------ assignment
@router.post(
    "/payroll/assignments",
    response_model=CompAssignmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("salary_component", "insert"))],
)
def assign_component(
    body: CompAssignmentCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comp = _comp_or_404(db, user.tenant_id, body.component_id)
    try:
        assignment = payroll_service.assign_component(
            db=db, tenant_id=user.tenant_id,
            employment_id=body.employment_id, component_id=comp.id,
            valid_from=body.valid_from,
            override_amount=body.override_amount,
            is_enabled=body.is_enabled,
            event=body.event, event_reason=body.event_reason,
            created_by=user.id,
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    info = ed.as_of(
        db=db, tenant_id=user.tenant_id, model=CompAssignmentInfo,
        identity_field="assignment_id", identity_value=assignment.id,
        as_of_date=body.valid_from,
    )
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="create", object_type="comp_assignment",
        object_id=assignment.id,
        new_values={"employment_id": str(body.employment_id),
                    "component_code": comp.code},
        reason=body.reason, channel="api", ip=client_ip(request),
    )
    db.commit()
    return CompAssignmentOut(
        id=assignment.id, employment_id=assignment.employment_id,
        component_id=assignment.component_id, component_code=comp.code,
        override_amount=info.override_amount if info else None,
        is_enabled=info.is_enabled if info else None,
        valid_from=info.valid_from if info else None,
        valid_to=info.valid_to if info else None,
    )


@router.get(
    "/payroll/assignments",
    response_model=list[CompAssignmentOut],
    dependencies=[Depends(require_permission("salary_component", "view"))],
)
def list_assignments(
    employment_id: uuid.UUID,
    as_of: date = Query(default_factory=date.today),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assigns = (
        db.execute(
            select(CompAssignment).where(
                CompAssignment.tenant_id == user.tenant_id,
                CompAssignment.employment_id == employment_id,
            )
        )
        .scalars()
        .all()
    )
    out = []
    for a in assigns:
        comp = db.get(SalaryComponent, a.component_id)
        info = ed.as_of(
            db=db, tenant_id=user.tenant_id, model=CompAssignmentInfo,
            identity_field="assignment_id", identity_value=a.id,
            as_of_date=as_of,
        )
        if info is None:
            continue
        out.append(CompAssignmentOut(
            id=a.id, employment_id=a.employment_id,
            component_id=a.component_id,
            component_code=comp.code if comp else None,
            override_amount=info.override_amount,
            is_enabled=info.is_enabled,
            valid_from=info.valid_from, valid_to=info.valid_to,
        ))
    return out


# ------------------------------------------------------------------ policy
@router.get(
    "/payroll/policy",
    response_model=PayrollPolicyOut,
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def get_policy(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return payroll_service.get_policy(db, user.tenant_id)


@router.put(
    "/payroll/policy",
    response_model=PayrollPolicyOut,
    dependencies=[Depends(require_permission("payroll", "correct"))],
)
def update_policy(
    body: PayrollPolicyUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policy = payroll_service.get_policy(db, user.tenant_id)
    old = {"pph21_method": policy.pph21_method, "thr_basis": policy.thr_basis}
    if body.pph21_method:
        policy.pph21_method = body.pph21_method
    if body.thr_basis:
        policy.thr_basis = body.thr_basis
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="correct", object_type="payroll_policy",
        object_id=policy.id, old_values=old,
        new_values={"pph21_method": policy.pph21_method,
                    "thr_basis": policy.thr_basis},
        reason=body.reason, channel="api", ip=client_ip(request),
    )
    db.commit()
    return policy


# ------------------------------------------------------------------ run & lock
@router.post(
    "/payroll/runs",
    response_model=PayrollRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("payroll", "insert"))],
)
def create_run(
    body: PayrollRunCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        run = payroll_service.create_run(
            db=db, tenant_id=user.tenant_id, period=body.period,
            method=body.pph21_method, include_thr=body.include_thr,
            thr_holiday_date=body.thr_holiday_date,
            overtime_hours=body.overtime_hours, notes=body.notes,
            created_by=user.id,
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="create", object_type="payroll_run", object_id=run.id,
        new_values={"period": run.period, "headcount": run.headcount,
                    "totals": run.totals},
        reason=body.notes or "Payroll run", channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return run


@router.get(
    "/payroll/runs",
    response_model=list[PayrollRunOut],
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def list_runs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(PayrollRun)
            .where(PayrollRun.tenant_id == user.tenant_id)
            .order_by(PayrollRun.period.desc())
        )
        .scalars()
        .all()
    )


@router.get(
    "/payroll/runs/{run_id}",
    response_model=PayrollRunOut,
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def get_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _run_or_404(db, user.tenant_id, run_id)


@router.get(
    "/payroll/runs/{run_id}/lines",
    response_model=list[PayrollLineOut],
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def get_run_lines(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _run_or_404(db, user.tenant_id, run_id)
    return (
        db.execute(
            select(PayrollLine)
            .where(PayrollLine.payroll_run_id == run.id)
            .order_by(PayrollLine.person_name)
        )
        .scalars()
        .all()
    )


@router.post(
    "/payroll/runs/{run_id}/lock",
    response_model=PayrollRunOut,
    dependencies=[Depends(require_permission("payroll", "correct"))],
)
def lock_run(
    run_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _run_or_404(db, user.tenant_id, run_id)
    try:
        run = payroll_service.lock_run(
            db=db, tenant_id=user.tenant_id, run_id=run.id, locked_by=user.id
        )
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payroll run tidak ditemukan")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="update", object_type="payroll_run", object_id=run.id,
        old_values={"status": "draft"},
        new_values={"status": "locked", "period": run.period},
        reason=f"Kunci payroll periode {run.period}", channel="api",
        ip=client_ip(request),
    )
    db.commit()
    return run


# ------------------------------------------------------------------ slip & bank
def _line_or_404(db: Session, tenant_id, run: PayrollRun,
                 employment_id: uuid.UUID) -> PayrollLine:
    line = (
        db.execute(
            select(PayrollLine).where(
                PayrollLine.payroll_run_id == run.id,
                PayrollLine.employment_id == employment_id,
            )
        )
        .scalars()
        .first()
    )
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Baris slip tidak ditemukan")
    return line


def _company_name(db: Session, tenant_id, employment: Employment,
                  period: str) -> str:
    _, period_end = payroll_service._period_bounds(period)
    info = ed.as_of(
        db=db, tenant_id=tenant_id, model=LegalEntityInfo,
        identity_field="legal_entity_id",
        identity_value=employment.legal_entity_id,
        as_of_date=period_end,
    )
    return info.name if info else "-"


@router.get(
    "/payroll/runs/{run_id}/payslip/{employment_id}.pdf",
)
def payslip_pdf(
    run_id: uuid.UUID,
    employment_id: uuid.UUID,
    request: Request,
    x_payslip_pin: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _run_or_404(db, user.tenant_id, run_id)
    line = _line_or_404(db, user.tenant_id, run, employment_id)
    own = population_service.get_user_employment(db, user)
    is_own = own is not None and str(own.id) == str(employment_id)
    if not is_own and not rbp_service.has_permission(
            db, user, "payroll", "view"):
        # Slip orang lain tetap di gerbang izin payroll (HR/finance).
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Izin 'view' pada 'payroll' ditolak")
    if is_own:
        # EXP-003: slip milik sendiri wajib PIN (jalur self-service).
        result = pin_service.check_pin(db, user, x_payslip_pin)
        if result != pin_service.OK:
            db.commit()  # simpan pencatatan kegagalan/kunci
            # Selalu 403 agar klien tidak meng-logout pengguna (401
            # dicadangkan untuk sesi berakhir).
            detail = {
                pin_service.NOT_SET: "PIN_BELUM_DIATUR",
                pin_service.LOCKED: "PIN_TERKUNCI",
                pin_service.WRONG: "PIN_SALAH",
            }[result]
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail)
    # Semua unduhan slip (sendiri maupun oleh HR) tercatat di audit.
    write_audit(
        db=db, tenant_id=user.tenant_id, actor_user_id=user.id,
        action="download", object_type="payslip", object_id=line.id,
        old_values=None,
        new_values={"period": run.period,
                    "employment_id": str(employment_id),
                    "self_service": is_own},
        reason=None, channel="api", ip=client_ip(request))
    db.commit()
    employment = db.get(Employment, employment_id)
    pdf = payslip_service.render_payslip_pdf(
        line=line, period=run.period,
        company_name=_company_name(db, user.tenant_id, employment, run.period)
        if employment else "-",
    )
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename=slip-{run.period}-{line.nik}.pdf"},
    )


@router.get(
    "/payroll/runs/{run_id}/transfer-file",
    dependencies=[Depends(require_permission("payroll", "view"))],
)
def transfer_file(
    run_id: uuid.UUID,
    bank: str = Query(default="bca", pattern=r"^(?i)(bca|mandiri|bri|bni)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _run_or_404(db, user.tenant_id, run_id)
    lines = (
        db.execute(
            select(PayrollLine)
            .where(PayrollLine.payroll_run_id == run.id)
            .order_by(PayrollLine.person_name)
        )
        .scalars()
        .all()
    )
    csv_text = payslip_service.render_transfer_csv(
        lines=lines, period=run.period, bank=bank.lower())
    return PlainTextResponse(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=transfer-{bank.lower()}-{run.period}.csv"},
    )
