import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.db.base import superuser_sessionmaker
from src.db.models.organization import Organization
from src.db.models.employee import Employee
from src.db.models.leave_request import LeaveRequest
from src.modules.auth.helpers import hash_password, create_access_token


@pytest.mark.asyncio
async def test_leave_requests_sequential_and_overlapping():
    # Setup organization and admin + developer employees
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Leave Corp")
            session.add(org)
            
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@leave.com",
                full_name="Admin User",
                role="admin",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(admin)
            
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"emp_{uuid.uuid4()}@leave.com",
                full_name="Regular Employee",
                role="developer",
                status="active",
                password_hash=hash_password("emp_pass"),
            )
            session.add(emp)

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")
    emp_token, _, _ = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {emp_token}"}
        base_time = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)

        # 1. Request A (Mon - Wed) succeeds
        start_a = base_time + timedelta(days=1)
        end_a = base_time + timedelta(days=3)
        res_a = await ac.post(
            "/leave-requests",
            headers=headers,
            json={
                "start_time": start_a.isoformat(),
                "end_time": end_a.isoformat(),
            },
        )
        assert res_a.status_code == 201
        data_a = res_a.json()
        assert data_a["status"] == "pending"

        # 2. Request B (Tue - Thu) same employee, overlaps with A -> fails with 409
        start_b = base_time + timedelta(days=2)
        end_b = base_time + timedelta(days=4)
        res_b = await ac.post(
            "/leave-requests",
            headers=headers,
            json={
                "start_time": start_b.isoformat(),
                "end_time": end_b.isoformat(),
            },
        )
        assert res_b.status_code == 409
        assert "overlapping leave request already exists" in res_b.json()["detail"].lower()

        # 3. Request C (Thu - Fri) same employee, does not overlap -> succeeds
        start_c = base_time + timedelta(days=3, hours=1) # start after request A ends
        end_c = base_time + timedelta(days=5)
        res_c = await ac.post(
            "/leave-requests",
            headers=headers,
            json={
                "start_time": start_c.isoformat(),
                "end_time": end_c.isoformat(),
            },
        )
        assert res_c.status_code == 201


@pytest.mark.asyncio
async def test_leave_requests_different_employees_same_dates():
    # Setup organization and two developers
    org_id = uuid.uuid4()
    emp1_id = uuid.uuid4()
    emp2_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Multi-Leave Corp")
            session.add(org)
            
            emp1 = Employee(
                id=emp1_id,
                organization_id=org_id,
                email=f"emp1_{uuid.uuid4()}@leave.com",
                full_name="Employee One",
                role="developer",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(emp1)
            
            emp2 = Employee(
                id=emp2_id,
                organization_id=org_id,
                email=f"emp2_{uuid.uuid4()}@leave.com",
                full_name="Employee Two",
                role="developer",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(emp2)

    emp1_token, _, _ = create_access_token(emp1_id, org_id, "developer")
    emp2_token, _, _ = create_access_token(emp2_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        base_time = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        start_time = base_time + timedelta(days=1)
        end_time = base_time + timedelta(days=3)

        # Employee 1 requests leave (succeeds)
        res1 = await ac.post(
            "/leave-requests",
            headers={"Authorization": f"Bearer {emp1_token}"},
            json={
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        assert res1.status_code == 201

        # Employee 2 requests same leave (succeeds, since scoped by employee_id)
        res2 = await ac.post(
            "/leave-requests",
            headers={"Authorization": f"Bearer {emp2_token}"},
            json={
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        assert res2.status_code == 201


@pytest.mark.asyncio
async def test_rejected_leaves_do_not_block():
    # Setup organization, admin, employee
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Rejection Corp")
            session.add(org)
            
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@leave.com",
                full_name="Admin",
                role="admin",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(admin)
            
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"emp_{uuid.uuid4()}@leave.com",
                full_name="Regular Employee",
                role="developer",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(emp)

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")
    emp_token, _, _ = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        base_time = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        start_time = base_time + timedelta(days=1)
        end_time = base_time + timedelta(days=3)

        # 1. Request A (succeeds, starts as pending)
        res_a = await ac.post(
            "/leave-requests",
            headers={"Authorization": f"Bearer {emp_token}"},
            json={
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        assert res_a.status_code == 201
        req_id = res_a.json()["id"]

        # 2. Request B (Tue-Thu) same employee, overlaps with A -> fails with 409
        res_b1 = await ac.post(
            "/leave-requests",
            headers={"Authorization": f"Bearer {emp_token}"},
            json={
                "start_time": (base_time + timedelta(days=2)).isoformat(),
                "end_time": (base_time + timedelta(days=4)).isoformat(),
            },
        )
        assert res_b1.status_code == 409

        # 3. Reject Request A (Admin action)
        res_reject = await ac.patch(
            f"/leave-requests/{req_id}/reject",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res_reject.status_code == 200
        assert res_reject.json()["status"] == "rejected"

        # 4. Request B now succeeds (rejected request no longer blocks overlapping range)
        res_b2 = await ac.post(
            "/leave-requests",
            headers={"Authorization": f"Bearer {emp_token}"},
            json={
                "start_time": (base_time + timedelta(days=2)).isoformat(),
                "end_time": (base_time + timedelta(days=4)).isoformat(),
            },
        )
        assert res_b2.status_code == 201


@pytest.mark.asyncio
async def test_concurrent_leave_requests_safety():
    # Setup organization and employee
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Concurrent Corp")
            session.add(org)
            
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"emp_{uuid.uuid4()}@leave.com",
                full_name="Concurrent Employee",
                role="developer",
                status="active",
                password_hash=hash_password("pass"),
            )
            session.add(emp)

    emp_token, _, _ = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac1, \
               AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac2:
        base_time = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        payload = {
            "start_time": (base_time + timedelta(days=1)).isoformat(),
            "end_time": (base_time + timedelta(days=3)).isoformat(),
        }

        # Fire two overlapping insert requests concurrently
        tasks = [
            ac1.post("/leave-requests", headers={"Authorization": f"Bearer {emp_token}"}, json=payload),
            ac2.post("/leave-requests", headers={"Authorization": f"Bearer {emp_token}"}, json=payload),
        ]
        results = await asyncio.gather(*tasks)

        # Assert exactly one succeeded (201 Created) and one failed (409 Conflict)
        status_codes = [r.status_code for r in results]
        assert 201 in status_codes
        assert 409 in status_codes

        # Verify details of the conflict
        failed_res = [r for r in results if r.status_code == 409][0]
        assert "overlapping leave request already exists" in failed_res.json()["detail"].lower()
