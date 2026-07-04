import uuid

import pytest
from sqlalchemy import select

from src.db.base import async_sessionmaker_factory
from src.db.models.employee import Employee
from src.db.models.organization import Organization
from src.db.session import tenant_scoped_session


@pytest.mark.asyncio
async def test_employees_rls_adversarial() -> None:
    # 1. Create two organizations using a platform session
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()

    async with async_sessionmaker_factory() as session:
        async with session.begin():
            org_a = Organization(id=org_a_id, name="Org A")
            org_b = Organization(id=org_b_id, name="Org B")
            session.add(org_a)
            session.add(org_b)

    # 2. Insert employee for Org B under Org B's session
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_b_id)) as session_b:
        emp_b = Employee(
            organization_id=org_b_id,
            email="target@orgb.com",
            full_name="Bob Org B",
            role="developer",
            timezone="UTC",
            status="active",
        )
        session_b.add(emp_b)

    # 3. Adversarial Read: Org A session tries to read Org B's employee
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_a_id)) as session_a:
        result = await session_a.execute(select(Employee).where(Employee.organization_id == org_b_id))
        employees = result.scalars().all()
        assert len(employees) == 0, "Org A session must not read Org B's employee"

    # 4. Adversarial Write: Org A session tries to write a row with Org B's organization_id
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_a_id)) as session_a_write:
        emp_hack = Employee(
            organization_id=org_b_id,  # Target Org B
            email="hack@orgb.com",
            full_name="Hacker Alice",
            role="developer",
            timezone="UTC",
            status="active",
        )
        session_a_write.add(emp_hack)

        # We expect a database exception (InsufficientPrivilegeError in Postgres/asyncpg)
        with pytest.raises(Exception) as exc_info:
            await session_a_write.flush()

        err_str = str(exc_info.value)
        assert "InsufficientPrivilegeError" in err_str or "row-level security policy" in err_str, (
            f"Expected RLS policy rejection, but got: {err_str}"
        )
