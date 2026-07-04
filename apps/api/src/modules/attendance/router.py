import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.db.models.clock_event import ClockEvent
from src.db.models.employee import Employee

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attendance"])


class ClockEventCreate(BaseModel):
    client_reported_at: datetime | None = None


@router.post("/attendance/clock-in", status_code=status.HTTP_201_CREATED)
async def clock_in(
    payload: ClockEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Fetch last event to ensure alternation
    stmt = (
        select(ClockEvent)
        .where(ClockEvent.employee_id == ctx.user_id)
        .order_by(ClockEvent.recorded_at.desc(), ClockEvent.created_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    last_event = res.scalar_one_or_none()

    if last_event and last_event.event_type == "clock_in":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clock in. You are already clocked in.",
        )

    # Insert clock_in event, leaving recorded_at to be populated by DB default now()
    event = ClockEvent(
        organization_id=ctx.organization_id,
        employee_id=ctx.user_id,
        event_type="clock_in",
        client_reported_at=payload.client_reported_at,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    return {
        "id": event.id,
        "event_type": event.event_type,
        "recorded_at": event.recorded_at,
        "client_reported_at": event.client_reported_at,
    }


@router.post("/attendance/clock-out", status_code=status.HTTP_201_CREATED)
async def clock_out(
    payload: ClockEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Fetch last event to ensure alternation
    stmt = (
        select(ClockEvent)
        .where(ClockEvent.employee_id == ctx.user_id)
        .order_by(ClockEvent.recorded_at.desc(), ClockEvent.created_at.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    last_event = res.scalar_one_or_none()

    if not last_event or last_event.event_type == "clock_out":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot clock out. You are not clocked in.",
        )

    # Insert clock_out event, leaving recorded_at to be populated by DB default now()
    event = ClockEvent(
        organization_id=ctx.organization_id,
        employee_id=ctx.user_id,
        event_type="clock_out",
        client_reported_at=payload.client_reported_at,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)

    return {
        "id": event.id,
        "event_type": event.event_type,
        "recorded_at": event.recorded_at,
        "client_reported_at": event.client_reported_at,
    }


@router.get("/attendance/history", status_code=status.HTTP_200_OK)
async def get_history(
    request: Request,
    employee_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    target_employee_id = employee_id or ctx.user_id

    # Authorization check
    if ctx.role != "admin" and ctx.user_id != target_employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    # Build query with timezone conversion at query time
    # func.timezone(zone, timestamp) maps to: timestamp AT TIME ZONE zone
    stmt = (
        select(
            ClockEvent,
            func.timezone(Employee.timezone, ClockEvent.recorded_at).label("local_time")
        )
        .join(Employee, Employee.id == ClockEvent.employee_id)
        .where(ClockEvent.employee_id == target_employee_id)
    )

    if from_date:
        stmt = stmt.where(ClockEvent.recorded_at >= from_date)
    if to_date:
        stmt = stmt.where(ClockEvent.recorded_at <= to_date)

    stmt = stmt.order_by(ClockEvent.recorded_at.asc())

    res = await db.execute(stmt)
    rows = res.all()

    events_data = []
    for event, local_time in rows:
        events_data.append({
            "id": event.id,
            "event_type": event.event_type,
            "recorded_at_utc": event.recorded_at,
            "recorded_at_local": local_time,
            "client_reported_at": event.client_reported_at,
        })

    return {"events": events_data}
