import zoneinfo
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.db.models.employee import Employee

logger = logging.getLogger(__name__)

router = APIRouter(tags=["employees"])


class EmployeeUpdate(BaseModel):
    full_name: str | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                zoneinfo.ZoneInfo(v)
            except Exception:
                raise ValueError("Invalid IANA timezone")
        return v


from datetime import datetime, timezone

class EmployeeRecordResponse(BaseModel):
    id: str
    email: str | None = None
    full_name: str | None = None
    timezone: str
    role: str
    status: str
    deleted_at: str | None = None


class EmployeeMeResponse(BaseModel):
    id: str
    email: str | None = None
    full_name: str | None = None
    timezone: str
    role: str
    organization_id: str


class EmployeeUpdateMeResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    full_name: str | None = None
    timezone: str
    role: str


class EmployeeTerminateResponse(BaseModel):
    id: uuid.UUID
    status: str
    deleted_at: datetime


@router.get("/employees", response_model=list[EmployeeRecordResponse])
async def get_employees(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[EmployeeRecordResponse]:
    """
    Retrieve all active and soft-deleted employee records for the organization.
    
    Accessible only by admins. RLS automatically filters results to the tenant organization.
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
            detail="Only admins can view employee records",
        )
    stmt = select(Employee).order_by(Employee.full_name.asc())
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        EmployeeRecordResponse(
            id=str(r.id),
            email=r.email,
            full_name=r.full_name,
            timezone=r.timezone,
            role=r.role,
            status=r.status,
            deleted_at=r.deleted_at.isoformat() if r.deleted_at else None,
        )
        for r in records
    ]


@router.get("/employees/me", response_model=EmployeeMeResponse, status_code=status.HTTP_200_OK)
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EmployeeMeResponse:
    """
    Retrieve the profile details of the currently authenticated employee.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    stmt = select(Employee).where(Employee.id == ctx.user_id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    return EmployeeMeResponse(
        id=str(employee.id),
        email=employee.email,
        full_name=employee.full_name,
        timezone=employee.timezone,
        role=employee.role,
        organization_id=str(employee.organization_id),
    )


@router.patch("/employees/me", response_model=EmployeeUpdateMeResponse, status_code=status.HTTP_200_OK)
async def update_me(
    payload: EmployeeUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EmployeeUpdateMeResponse:
    """
    Update profile details (e.g. full name, timezone) of the currently authenticated employee.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    stmt = select(Employee).where(Employee.id == ctx.user_id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if payload.full_name is not None:
        employee.full_name = payload.full_name
    if payload.timezone is not None:
        employee.timezone = payload.timezone

    await db.flush()
    return EmployeeUpdateMeResponse(
        id=employee.id,
        email=employee.email,
        full_name=employee.full_name,
        timezone=employee.timezone,
        role=employee.role,
    )


@router.patch("/employees/{employee_id}", response_model=EmployeeUpdateMeResponse, status_code=status.HTTP_200_OK)
async def update_employee(
    employee_id: uuid.UUID,
    payload: EmployeeUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EmployeeUpdateMeResponse:
    """
    Update profile details of a specific employee.
    
    Admins can update anyone's profile. Normal employees can only update their own profile.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Authorization check
    if ctx.role != "admin" and ctx.user_id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    stmt = select(Employee).where(Employee.id == employee_id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    if payload.full_name is not None:
        employee.full_name = payload.full_name
    if payload.timezone is not None:
        employee.timezone = payload.timezone

    await db.flush()
    return EmployeeUpdateMeResponse(
        id=employee.id,
        email=employee.email,
        full_name=employee.full_name,
        timezone=employee.timezone,
        role=employee.role,
    )


@router.post("/employees/{employee_id}/terminate", response_model=EmployeeTerminateResponse, status_code=status.HTTP_200_OK)
async def terminate_employee(
    employee_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EmployeeTerminateResponse:
    """
    Soft-terminate an employee's profile.
    
    Sets the employee's status to 'terminated' and populates the deleted_at timestamp.
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
            detail="Only admins can terminate employees",
        )

    stmt = select(Employee).where(
        Employee.id == employee_id,
        Employee.organization_id == ctx.organization_id,
    )
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    employee.status = "terminated"
    employee.deleted_at = datetime.now(timezone.utc)

    await db.flush()
    return EmployeeTerminateResponse(
        id=employee.id,
        status=employee.status,
        deleted_at=employee.deleted_at,
    )

