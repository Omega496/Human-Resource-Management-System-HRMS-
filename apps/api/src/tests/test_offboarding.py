import uuid
import pytest
from datetime import date, datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from src.main import app
from src.db.base import superuser_sessionmaker
from src.db.models.organization import Organization
from src.db.models.employee import Employee
from src.db.models.payroll_ledger_line import PayrollLedgerLine
from src.db.models.pseudonymization_map import PseudonymizationMap
from src.modules.auth.helpers import hash_password, create_access_token


@pytest.mark.asyncio
async def test_offboarding_pseudonymization_lifecycle():
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    original_email = f"emp_{uuid.uuid4()}@paycorp.com"
    original_name = "Alice Developer"
    # Use a unique role to isolate this test's cohort calculations
    unique_role = f"developer-{uuid.uuid4()}"

    # 1. Setup organization, admin, employee, and some payroll ledger lines
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Offboarding Corp")
            session.add(org)

            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@paycorp.com",
                full_name="Admin User",
                role="admin",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(admin)

            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=original_email,
                full_name=original_name,
                role=unique_role,
                status="active",
                timezone="America/New_York",
                password_hash=hash_password("emp_pass"),
            )
            session.add(emp)

            # Insert multiple payroll ledger lines for the employee
            line1 = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 1, 1),
                line_type="base_salary",
                amount_cents=500000,
                currency="USD",
                status="closed",
            )
            line2 = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 2, 1),
                line_type="base_salary",
                amount_cents=500000,
                currency="USD",
                status="closed",
            )
            line3 = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 2, 1),
                line_type="bonus",
                amount_cents=75000,
                currency="USD",
                status="closed",
            )
            session.add_all([line1, line2, line3])

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Assert: Pseudonymizing a non-terminated employee is rejected
        forget_res = await ac.post(
            f"/offboarding/{emp_id}/forget",
            headers=headers,
        )
        assert forget_res.status_code == 400
        assert "must be terminated before pseudonymization" in forget_res.json()["detail"]

        # 3. Terminate the employee via API
        term_res = await ac.post(
            f"/employees/{emp_id}/terminate",
            headers=headers,
        )
        assert term_res.status_code == 200
        assert term_res.json()["status"] == "terminated"

        # Calculate sum of amount_cents before pseudonymization
        async with superuser_sessionmaker() as session:
            stmt_sum = select(func.sum(PayrollLedgerLine.amount_cents)).where(
                PayrollLedgerLine.employee_id == emp_id
            )
            res_sum = await session.execute(stmt_sum)
            before_sum = res_sum.scalar()
            assert before_sum == 1075000  # 500k + 500k + 75k

        # 4. Perform pseudonymization (forget endpoint)
        forget_res = await ac.post(
            f"/offboarding/{emp_id}/forget",
            headers=headers,
        )
        assert forget_res.status_code == 200
        data = forget_res.json()
        assert data["original_employee_id"] == str(emp_id)
        assert "pseudonym_hash" in data
        assert data["structural_cohort"] == f"Role: {unique_role} / Timezone: America/New_York"

        # 5. Assert: Query for original name/email returns nothing recognizable
        async with superuser_sessionmaker() as session:
            stmt_emp = select(Employee).where(Employee.id == emp_id)
            res_emp = await session.execute(stmt_emp)
            emp_db = res_emp.scalar_one()

            assert emp_db.full_name == "Deleted User"
            assert emp_db.email != original_email
            assert original_email not in emp_db.email
            assert emp_db.password_hash is None

        # 6. Assert: SUM(amount_cents) grouped by structural_cohort across the employee's payroll_ledger_lines
        # is IDENTICAL before and after pseudonymization (proves mathematical integrity).
        async with superuser_sessionmaker() as session:
            stmt_cohort_sum = (
                select(func.sum(PayrollLedgerLine.amount_cents))
                .join(
                    PseudonymizationMap,
                    PseudonymizationMap.original_employee_id == PayrollLedgerLine.employee_id,
                )
                .where(
                    PseudonymizationMap.structural_cohort == f"Role: {unique_role} / Timezone: America/New_York"
                )
            )
            res_cohort_sum = await session.execute(stmt_cohort_sum)
            after_sum = res_cohort_sum.scalar()
            
            # Print the sums to demonstrate equality
            print(f"\n[SUM Comparison] Before: {before_sum} cents, After: {after_sum} cents")
            assert before_sum == after_sum

        # 7. Assert: Idempotency - calling the forget endpoint twice is a no-op / returns same mapping
        forget_res_again = await ac.post(
            f"/offboarding/{emp_id}/forget",
            headers=headers,
        )
        assert forget_res_again.status_code == 200
        data_again = forget_res_again.json()
        assert data_again["pseudonym_hash"] == data["pseudonym_hash"]
        assert data_again["structural_cohort"] == data["structural_cohort"]
