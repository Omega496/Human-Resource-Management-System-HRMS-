import hashlib
import json
import uuid
from datetime import date, datetime, timezone, timedelta

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from src.main import app
from src.db.base import superuser_sessionmaker
from src.db.models.organization import Organization
from src.db.models.employee import Employee
from src.db.models.payroll_rule import PayrollRule
from src.db.models.payroll_ledger_line import PayrollLedgerLine
from src.modules.auth.helpers import hash_password, create_access_token


def compute_row_checksum(row) -> str:
    """Computes a SHA256 checksum of the database row's non-dynamic columns."""
    data = {
        c.name: str(getattr(row, c.name))
        for c in row.__table__.columns
    }
    # Sort keys for deterministic serialization
    serialized = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@pytest.mark.asyncio
async def test_payroll_immutability_trigger():
    # Setup org, employee, and ledger line
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Payroll Immutability Corp")
            session.add(org)
            
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@pay.com",
                full_name="Payroll Admin",
                role="admin",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(admin)
            
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"emp_{uuid.uuid4()}@pay.com",
                full_name="Payroll Employee",
                role="developer",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(emp)

            # Create an open ledger line
            line = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 3, 1),
                line_type="base_salary",
                amount_cents=300000,
                currency="USD",
                status="open",
            )
            session.add(line)

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Close month via API
        close_res = await ac.post(
            "/payroll/close-month",
            headers=headers,
            json={
                "organization_id": str(org_id),
                "ledger_month": "2026-03-01",
            },
        )
        assert close_res.status_code == 200
        assert close_res.json()["closed_count"] == 1

        # 2. Verify line is now closed in DB
        async with superuser_sessionmaker() as session:
            async with session.begin():
                stmt = select(PayrollLedgerLine).where(
                    PayrollLedgerLine.organization_id == org_id,
                    PayrollLedgerLine.ledger_month == date(2026, 3, 1),
                )
                res = await session.execute(stmt)
                db_line = res.scalar_one()
                assert db_line.status == "closed"
                assert db_line.closed_at is not None

                # 3. Attempt direct UPDATE via DB (should trigger DB trigger RaiseExceptionError)
                db_line.amount_cents = 350000
                with pytest.raises(DBAPIError) as exc_info:
                    await session.flush()
                
                assert "is closed and cannot be modified" in str(exc_info.value)


@pytest.mark.asyncio
async def test_payroll_temporal_rules_adjustment():
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    # Dates
    march_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    april_1 = datetime(2026, 4, 1, tzinfo=timezone.utc)
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Payroll Rules Corp")
            session.add(org)
            
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@pay.com",
                full_name="Payroll Admin",
                role="admin",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(admin)
            
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"emp_{uuid.uuid4()}@pay.com",
                full_name="Payroll Employee",
                role="developer",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(emp)

            # Rule 1: Valid March 1st to April 1st (Rule Value = 400,000 cents / $4,000)
            rule_march = PayrollRule(
                organization_id=org_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                rule_value={"amount_cents": 400000},
                valid_from=march_1,
                valid_to=april_1,
            )
            session.add(rule_march)

            # Rule 2: Valid April 1st onwards (Rule Value = 550,000 cents / $5,500)
            rule_april = PayrollRule(
                organization_id=org_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                rule_value={"amount_cents": 550000},
                valid_from=april_1,
                valid_to=None,
            )
            session.add(rule_april)

    # Re-fetch rule IDs and insert ledger line in same session
    async with superuser_sessionmaker() as session:
        async with session.begin():
            res_r = await session.execute(
                select(PayrollRule).where(
                    PayrollRule.organization_id == org_id,
                    PayrollRule.valid_from == march_1,
                )
            )
            rule_march_db = res_r.scalar_one()

            # Insert a March ledger line computed from the March rule.
            # But let's say the line was paid only 300,000 cents (underpaid by 100,000 relative to March's rule of 400,000).
            line = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 3, 1),
                line_type="base_salary",
                amount_cents=300000,
                currency="USD",
                status="open",
                computed_from_rule_id=rule_march_db.id,
            )
            session.add(line)

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Close March month first
        close_res = await ac.post(
            "/payroll/close-month",
            headers=headers,
            json={
                "organization_id": str(org_id),
                "ledger_month": "2026-03-01",
            },
        )
        assert close_res.status_code == 200

        # Retrieve original line details and calculate its checksum
        async with superuser_sessionmaker() as session:
            async with session.begin():
                orig_line_res = await session.execute(
                    select(PayrollLedgerLine).where(
                        PayrollLedgerLine.organization_id == org_id,
                        PayrollLedgerLine.ledger_month == date(2026, 3, 1),
                    )
                )
                orig_line_before = orig_line_res.scalar_one()
                checksum_before = compute_row_checksum(orig_line_before)
                original_line_id = orig_line_before.id

        # 2. Fire adjustment API call (today is in July 2026, where the current rule is Rule 2: 550,000)
        # But since we adjust the March line, it must resolve the rule valid in March (Rule 1: 400,000)
        # Expected adjustment: 400,000 (March rule) - 300,000 (actual paid) = 100,000 delta.
        # It must NOT use April's rule (550,000 - 300,000 = 250,000).
        adj_res = await ac.post(
            "/payroll/adjustments",
            headers=headers,
            json={
                "original_line_id": str(original_line_id),
                "reason": "Underpayment in March base salary",
            },
        )
        assert adj_res.status_code == 201
        adj_data = adj_res.json()

        # Verify adjustment delta is exactly 100,000 cents (from the March rule)
        assert adj_data["amount_cents"] == 100000
        assert adj_data["line_type"] == "adjustment"
        assert adj_data["adjustment_of"] == str(original_line_id)

        # 3. Retrieve original line and assert its checksum has NOT changed (4d byte-for-byte equality)
        async with superuser_sessionmaker() as session:
            async with session.begin():
                orig_line_res_after = await session.execute(
                    select(PayrollLedgerLine).where(PayrollLedgerLine.id == original_line_id)
                )
                orig_line_after = orig_line_res_after.scalar_one()
                checksum_after = compute_row_checksum(orig_line_after)

                assert checksum_before == checksum_after
