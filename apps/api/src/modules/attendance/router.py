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


class ClockEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    recorded_at: datetime
    client_reported_at: datetime | None = None


@router.post("/attendance/clock-in", response_model=ClockEventResponse, status_code=status.HTTP_201_CREATED)
async def clock_in(
    payload: ClockEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ClockEventResponse:
    """
    Record a clock-in event for the authenticated employee.
    
    Verifies that the employee's last status was not 'clock_in' to enforce alternating events.
    The timestamp is set by the server.
    """
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

    return ClockEventResponse(
        id=event.id,
        event_type=event.event_type,
        recorded_at=event.recorded_at,
        client_reported_at=event.client_reported_at,
    )


@router.post("/attendance/clock-out", response_model=ClockEventResponse, status_code=status.HTTP_201_CREATED)
async def clock_out(
    payload: ClockEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ClockEventResponse:
    """
    Record a clock-out event for the authenticated employee.
    
    Verifies that the employee's last status was 'clock_in' to enforce alternating events.
    The timestamp is set by the server.
    """
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

    return ClockEventResponse(
        id=event.id,
        event_type=event.event_type,
        recorded_at=event.recorded_at,
        client_reported_at=event.client_reported_at,
    )


class AttendanceHistoryItem(BaseModel):
    id: uuid.UUID
    event_type: str
    recorded_at_utc: datetime
    recorded_at_local: datetime
    client_reported_at: datetime | None = None


class AttendanceHistoryResponse(BaseModel):
    events: list[AttendanceHistoryItem]


@router.get("/attendance/history", response_model=AttendanceHistoryResponse, status_code=status.HTTP_200_OK)
async def get_history(
    request: Request,
    employee_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: AsyncSession = Depends(get_db),
) -> AttendanceHistoryResponse:
    """
    Retrieve attendance logs for an employee.
    
    Normal employees can only view their own history. Admins can view history for any employee 
    within their organization. Query-time timezone conversion is used to return local time.
    """
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
        events_data.append(
            AttendanceHistoryItem(
                id=event.id,
                event_type=event.event_type,
                recorded_at_utc=event.recorded_at,
                recorded_at_local=local_time,
                client_reported_at=event.client_reported_at,
            )
        )

    return AttendanceHistoryResponse(events=events_data)
