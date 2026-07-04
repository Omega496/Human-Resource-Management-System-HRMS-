import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.db.base import superuser_sessionmaker
from src.db.models.leave_request import LeaveRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["leave"])


class LeaveRequestCreate(BaseModel):
    employee_id: uuid.UUID | None = None
    start_time: datetime
    end_time: datetime


class LeaveRequestResponse(BaseModel):
    id: str
    employee_id: str
    start_time: str
    end_time: str
    status: str


class LeaveRequestCreateResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    status: str


@router.get("/leave-requests", response_model=list[LeaveRequestResponse])
async def get_leave_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[LeaveRequestResponse]:
    """
    Retrieve leave requests.
    
    Admins can view all leave requests in the organization. Normal employees can only view 
    their own leave requests.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    stmt = select(LeaveRequest)
    if ctx.role != "admin":
        stmt = stmt.where(LeaveRequest.employee_id == ctx.user_id)
    stmt = stmt.order_by(LeaveRequest.start_time.desc())
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        LeaveRequestResponse(
            id=str(r.id),
            employee_id=str(r.employee_id),
            start_time=r.start_time.isoformat(),
            end_time=r.end_time.isoformat(),
            status=r.status,
        )
        for r in records
    ]


@router.post("/leave-requests", response_model=LeaveRequestCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_leave_request(
    payload: LeaveRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LeaveRequestCreateResponse:
    """
    Create a new leave request.
    
    Validates that the end time is after the start time, checks for overlapping active 
    leave requests using the exclusion constraint, and raises a conflict error if overlaps exist.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    target_employee_id = payload.employee_id or ctx.user_id

    # Authorization: normal employee can only submit for themselves; admin can submit for anyone.
    if ctx.role != "admin" and ctx.user_id != target_employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    # Validate that end_time > start_time before attempting insert
    if payload.end_time <= payload.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time",
        )

    leave_req = LeaveRequest(
        organization_id=ctx.organization_id,
        employee_id=target_employee_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status="pending",
    )
    db.add(leave_req)

    try:
        await db.flush()
    except (IntegrityError, DBAPIError) as e:
        orig = getattr(e, "orig", None)
        sqlstate = getattr(orig, "sqlstate", None)

        # SQLSTATE 23P01 = exclusion_violation, 40P01 = deadlock_detected
        if sqlstate in ("23P01", "40P01"):
            # Use a separate diagnostic session since the current session transaction is aborted
            async with superuser_sessionmaker() as diagnostic_session:
                conflict_stmt = (
                    select(LeaveRequest)
                    .where(
                        LeaveRequest.employee_id == target_employee_id,
                        LeaveRequest.status.in_(["pending", "approved"]),
                        LeaveRequest.start_time <= payload.end_time,
                        LeaveRequest.end_time >= payload.start_time,
                    )
                    .limit(1)
                )
                res = await diagnostic_session.execute(conflict_stmt)
                conflict = res.scalar_one_or_none()

            if conflict:
                detail = f"Overlapping leave request already exists: {conflict.start_time.isoformat()} to {conflict.end_time.isoformat()} (status: {conflict.status})"
            else:
                detail = "Overlapping leave request already exists."

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail,
            )
        raise e

    # Refresh to load db defaults/generated columns
    await db.refresh(leave_req)
    return LeaveRequestCreateResponse(
        id=leave_req.id,
        employee_id=leave_req.employee_id,
        start_time=leave_req.start_time,
        end_time=leave_req.end_time,
        status=leave_req.status,
    )


@router.patch("/leave-requests/{request_id}/approve", response_model=LeaveRequestCreateResponse, status_code=status.HTTP_200_OK)
async def approve_leave_request(
    request_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LeaveRequestCreateResponse:
    """
    Approve a pending leave request.
    
    Only accessible by admins.
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
            detail="Only admins can approve/reject leave requests.",
        )

    stmt = select(LeaveRequest).where(LeaveRequest.id == request_id)
    res = await db.execute(stmt)
    leave_req = res.scalar_one_or_none()

    if not leave_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found",
        )

    leave_req.status = "approved"
    await db.flush()

    return LeaveRequestCreateResponse(
        id=leave_req.id,
        employee_id=leave_req.employee_id,
        start_time=leave_req.start_time,
        end_time=leave_req.end_time,
        status=leave_req.status,
    )


@router.patch("/leave-requests/{request_id}/reject", response_model=LeaveRequestCreateResponse, status_code=status.HTTP_200_OK)
async def reject_leave_request(
    request_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> LeaveRequestCreateResponse:
    """
    Reject a pending leave request.
    
    Excludes the request from the partial overlapping constraint check immediately, 
    allowing other overlapping requests to be submitted.
    Only accessible by admins.
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
            detail="Only admins can approve/reject leave requests.",
        )

    stmt = select(LeaveRequest).where(LeaveRequest.id == request_id)
    res = await db.execute(stmt)
    leave_req = res.scalar_one_or_none()

    if not leave_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found",
        )

    # Explanation of partial index exclusion constraint:
    # The table has a partial gist exclusion constraint `no_overlapping_active_leave`
    # defined with the filter `WHERE (status IN ('pending', 'approved'))`.
    # When we change the status from 'pending' to 'rejected', the row no longer matches
    # the index filter. Consequently, it is excluded from the GiST index, which immediately
    # allows new overlapping requests for the same employee to succeed.
    leave_req.status = "rejected"
    await db.flush()

    return LeaveRequestCreateResponse(
        id=leave_req.id,
        employee_id=leave_req.employee_id,
        start_time=leave_req.start_time,
        end_time=leave_req.end_time,
        status=leave_req.status,
    )
