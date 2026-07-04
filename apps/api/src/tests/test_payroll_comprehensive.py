import hashlib
import json
import uuid
from datetime import date, datetime, timezone, timedelta
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete
from sqlalchemy.exc import DBAPIError

from src.main import app
from src.db.base import superuser_sessionmaker
from src.db.models.organization import Organization
from src.db.models.employee import Employee
from src.db.models.payroll_rule import PayrollRule
from src.db.models.payroll_ledger_line import PayrollLedgerLine
from src.modules.auth.helpers import hash_password, create_access_token
from src.modules.payroll.service import PayrollRuleResolver


def compute_row_checksum(row) -> str:
    """Computes a SHA256 checksum of the database row's non-dynamic columns."""
    data = {
        c.name: str(getattr(row, c.name))
        for c in row.__table__.columns
    }
    serialized = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


async def get_payroll_setup():
    """Sets up Org A and Org B, with admins, employees, rules, and ledger lines."""
    # Organization A
    org_a_id = uuid.uuid4()
    admin_a_id = uuid.uuid4()
    emp_a_id = uuid.uuid4()

    # Organization B (for cross-tenant checks)
    org_b_id = uuid.uuid4()
    admin_b_id = uuid.uuid4()
    emp_b_id = uuid.uuid4()

    # Dates
    march_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    april_1 = datetime(2026, 4, 1, tzinfo=timezone.utc)

    async with superuser_sessionmaker() as session:
        async with session.begin():
            # Add Org A
            org_a = Organization(id=org_a_id, name=f"Organization A {uuid.uuid4()}")
            session.add(org_a)
            admin_a = Employee(
                id=admin_a_id,
                organization_id=org_a_id,
                email=f"admin_a_{uuid.uuid4()}@test.com",
                full_name="Admin A",
                role="admin",
                status="active",
                password_hash=hash_password("password"),
            )
            session.add(admin_a)
            emp_a = Employee(
                id=emp_a_id,
                organization_id=org_a_id,
                email=f"emp_a_{uuid.uuid4()}@test.com",
                full_name="Employee A",
                role="developer",
                status="active",
                password_hash=hash_password("password"),
            )
            session.add(emp_a)

            # Add Org B
            org_b = Organization(id=org_b_id, name=f"Organization B {uuid.uuid4()}")
            session.add(org_b)
            admin_b = Employee(
                id=admin_b_id,
                organization_id=org_b_id,
                email=f"admin_b_{uuid.uuid4()}@test.com",
                full_name="Admin B",
                role="admin",
                status="active",
                password_hash=hash_password("password"),
            )
            session.add(admin_b)
            emp_b = Employee(
                id=emp_b_id,
                organization_id=org_b_id,
                email=f"emp_b_{uuid.uuid4()}@test.com",
                full_name="Employee B",
                role="developer",
                status="active",
                password_hash=hash_password("password"),
            )
            session.add(emp_b)

            # Org A Rules
            rule_a_march = PayrollRule(
                organization_id=org_a_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                rule_value={"amount_cents": 400000},
                valid_from=march_1,
                valid_to=april_1,
            )
            session.add(rule_a_march)

            rule_a_april = PayrollRule(
                organization_id=org_a_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                rule_value={"amount_cents": 550000},
                valid_from=april_1,
                valid_to=None,
            )
            session.add(rule_a_april)

            # Org B Rules (different values)
            rule_b_march = PayrollRule(
                organization_id=org_b_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                rule_value={"amount_cents": 300000},
                valid_from=march_1,
                valid_to=None,
            )
            session.add(rule_b_march)

    # Fetch rule IDs in a separate session
    async with superuser_sessionmaker() as session:
        async with session.begin():
            rule_a_db = (await session.execute(
                select(PayrollRule).where(
                    PayrollRule.organization_id == org_a_id,
                    PayrollRule.valid_from == march_1,
                )
            )).scalar_one()
            rule_a_id = rule_a_db.id

            # Create ledger lines for Org A
            line_a_open = PayrollLedgerLine(
                organization_id=org_a_id,
                employee_id=emp_a_id,
                ledger_month=date(2026, 3, 1),
                line_type="base_salary",
                amount_cents=300000, # Underpaid by 100000
                currency="USD",
                status="open",
                computed_from_rule_id=rule_a_id,
            )
            session.add(line_a_open)

            # Create ledger lines for Org B
            line_b_open = PayrollLedgerLine(
                organization_id=org_b_id,
                employee_id=emp_b_id,
                ledger_month=date(2026, 3, 1),
                line_type="base_salary",
                amount_cents=300000,
                currency="USD",
                status="open",
            )
            session.add(line_b_open)

    # Generate JWT Tokens
    token_admin_a, _, _ = create_access_token(admin_a_id, org_a_id, "admin")
    token_emp_a, _, _ = create_access_token(emp_a_id, org_a_id, "developer")
    token_admin_b, _, _ = create_access_token(admin_b_id, org_b_id, "admin")

    return {
        "org_a_id": org_a_id,
        "admin_a_id": admin_a_id,
        "emp_a_id": emp_a_id,
        "org_b_id": org_b_id,
        "admin_b_id": admin_b_id,
        "emp_b_id": emp_b_id,
        "token_admin_a": token_admin_a,
        "token_emp_a": token_emp_a,
        "token_admin_b": token_admin_b,
        "rule_a_id": rule_a_id,
        "march_1": march_1,
        "april_1": april_1,
    }


