import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.db.models.employee import Employee
from src.modules.offboarding.service import PseudonymizationService

logger = logging.getLogger(__name__)

from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/offboarding", tags=["offboarding"])


class PseudonymizationResponse(BaseModel):
    original_employee_id: uuid.UUID
    pseudonym_hash: str
    structural_cohort: str
    pseudonymized_at: datetime
    requested_by: str


@router.post("/{employee_id}/forget", response_model=PseudonymizationResponse, status_code=status.HTTP_200_OK)
async def forget_employee(
    employee_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PseudonymizationResponse:
    """
    Process GDPR "Right to be Forgotten" (pseudonymization) request.
    
    Checks that the target employee is terminated, validates authorization (admin of same 
    org or the employee themselves), updates the database using structural cohort hashing, 
    and inserts a record in the pseudonymization keys table.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # 1. Fetch employee to check organization and status
    stmt = select(Employee).where(Employee.id == employee_id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found",
        )

    # 2. Authorization check: must be admin of the same org, or the employee themselves
    is_admin_of_org = (ctx.role == "admin" and ctx.organization_id == employee.organization_id)
    is_self = (ctx.user_id == employee_id)

    if not (is_admin_of_org or is_self):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied. Only admins or the employee themselves can trigger pseudonymization.",
        )

    # Determine requested_by value
    requested_by = "employee_request" if is_self else "org_admin_request"

    try:
        mapping = await PseudonymizationService.pseudonymize(
            db=db,
            employee_id=employee_id,
            requested_by=requested_by,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return PseudonymizationResponse(
        original_employee_id=mapping.original_employee_id,
        pseudonym_hash=mapping.pseudonym_hash,
        structural_cohort=mapping.structural_cohort,
        pseudonymized_at=mapping.pseudonymized_at,
        requested_by=mapping.requested_by,
    )
