"""
This test suite verifies PostgreSQL Row-Level Security (RLS) and Tenant Isolation
for all tables in the database schema carrying an `organization_id` column.

Enumerated tables carrying `organization_id` (inspected from ORM models):
1. employees (model: Employee)
2. invitations (model: Invitation)
3. clock_events (model: ClockEvent)
4. leave_requests (model: LeaveRequest)
5. payroll_rules (model: PayrollRule)
6. payroll_ledger_lines (model: PayrollLedgerLine)
7. pseudonymization_map (model: PseudonymizationMap)
8. automation_jobs (model: AutomationJob)
"""

import hashlib
import uuid
import pytest
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import select, update, text
from sqlalchemy.exc import DBAPIError

from src.db.base import async_sessionmaker_factory, superuser_sessionmaker
from src.db.models import (
    Organization,
    Employee,
    Invitation,
    ClockEvent,
    LeaveRequest,
    PayrollRule,
    PayrollLedgerLine,
    PseudonymizationMap,
    AutomationJob,
)

pytestmark = pytest.mark.rls


TABLE_PARAMETERS = [
    # (model_class, get_row_data, update_data, param_id)
    (
        Employee,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "email": f"test_{uuid.uuid4()}@test.com",
            "full_name": "Test Emp",
            "role": "developer",
            "timezone": "UTC",
            "status": "active",
        },
        {"full_name": "Updated Name"},
        "employees"
    ),
    (
        Invitation,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "email": f"inv_{uuid.uuid4()}@test.com",
            "token_hash": hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),
            "role": "developer",
            "invited_by": emp_id,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        },
        {"role": "admin"},
        "invitations"
    ),
    (
        ClockEvent,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "employee_id": emp_id,
            "event_type": "clock_in",
            "recorded_at": datetime.now(timezone.utc),
        },
        {"event_type": "clock_out"},
        "clock_events"
    ),
    (
        LeaveRequest,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "employee_id": emp_id,
            "start_time": datetime.now(timezone.utc),
            "end_time": datetime.now(timezone.utc) + timedelta(hours=8),
            "status": "pending",
        },
        {"status": "approved"},
        "leave_requests"
    ),
    (
        PayrollRule,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "rule_type": "salary",
            "rule_key": f"key_{uuid.uuid4()}",
            "rule_value": {"amount_cents": 1000},
            "valid_from": datetime.now(timezone.utc),
        },
        {"rule_value": {"amount_cents": 2000}},
        "payroll_rules"
    ),
    (
        PayrollLedgerLine,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "employee_id": emp_id,
            "ledger_month": date.today(),
            "line_type": "base_salary",
            "amount_cents": 200000,
            "currency": "USD",
            "status": "open",
        },
        {"amount_cents": 300000},
        "payroll_ledger_lines"
    ),
    (
        PseudonymizationMap,
        lambda org_id, emp_id: {
            "original_employee_id": emp_id,
            "organization_id": org_id,
            "pseudonym_hash": hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),
            "structural_cohort": "cohort_1",
            "requested_by": "admin",
        },
        {"structural_cohort": "cohort_2"},
        "pseudonymization_map"
    ),
    (
        AutomationJob,
        lambda org_id, emp_id: {
            "organization_id": org_id,
            "target_url": "http://example.com",
            "extraction_type": "title",
            "status": "queued",
        },
        {"status": "completed"},
        "automation_jobs"
    ),
]


async def setup_rls_data():
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    emp_a_id = uuid.uuid4()
    emp_b_id = uuid.uuid4()

    async with superuser_sessionmaker() as session:
        async with session.begin():
            # Create orgs
            org_a = Organization(id=org_a_id, name=f"Adversarial Org A {uuid.uuid4()}")
            org_b = Organization(id=org_b_id, name=f"Adversarial Org B {uuid.uuid4()}")
            session.add_all([org_a, org_b])

            # Create employees
            emp_a = Employee(
                id=emp_a_id,
                organization_id=org_a_id,
                email=f"emp_a_{uuid.uuid4()}@orga.com",
                full_name="Emp A",
                role="developer",
                status="active",
            )
            emp_b = Employee(
                id=emp_b_id,
                organization_id=org_b_id,
                email=f"emp_b_{uuid.uuid4()}@orgb.com",
                full_name="Emp B",
                role="developer",
                status="active",
            )
            session.add_all([emp_a, emp_b])

    return {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "emp_a_id": emp_a_id,
        "emp_b_id": emp_b_id,
    }


# ==========================================
# 1. READ ISOLATION ADVERSARIAL TEST
# ==========================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class, get_row_data, update_data",
    [p[:3] for p in TABLE_PARAMETERS],
    ids=[p[3] for p in TABLE_PARAMETERS]
)
async def test_rls_read_isolation(model_class, get_row_data, update_data):
    rls_setup = await setup_rls_data()
    org_a_id = rls_setup["org_a_id"]
    org_b_id = rls_setup["org_b_id"]
    emp_a_id = rls_setup["emp_a_id"]

    # Insert row as Org A using superuser session to bypass RLS
    row_data = get_row_data(org_a_id, emp_a_id)
    async with superuser_sessionmaker() as session:
        async with session.begin():
            row = model_class(**row_data)
            session.add(row)
            await session.flush()
            row_pk = getattr(row, "id", None) or getattr(row, "original_employee_id", None)

    assert row_pk is not None

    # Open Org B session with its own current_organization_id
    async with async_sessionmaker_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": str(org_b_id)},
            )
            # Test general query
            stmt = select(model_class)
            res = await session.execute(stmt)
            all_rows = res.scalars().all()
            for r in all_rows:
                assert getattr(r, "organization_id") != org_a_id

            # Test direct point lookup by known primary key
            pk_field = getattr(model_class, "id", None) or getattr(model_class, "original_employee_id", None)
            stmt_pk = select(model_class).where(pk_field == row_pk)
            res_pk = await session.execute(stmt_pk)
            point_rows = res_pk.scalars().all()
            assert len(point_rows) == 0, f"Tenant B leaked Tenant A data for {model_class.__tablename__}"