# ==========================================
# 1. HAPPY PATH TESTS
# ==========================================

@pytest.mark.asyncio
async def test_get_payroll_lines_happy_path():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.get(
            f"/payroll/lines?employee_id={setup['emp_a_id']}&month=2026-03",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["amount_cents"] == 300000
        assert data[0]["status"] == "open"


@pytest.mark.asyncio
async def test_close_month_happy_path():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/close-month",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "organization_id": str(setup["org_a_id"]),
                "ledger_month": "2026-03-01",
            },
        )
        assert res.status_code == 200
        assert res.json()["closed_count"] == 1


@pytest.mark.asyncio
async def test_create_adjustment_happy_path():
    setup = await get_payroll_setup()
    # 1. Close the month first so we can adjust it
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {setup['token_admin_a']}"}
        close_res = await ac.post(
            "/payroll/close-month",
            headers=headers,
            json={
                "organization_id": str(setup["org_a_id"]),
                "ledger_month": "2026-03-01",
            },
        )
        assert close_res.status_code == 200

        # Retrieve closed line ID
        async with superuser_sessionmaker() as session:
            async with session.begin():
                stmt = select(PayrollLedgerLine).where(
                    PayrollLedgerLine.organization_id == setup["org_a_id"],
                    PayrollLedgerLine.ledger_month == date(2026, 3, 1),
                )
                line = (await session.execute(stmt)).scalar_one()
                line_id = line.id

        # 2. Adjust it
        adj_res = await ac.post(
            "/payroll/adjustments",
            headers=headers,
            json={
                "original_line_id": str(line_id),
                "reason": "Salary adjustment",
            },
        )
        assert adj_res.status_code == 201
        data = adj_res.json()
        assert data["amount_cents"] == 100000  # 400000 (rule) - 300000 (paid)
        assert data["line_type"] == "adjustment"
        assert data["adjustment_of"] == str(line_id)


@pytest.mark.asyncio
async def test_rule_resolver_happy_path():
    setup = await get_payroll_setup()
    async with superuser_sessionmaker() as session:
        async with session.begin():
            # Resolve during march
            rule = await PayrollRuleResolver.resolve(
                db=session,
                organization_id=setup["org_a_id"],
                rule_type="salary_bracket",
                rule_key="tier_1",
                as_of=setup["march_1"] + timedelta(days=15),
            )
            assert rule is not None
            assert rule.rule_value["amount_cents"] == 400000


# ==========================================
# 2. EXPLICIT VALIDATION ERRORS
# ==========================================

