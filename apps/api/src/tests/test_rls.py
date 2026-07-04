import uuid

import pytest
from sqlalchemy import select

from src.db.base import async_sessionmaker_factory
from src.db.models.employee import Employee
from src.db.models.organization import Organization
from src.db.session import tenant_scoped_session


pytestmark = pytest.mark.rls


@pytest.mark.asyncio
async def test_tenant_rls_isolation() -> None:
    # 1. Create two organizations using a platform session (no tenant context set)
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()

    async with async_sessionmaker_factory() as session:
        async with session.begin():
            org_a = Organization(id=org_a_id, name="Tenant A")
            org_b = Organization(id=org_b_id, name="Tenant B")
            session.add(org_a)
            session.add(org_b)

    # 2. Insert an employee under Org A's tenant session
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_a_id)) as session_a:
        emp = Employee(
            organization_id=org_a_id,
            email="employee@tenanta.com",
            full_name="Alice Tenant A",
            role="developer",
            timezone="UTC",
            status="active",
        )
        session_a.add(emp)

    # 3. Query employees from Org B's tenant session
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_b_id)) as session_b:
        result_b = await session_b.execute(select(Employee))
        employees_b = result_b.scalars().all()
        assert len(employees_b) == 0, "Tenant B should not see Tenant A's employees"

    # 4. Query employees from Org A's tenant session
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_a_id)) as session_a_read:
        result_a = await session_a_read.execute(select(Employee))
        employees_a = result_a.scalars().all()
        assert len(employees_a) == 1, "Tenant A should see its own employee"
        assert employees_a[0].email == "employee@tenanta.com"

    # 5. Query from a session without setting the context (fails closed)
    async with async_sessionmaker_factory() as session_none:
        result_none = await session_none.execute(select(Employee))
        employees_none = result_none.scalars().all()
        assert len(employees_none) == 0, "Un-contextualized session should see no rows (fail closed)"
