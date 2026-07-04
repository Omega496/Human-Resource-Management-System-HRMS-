import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.db.models.payroll_ledger_line import PayrollLedgerLine
from src.db.models.payroll_rule import PayrollRule
from src.modules.payroll.service import PayrollRuleResolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payroll", tags=["payroll"])


class CloseMonthPayload(BaseModel):
    organization_id: uuid.UUID
    ledger_month: date


class AdjustmentPayload(BaseModel):
    original_line_id: uuid.UUID
    reason: str


class PayrollLineResponse(BaseModel):
    id: str
    organization_id: str
    employee_id: str
    ledger_month: str
    line_type: str
    amount_cents: int
    currency: str
    status: str
    adjustment_of: str | None = None
    computed_from_rule_id: str | None = None
    created_at: str
    closed_at: str | None = None


class CloseMonthResponse(BaseModel):
    closed_count: int


class AdjustmentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    ledger_month: date
    line_type: str
    amount_cents: int
    currency: str
    status: str
    adjustment_of: uuid.UUID | None = None
    computed_from_rule_id: uuid.UUID | None = None


@router.get("/lines", response_model=list[PayrollLineResponse])
async def get_payroll_lines(
    employee_id: uuid.UUID,
    month: str,  # format YYYY-MM
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[PayrollLineResponse]:
    """
    Retrieve payroll ledger lines for a specific employee and month.
    
    Accessible only by admins. RLS enforces organization boundary.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view payroll records",
        )
    try:
        y, m = map(int, month.split("-"))
        target_date = date(y, m, 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid month format. Expected YYYY-MM.",
        )

    stmt = (
        select(PayrollLedgerLine)
        .where(
            PayrollLedgerLine.organization_id == ctx.organization_id,
            PayrollLedgerLine.employee_id == employee_id,
            PayrollLedgerLine.ledger_month == target_date,
        )
        .order_by(PayrollLedgerLine.created_at.desc())
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        PayrollLineResponse(
            id=str(r.id),
            organization_id=str(r.organization_id),
            employee_id=str(r.employee_id),
            ledger_month=r.ledger_month.isoformat(),
            line_type=r.line_type,
            amount_cents=r.amount_cents,
            currency=r.currency,
            status=r.status,
            adjustment_of=str(r.adjustment_of) if r.adjustment_of else None,
            computed_from_rule_id=str(r.computed_from_rule_id) if r.computed_from_rule_id else None,
            created_at=r.created_at.isoformat(),
            closed_at=r.closed_at.isoformat() if r.closed_at else None,
        )
        for r in records
    ]


@router.post("/close-month", response_model=CloseMonthResponse, status_code=status.HTTP_200_OK)
async def close_month(
    payload: CloseMonthPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CloseMonthResponse:
    """
    Close a payroll month for the organization.
    
    Locks all open ledger lines for the specified month, preventing further modifications.
    Closed lines can only be adjusted in subsequent open months. Accessible only by admins.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can close payroll months",
        )

    # Ensure requested org_id matches tenant context
    if payload.organization_id != ctx.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization mismatch",
        )

    # Convert ledger_month to first-of-month date
    target_month = date(payload.ledger_month.year, payload.ledger_month.month, 1)

    # Perform bulk update on open lines for this month
    stmt = (
        update(PayrollLedgerLine)
        .where(
            PayrollLedgerLine.organization_id == payload.organization_id,
            PayrollLedgerLine.ledger_month == target_month,
            PayrollLedgerLine.status == "open",
        )
        .values(
            status="closed",
            closed_at=func.now(),
        )
    )
    result = await db.execute(stmt)
    await db.flush()

    return CloseMonthResponse(closed_count=result.rowcount)


@router.post("/adjustments", response_model=AdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    payload: AdjustmentPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdjustmentResponse:
    """
    Create a payroll adjustment against a closed payroll ledger line.
    
    Resolves the rule that was valid *as of* the original line's month, recomputes 
    the correct amount, and appends a delta adjustment line to the current open month.
    Closed months are strictly immutable. Accessible only by admins.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can submit adjustments",
        )

    # 1. Look up the original line (load relationship with rule)
    stmt = (
        select(PayrollLedgerLine)
        .options(selectinload(PayrollLedgerLine.computed_from_rule))
        .where(
            PayrollLedgerLine.id == payload.original_line_id,
            PayrollLedgerLine.organization_id == ctx.organization_id,
        )
    )
    res = await db.execute(stmt)
    original_line = res.scalar_one_or_none()

    if not original_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original payroll line not found",
        )

    # 2. Must be closed to be adjusted
    if original_line.status != "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Adjustments are only allowed against closed payroll lines. Modify open lines directly.",
        )

    original_rule = original_line.computed_from_rule
    if not original_rule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Original line was not computed from a payroll rule",
        )

    # 3. Re-resolve the rule valid *as of* the original line's ledger month
    as_of = datetime(
        original_line.ledger_month.year,
        original_line.ledger_month.month,
        original_line.ledger_month.day,
        tzinfo=timezone.utc,
    )

    resolved_rule = await PayrollRuleResolver.resolve(
        db=db,
        organization_id=original_line.organization_id,
        rule_type=original_rule.rule_type,
        rule_key=original_rule.rule_key,
        as_of=as_of,
    )

    if not resolved_rule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No matching rule was valid during the target month",
        )

    # 4. Recompute amount based on resolved rule
    correct_amount = resolved_rule.rule_value.get("amount_cents")
    if correct_amount is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resolved rule does not contain amount_cents value",
        )

    delta = correct_amount - original_line.amount_cents

    # 5. Insert new row in current open month
    today = date.today()
    current_month = date(today.year, today.month, 1)

    adjustment_line = PayrollLedgerLine(
        organization_id=original_line.organization_id,
        employee_id=original_line.employee_id,
        ledger_month=current_month,
        line_type="adjustment",
        amount_cents=delta,
        currency=original_line.currency,
        status="open",
        adjustment_of=original_line.id,
        computed_from_rule_id=resolved_rule.id,
    )
    db.add(adjustment_line)
    await db.flush()
    await db.refresh(adjustment_line)

    return AdjustmentResponse(
        id=adjustment_line.id,
        organization_id=adjustment_line.organization_id,
        employee_id=adjustment_line.employee_id,
        ledger_month=adjustment_line.ledger_month,
        line_type=adjustment_line.line_type,
        amount_cents=adjustment_line.amount_cents,
        currency=adjustment_line.currency,
        status=adjustment_line.status,
        adjustment_of=adjustment_line.adjustment_of,
        computed_from_rule_id=adjustment_line.computed_from_rule_id,
    )
