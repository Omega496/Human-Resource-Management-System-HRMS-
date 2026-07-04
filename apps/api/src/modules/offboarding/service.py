import hashlib
import hmac
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.employee import Employee
from src.db.models.pseudonymization_map import PseudonymizationMap
from src.modules.offboarding.secrets import secrets_provider

logger = logging.getLogger(__name__)


class PseudonymizationService:
    @staticmethod
    async def pseudonymize(
        db: AsyncSession,
        employee_id: uuid.UUID,
        requested_by: str,
    ) -> PseudonymizationMap:
        """
        Pseudonymizes a terminated employee by redacting PII, inserting a pseudonymization map,
        and preserving the structural and mathematical integrity of historical logs.
        
        Is idempotent.
        """
        # 1. Fetch employee
        stmt = select(Employee).where(Employee.id == employee_id)
        res = await db.execute(stmt)
        employee = res.scalar_one_or_none()
        if not employee:
            raise ValueError(f"Employee {employee_id} not found")

        # 2. Guard: Must be terminated
        if employee.status != "terminated" or employee.deleted_at is None:
            raise ValueError("Employee must be terminated before pseudonymization")

        # 3. Check for existing pseudonymization (Idempotency)
        stmt_map = select(PseudonymizationMap).where(
            PseudonymizationMap.original_employee_id == employee_id
        )
        res_map = await db.execute(stmt_map)
        existing_map = res_map.scalar_one_or_none()
        if existing_map:
            logger.info(f"Employee {employee_id} is already pseudonymized.")
            return existing_map

        # 4. Fetch pepper and compute hash
        pepper = secrets_provider.get("pseudonymization_pepper")
        hasher = hmac.new(pepper.encode("utf-8"), employee_id.bytes, hashlib.sha256)
        pseudonym_hash = hasher.hexdigest()

        # 5. Derive structural cohort
        # Standard: Region/Location details or department. Since we have timezone and role,
        # we roll up into: "Role: {role} / Timezone: {timezone}"
        structural_cohort = f"Role: {employee.role} / Timezone: {employee.timezone}"

        # 6. Insert mapping
        mapping = PseudonymizationMap(
            original_employee_id=employee_id,
            organization_id=employee.organization_id,
            pseudonym_hash=pseudonym_hash,
            structural_cohort=structural_cohort,
            requested_by=requested_by,
        )
        db.add(mapping)

        # 7. Redact employee fields
        employee.full_name = "Deleted User"
        # Since 'email' has a NOT NULL and UNIQUE constraint in the DB,
        # we replace it with a unique redacted email string that destroys PII
        # but satisfies database integrity constraints.
        employee.email = f"redacted-{employee_id}@redacted.local"
        employee.password_hash = None

        # 8. Update descriptive fields on historical rows (if any).
        # Since the current DB schema for clock_events, leave_requests, and payroll_ledger_lines
        # does not contain any free-form notes/description/reason fields, we do not need to update
        # them. We explicitly make sure that all numeric/financial columns (such as amount_cents)
        # are untouched to preserve mathematical integrity.

        await db.flush()
        return mapping