@pytest.mark.asyncio
async def test_get_lines_rejects_unauthenticated_request():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.get(
            f"/payroll/lines?employee_id={setup['emp_a_id']}&month=2026-03"
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_lines_rejects_non_admin_role():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.get(
            f"/payroll/lines?employee_id={setup['emp_a_id']}&month=2026-03",
            headers={"Authorization": f"Bearer {setup['token_emp_a']}"},
        )
        assert res.status_code == 403
        assert "Only admins can view payroll records" in res.json()["detail"]


@pytest.mark.asyncio
async def test_get_lines_rejects_invalid_month_format():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.get(
            f"/payroll/lines?employee_id={setup['emp_a_id']}&month=2026/03",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
        )
        assert res.status_code == 400
        assert "Invalid month format" in res.json()["detail"]


@pytest.mark.asyncio
async def test_close_month_rejects_unauthenticated_request():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/close-month",
            json={
                "organization_id": str(setup["org_a_id"]),
                "ledger_month": "2026-03-01",
            },
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_close_month_rejects_non_admin_role():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/close-month",
            headers={"Authorization": f"Bearer {setup['token_emp_a']}"},
            json={
                "organization_id": str(setup["org_a_id"]),
                "ledger_month": "2026-03-01",
            },
        )
        assert res.status_code == 403
        assert "Only admins can close payroll months" in res.json()["detail"]


@pytest.mark.asyncio
async def test_close_month_rejects_org_id_mismatch():
    setup = await get_payroll_setup()
    # Admin A attempts to close Org B's month
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/close-month",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "organization_id": str(setup["org_b_id"]),
                "ledger_month": "2026-03-01",
            },
        )
        assert res.status_code == 403
        assert "Organization mismatch" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_adjustment_rejects_unauthenticated_request():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            json={
                "original_line_id": str(uuid.uuid4()),
                "reason": "Test",
            },
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_adjustment_rejects_non_admin_role():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_emp_a']}"},
            json={
                "original_line_id": str(uuid.uuid4()),
                "reason": "Test",
            },
        )
        assert res.status_code == 403
        assert "Only admins can submit adjustments" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_adjustment_rejects_non_existent_original_line():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "original_line_id": str(uuid.uuid4()),
                "reason": "Test",
            },
        )
        assert res.status_code == 404
        assert "Original payroll line not found" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_adjustment_rejects_open_original_line():
    setup = await get_payroll_setup()
    # Retrieve open line ID
    async with superuser_sessionmaker() as session:
        async with session.begin():
            stmt = select(PayrollLedgerLine).where(
                PayrollLedgerLine.organization_id == setup["org_a_id"],
                PayrollLedgerLine.status == "open",
            )
            line = (await session.execute(stmt)).scalars().first()
            line_id = line.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "original_line_id": str(line_id),
                "reason": "Test",
            },
        )
        assert res.status_code == 400
        assert "Adjustments are only allowed against closed payroll lines" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_adjustment_rejects_line_without_computed_rule():
    setup = await get_payroll_setup()
    # Create a line without computed_from_rule_id, close it, and adjust it.
    org_id = setup["org_a_id"]
    emp_id = setup["emp_a_id"]

    async with superuser_sessionmaker() as session:
        async with session.begin():
            line_no_rule = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 4, 1),
                line_type="bonus",
                amount_cents=50000,
                currency="USD",
                status="closed",  # Directly insert as closed for simplicity
            )
            session.add(line_no_rule)

    async with superuser_sessionmaker() as session:
        async with session.begin():
            stmt = select(PayrollLedgerLine).where(
                PayrollLedgerLine.organization_id == org_id,
                PayrollLedgerLine.ledger_month == date(2026, 4, 1),
                PayrollLedgerLine.line_type == "bonus",
            )
            line = (await session.execute(stmt)).scalar_one()
            line_id = line.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "original_line_id": str(line_id),
                "reason": "Test",
            },
        )
        assert res.status_code == 400
        assert "Original line was not computed from a payroll rule" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_adjustment_rejects_no_matching_historic_rule_found():
    setup = await get_payroll_setup()
    org_id = setup["org_a_id"]
    emp_id = setup["emp_a_id"]
    rule_id = setup["rule_a_id"]

    async with superuser_sessionmaker() as session:
        async with session.begin():
            # Month is 2025-01-01, but the rule is only valid from 2026-03-01.
            line_old = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2025, 1, 1),
                line_type="base_salary",
                amount_cents=300000,
                currency="USD",
                status="closed",
                computed_from_rule_id=rule_id,
            )
            session.add(line_old)

    async with superuser_sessionmaker() as session:
        async with session.begin():
            stmt = select(PayrollLedgerLine).where(
                PayrollLedgerLine.organization_id == org_id,
                PayrollLedgerLine.ledger_month == date(2025, 1, 1),
            )
            line = (await session.execute(stmt)).scalar_one()
            line_id = line.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "original_line_id": str(line_id),
                "reason": "Test",
            },
        )
        assert res.status_code == 400
        assert "No matching rule was valid during the target month" in res.json()["detail"]