# ==========================================
# 2. WRITE ISOLATION ADVERSARIAL TEST
# ==========================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class, get_row_data, update_data",
    [p[:3] for p in TABLE_PARAMETERS],
    ids=[p[3] for p in TABLE_PARAMETERS]
)
async def test_rls_write_isolation(model_class, get_row_data, update_data):
    rls_setup = await setup_rls_data()
    org_a_id = rls_setup["org_a_id"]
    org_b_id = rls_setup["org_b_id"]
    emp_a_id = rls_setup["emp_a_id"]

    row_data = get_row_data(org_a_id, emp_a_id)

    # Open Org B session and try to write Org A's organization_id explicitly
    async with async_sessionmaker_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": str(org_b_id)},
            )
            bad_row = model_class(**row_data)
            session.add(bad_row)

            # RLS policy should raise an InsufficientPrivilege / policy check exception
            with pytest.raises(DBAPIError) as exc_info:
                await session.flush()

            err_str = str(exc_info.value)
            assert "insufficient_privilege" in err_str or "violates row-level security policy" in err_str


# ==========================================
# 3. UPDATE ISOLATION ADVERSARIAL TEST
# ==========================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class, get_row_data, update_data",
    [p[:3] for p in TABLE_PARAMETERS],
    ids=[p[3] for p in TABLE_PARAMETERS]
)
async def test_rls_update_isolation(model_class, get_row_data, update_data):
    rls_setup = await setup_rls_data()
    org_a_id = rls_setup["org_a_id"]
    org_b_id = rls_setup["org_b_id"]
    emp_a_id = rls_setup["emp_a_id"]

    # Insert row as Org A
    row_data = get_row_data(org_a_id, emp_a_id)
    async with superuser_sessionmaker() as session:
        async with session.begin():
            row = model_class(**row_data)
            session.add(row)
            await session.flush()
            row_pk = getattr(row, "id", None) or getattr(row, "original_employee_id", None)

    # Attempt to update it inside Org B's session
    async with async_sessionmaker_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": str(org_b_id)},
            )
            pk_field = getattr(model_class, "id", None) or getattr(model_class, "original_employee_id", None)
            stmt = update(model_class).where(pk_field == row_pk).values(**update_data)
            res = await session.execute(stmt)
            # RLS makes the row invisible to Org B's session, so 0 rows are updated
            assert res.rowcount == 0


# ==========================================
# 4. FAIL-CLOSED NO-CONTEXT TEST
# ==========================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class, get_row_data, update_data",
    [p[:3] for p in TABLE_PARAMETERS],
    ids=[p[3] for p in TABLE_PARAMETERS]
)
async def test_rls_no_tenant_context_fail_closed(model_class, get_row_data, update_data):
    rls_setup = await setup_rls_data()
    org_a_id = rls_setup["org_a_id"]
    emp_a_id = rls_setup["emp_a_id"]

    row_data = get_row_data(org_a_id, emp_a_id)
    async with superuser_sessionmaker() as session:
        async with session.begin():
            row = model_class(**row_data)
            session.add(row)
            await session.flush()

    # Query with normal session without ever setting the current_organization_id context variable
    async with async_sessionmaker_factory() as session:
        async with session.begin():
            stmt = select(model_class)
            res = await session.execute(stmt)
            all_rows = res.scalars().all()
            assert len(all_rows) == 0, f"Un-contextualized session leaked rows for {model_class.__tablename__}"


# ==========================================
# 5. ORM-SHORTCUT / SUPERUSER BYPASS TEST
# ==========================================

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_class, get_row_data, update_data",
    [p[:3] for p in TABLE_PARAMETERS],
    ids=[p[3] for p in TABLE_PARAMETERS]
)
async def test_rls_superuser_bypass_permitted(model_class, get_row_data, update_data):
    rls_setup = await setup_rls_data()
    org_a_id = rls_setup["org_a_id"]
    emp_a_id = rls_setup["emp_a_id"]

    row_data = get_row_data(org_a_id, emp_a_id)
    async with superuser_sessionmaker() as session:
        async with session.begin():
            row = model_class(**row_data)
            session.add(row)
            await session.flush()
            row_pk = getattr(row, "id", None) or getattr(row, "original_employee_id", None)

    # Query using superuser_sessionmaker (bypasses RLS) without tenant context
    async with superuser_sessionmaker() as session:
        async with session.begin():
            pk_field = getattr(model_class, "id", None) or getattr(model_class, "original_employee_id", None)
            stmt = select(model_class).where(pk_field == row_pk)
            res = await session.execute(stmt)
            point_rows = res.scalars().all()
            assert len(point_rows) == 1, f"Superuser session could not bypass RLS for {model_class.__tablename__}"
