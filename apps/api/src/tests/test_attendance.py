import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.db.base import superuser_sessionmaker
from src.db.models.organization import Organization
from src.db.models.employee import Employee
from src.db.models.clock_event import ClockEvent
from src.modules.auth.helpers import hash_password, create_access_token


@pytest.mark.asyncio
async def test_employee_timezone_validation():
    # Setup organization and employee
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="TZ Corp")
            session.add(org)
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"tz_emp_{uuid.uuid4()}@tz.com",
                full_name="TZ Tester",
                role="developer",
                status="active",
                password_hash=hash_password("password"),
            )
            session.add(emp)

    token, _, _ = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        # A. Attempt to set invalid timezone (should fail with 422)
        invalid_res = await ac.patch(
            "/employees/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"timezone": "Invalid/TimeZone_Here"},
        )
        assert invalid_res.status_code == 422
        # Verify the error structure includes timezone validation error
        assert "timezone" in str(invalid_res.json()["detail"])

        # B. Set valid IANA timezone (should succeed)
        valid_res = await ac.patch(
            "/employees/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"timezone": "Asia/Kolkata"},
        )
        assert valid_res.status_code == 200
        assert valid_res.json()["timezone"] == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_clock_in_clock_out_alternation():
    # Setup org and employee
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Clock Corp")
            session.add(org)
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"clock_{uuid.uuid4()}@clock.com",
                full_name="Clock Tester",
                role="developer",
                status="active",
                timezone="UTC",
                password_hash=hash_password("password"),
            )
            session.add(emp)

    token, _, _ = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # 1. First Clock-in (success)
        res1 = await ac.post("/attendance/clock-in", headers=headers, json={})
        assert res1.status_code == 201
        assert res1.json()["event_type"] == "clock_in"

        # 2. Clock-in again (failure)
        res2 = await ac.post("/attendance/clock-in", headers=headers, json={})
        assert res2.status_code == 400
        assert "already clocked in" in res2.json()["detail"].lower()

        # 3. Clock-out (success)
        res3 = await ac.post("/attendance/clock-out", headers=headers, json={})
        assert res3.status_code == 201
        assert res3.json()["event_type"] == "clock_out"

        # 4. Clock-out again (failure)
        res4 = await ac.post("/attendance/clock-out", headers=headers, json={})
        assert res4.status_code == 400
        assert "not clocked in" in res4.json()["detail"].lower()


@pytest.mark.asyncio
async def test_client_clock_skew_ignored():
    # Setup
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Skew Corp")
            session.add(org)
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=f"skew_{uuid.uuid4()}@skew.com",
                full_name="Skew Tester",
                role="developer",
                status="active",
                timezone="UTC",
                password_hash=hash_password("password"),
            )
            session.add(emp)

    token, _, _ = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        headers = {"Authorization": f"Bearer {token}"}

        # Submit a client_reported_at that is wildly in the future (e.g. 5 hours)
        skewed_time = datetime.now(timezone.utc) + timedelta(hours=5)
        res = await ac.post(
            "/attendance/clock-in",
            headers=headers,
            json={"client_reported_at": skewed_time.isoformat()},
        )
        assert res.status_code == 201
        data = res.json()

        recorded_at = datetime.fromisoformat(data["recorded_at"])
        client_reported_at = datetime.fromisoformat(data["client_reported_at"])

        # Check recorded_at is close to the current server time (within 5 seconds)
        assert abs((datetime.now(timezone.utc) - recorded_at).total_seconds()) < 5.0
        # Check client_reported_at is indeed the skewed time we submitted
        assert abs((skewed_time - client_reported_at).total_seconds()) < 1.0


@pytest.mark.asyncio
async def test_timezone_conversion_history():
    # Setup organization and two employees with different timezones
    org_id = uuid.uuid4()
    emp1_id = uuid.uuid4()
    emp2_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="History Corp")
            session.add(org)
            
            # Employee 1: America/New_York (UTC-5 or UTC-4 depending on DST)
            emp1 = Employee(
                id=emp1_id,
                organization_id=org_id,
                email=f"ny_{uuid.uuid4()}@history.com",
                full_name="NY User",
                role="developer",
                status="active",
                timezone="America/New_York",
                password_hash=hash_password("password"),
            )
            session.add(emp1)

            # Employee 2: Asia/Kolkata (UTC+5:30)
            emp2 = Employee(
                id=emp2_id,
                organization_id=org_id,
                email=f"kolkata_{uuid.uuid4()}@history.com",
                full_name="Kolkata User",
                role="developer",
                status="active",
                timezone="Asia/Kolkata",
                password_hash=hash_password("password"),
            )
            session.add(emp2)

    token1, _, _ = create_access_token(emp1_id, org_id, "developer")
    token2, _, _ = create_access_token(emp2_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        # Clock in Employee 1
        res1 = await ac.post("/attendance/clock-in", headers={"Authorization": f"Bearer {token1}"}, json={})
        assert res1.status_code == 201

        # Clock in Employee 2
        res2 = await ac.post("/attendance/clock-in", headers={"Authorization": f"Bearer {token2}"}, json={})
        assert res2.status_code == 201

        # A. Fetch history for Employee 1 (America/New_York)
        hist1_res = await ac.get("/attendance/history", headers={"Authorization": f"Bearer {token1}"})
        assert hist1_res.status_code == 200
        events1 = hist1_res.json()["events"]
        assert len(events1) >= 1
        event1 = events1[-1]
        
        utc_time1 = datetime.fromisoformat(event1["recorded_at_utc"])
        local_time1 = datetime.fromisoformat(event1["recorded_at_local"])
        expected_local1 = utc_time1.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
        assert abs((expected_local1 - local_time1).total_seconds()) < 1.0

        # B. Fetch history for Employee 2 (Asia/Kolkata - with half hour offset)
        hist2_res = await ac.get("/attendance/history", headers={"Authorization": f"Bearer {token2}"})
        assert hist2_res.status_code == 200
        events2 = hist2_res.json()["events"]
        assert len(events2) >= 1
        event2 = events2[-1]

        utc_time2 = datetime.fromisoformat(event2["recorded_at_utc"])
        local_time2 = datetime.fromisoformat(event2["recorded_at_local"])
        expected_local2 = utc_time2.astimezone(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
        assert abs((expected_local2 - local_time2).total_seconds()) < 1.0