@pytest.mark.asyncio
async def test_create_adjustment_rejects_rule_missing_amount_cents_value():
    setup = await get_payroll_setup()
    org_id = setup["org_a_id"]
    emp_id = setup["emp_a_id"]

    async with superuser_sessionmaker() as session:
        async with session.begin():
            bad_rule = PayrollRule(
                organization_id=org_id,
                rule_type="allowance",
                rule_key="phone",
                rule_value={"phone_model": "iPhone"}, # missing amount_cents
                valid_from=setup["march_1"],
                valid_to=None,
            )
            session.add(bad_rule)

    async with superuser_sessionmaker() as session:
        async with session.begin():
            bad_rule_db = (await session.execute(
                select(PayrollRule).where(
                    PayrollRule.organization_id == org_id,
                    PayrollRule.rule_type == "allowance",
                )
            )).scalar_one()

            line_bad = PayrollLedgerLine(
                organization_id=org_id,
                employee_id=emp_id,
                ledger_month=date(2026, 3, 1),
                line_type="allowance",
                amount_cents=10000,
                currency="USD",
                status="closed",
                computed_from_rule_id=bad_rule_db.id,
            )
            session.add(line_bad)
            await session.flush()
            line_id = line_bad.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_admin_a']}"},
            json={
                "original_line_id": str(line_id),
                "reason": "Test",
            },
        )
        assert res.status_code == 400
        assert "Resolved rule does not contain amount_cents value" in res.json()["detail"]


# ==========================================
# 3. ADVERSARIAL CASES (PRIME DIRECTIVES)
# ==========================================

# Prime Directive #1 (Tenant Isolation)
@pytest.mark.asyncio
async def test_cross_tenant_read_isolation_on_payroll_lines():
    setup = await get_payroll_setup()
    # Admin B (Org B) requests Org A's employee records
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.get(
            f"/payroll/lines?employee_id={setup['emp_a_id']}&month=2026-03",
            headers={"Authorization": f"Bearer {setup['token_admin_b']}"},
        )
        assert res.status_code == 200
        assert len(res.json()) == 0


# Prime Directive #1 (Tenant Isolation)
@pytest.mark.asyncio
async def test_cross_tenant_write_isolation_on_close_month():
    setup = await get_payroll_setup()
    # Admin B (Org B) tries to close Org A's month
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/close-month",
            headers={"Authorization": f"Bearer {setup['token_admin_b']}"},
            json={
                "organization_id": str(setup["org_a_id"]),
                "ledger_month": "2026-03-01",
            },
        )
        assert res.status_code == 403
        assert "Organization mismatch" in res.json()["detail"]


# Prime Directive #1 (Tenant Isolation)
@pytest.mark.asyncio
async def test_cross_tenant_write_isolation_on_adjustments():
    setup = await get_payroll_setup()
    # 1. Close Org A's line
    async with superuser_sessionmaker() as session:
        async with session.begin():
            stmt = select(PayrollLedgerLine).where(
                PayrollLedgerLine.organization_id == setup["org_a_id"],
                PayrollLedgerLine.status == "open",
            )
            line = (await session.execute(stmt)).scalars().first()
            line.status = "closed"

    # 2. Admin B (Org B) tries to adjust Org A's closed line
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/payroll/adjustments",
            headers={"Authorization": f"Bearer {setup['token_admin_b']}"},
            json={
                "original_line_id": str(line.id),
                "reason": "Test",
            },
        )
        assert res.status_code == 404
        assert "Original payroll line not found" in res.json()["detail"]


# Prime Directive #4 (Payroll Immutability)
@pytest.mark.asyncio
async def test_db_trigger_prevents_updates_to_closed_ledger_lines():
    setup = await get_payroll_setup()
    async with superuser_sessionmaker() as session:
        async with session.begin():
            line = PayrollLedgerLine(
                organization_id=setup["org_a_id"],
                employee_id=setup["emp_a_id"],
                ledger_month=date(2026, 5, 1),
                line_type="bonus",
                amount_cents=10000,
                currency="USD",
                status="closed",
            )
            session.add(line)
            await session.flush()
            line_id = line.id

    async with superuser_sessionmaker() as session:
        async with session.begin():
            stmt = select(PayrollLedgerLine).where(PayrollLedgerLine.id == line_id)
            db_line = (await session.execute(stmt)).scalar_one()
            db_line.amount_cents = 20000

            with pytest.raises(DBAPIError) as exc_info:
                await session.flush()
            assert "is closed and cannot be modified" in str(exc_info.value)


# Prime Directive #4 (Payroll Immutability)
@pytest.mark.asyncio
async def test_db_trigger_prevents_deletes_to_closed_ledger_lines():
    setup = await get_payroll_setup()
    async with superuser_sessionmaker() as session:
        async with session.begin():
            line = PayrollLedgerLine(
                organization_id=setup["org_a_id"],
                employee_id=setup["emp_a_id"],
                ledger_month=date(2026, 5, 1),
                line_type="bonus",
                amount_cents=10000,
                currency="USD",
                status="closed",
            )
            session.add(line)
            await session.flush()
            line_id = line.id

    async with superuser_sessionmaker() as session:
        async with session.begin():
            stmt = delete(PayrollLedgerLine).where(PayrollLedgerLine.id == line_id)
            with pytest.raises(DBAPIError) as exc_info:
                await session.execute(stmt)
            assert "is closed and cannot be modified" in str(exc_info.value)


# ==========================================
# 4. BOUNDARY CONDITIONS
# ==========================================

@pytest.mark.asyncio
async def test_rule_resolver_boundary_conditions():
    setup = await get_payroll_setup()
    org_id = setup["org_a_id"]
    march_1 = setup["march_1"]
    april_1 = setup["april_1"]

    async with superuser_sessionmaker() as session:
        async with session.begin():
            # 1. Exactly on valid_from (inclusive)
            rule_on_from = await PayrollRuleResolver.resolve(
                db=session,
                organization_id=org_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                as_of=march_1,
            )
            assert rule_on_from is not None
            assert rule_on_from.rule_value["amount_cents"] == 400000

            # 2. Right before valid_from (should be None)
            rule_before_from = await PayrollRuleResolver.resolve(
                db=session,
                organization_id=org_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                as_of=march_1 - timedelta(seconds=1),
            )
            assert rule_before_from is None

            # 3. Exactly on valid_to (exclusive, since next rule starts there)
            rule_on_to = await PayrollRuleResolver.resolve(
                db=session,
                organization_id=org_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                as_of=april_1,
            )
            assert rule_on_to is not None
            assert rule_on_to.rule_value["amount_cents"] == 550000

            # 4. Right before valid_to (should be march rule: 400,000)
            rule_before_to = await PayrollRuleResolver.resolve(
                db=session,
                organization_id=org_id,
                rule_type="salary_bracket",
                rule_key="tier_1",
                as_of=april_1 - timedelta(seconds=1),
            )
            assert rule_before_to is not None
            assert rule_before_to.rule_value["amount_cents"] == 400000


# ==========================================
# 5. IDEMPOTENCY
# ==========================================

@pytest.mark.asyncio
async def test_close_month_is_idempotent():
    setup = await get_payroll_setup()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {setup['token_admin_a']}"}
        payload = {
            "organization_id": str(setup["org_a_id"]),
            "ledger_month": "2026-03-01",
        }

        # First call closes 1 open line
        res1 = await ac.post("/payroll/close-month", headers=headers, json=payload)
        assert res1.status_code == 200
        assert res1.json()["closed_count"] == 1

        # Second call is a no-op (closes 0 lines)
        res2 = await ac.post("/payroll/close-month", headers=headers, json=payload)
        assert res2.status_code == 200
        assert res2.json()["closed_count"] == 0
