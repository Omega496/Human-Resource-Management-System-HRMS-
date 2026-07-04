import asyncio
import time
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from src.main import app
from src.db.base import async_sessionmaker_factory, superuser_sessionmaker
from src.db.models.employee import Employee
from src.db.models.organization import Organization
from src.db.models.refresh_token import RefreshToken
from src.modules.auth.helpers import hash_password, create_access_token, hash_token
from src.core.revocation import revocation_cache, RevocationCache


@pytest_asyncio.fixture(autouse=True)
async def setup_revocation():
    # Make sure revocation cache listener is active
    await revocation_cache.hydrate()
    await revocation_cache.start_listener()
    yield
    await revocation_cache.stop_listener()
    revocation_cache.clear_local()


@pytest.mark.asyncio
async def test_auth_login_refresh_logout_cycle():
    # 1. Seed organization & employee with hashed password
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email_val = f"user_{uuid.uuid4()}@test.com"
    raw_password = "secure_password123"
    hashed = hash_password(raw_password)

    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Test Org")
            session.add(org)

            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=email_val,
                full_name="Alice Test",
                role="developer",
                timezone="UTC",
                status="active",
                password_hash=hashed,
            )
            session.add(emp)

    # 2. Login request
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        login_res = await ac.post(
            "/auth/login",
            json={"email": email_val, "password": raw_password},
        )
        assert login_res.status_code == 200
        data = login_res.json()
        assert "access_token" in data
        access_token = data["access_token"]

        # Check cookies
        assert "refresh_token" in ac.cookies
        refresh_token = ac.cookies["refresh_token"]

        # 3. Call protected endpoint with access token
        # Let's verify health check doesn't need auth, but other paths do.
        # Wait, since there's no other business routes yet, let's verify auth middleware blocks or allows
        # Let's test a dummy/invalid protected route to see if auth middleware checks it.
        protected_res = await ac.get(
            "/auth/nonexistent",  # Any non-exempt route will run through auth middleware first
            headers={"Authorization": f"Bearer {access_token}"},
        )
        # Should return 404 (since route doesn't exist) but NOT 401 (auth succeeded)
        assert protected_res.status_code == 404

        # 4. Refresh request
        # Send request with the refresh cookie (handled automatically by httpx)
        refresh_res = await ac.post("/auth/refresh")
        assert refresh_res.status_code == 200
        new_data = refresh_res.json()
        assert "access_token" in new_data
        new_access_token = new_data["access_token"]
        assert new_access_token != access_token

        # Check that we got a new refresh token cookie
        new_refresh_token = ac.cookies["refresh_token"]
        assert new_refresh_token != refresh_token

        # 5. Logout request
        logout_res = await ac.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {new_access_token}"},
        )
        assert logout_res.status_code == 200
        assert ac.cookies.get("refresh_token") is None  # cookie was deleted


@pytest.mark.asyncio
async def test_revoked_token_rejected():
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    access_token, jti, exp = create_access_token(emp_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        # Before revocation, auth middleware validates it (should return 404 because path doesn't exist, not 401)
        res = await ac.get("/auth/protected-dummy", headers={"Authorization": f"Bearer {access_token}"})
        assert res.status_code == 404

        # Revoke the token
        await revocation_cache.revoke(jti, exp)

        # After revocation, must reject with 401
        res2 = await ac.get("/auth/protected-dummy", headers={"Authorization": f"Bearer {access_token}"})
        assert res2.status_code == 401
        assert res2.json()["detail"] == "Token is revoked"


@pytest.mark.asyncio
async def test_concurrent_refresh_rotation_safety():
    # Setup employee
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email_val = f"concur_{uuid.uuid4()}@test.com"
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Test Org Concurrency")
            session.add(org)
            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=email_val,
                full_name="Concur Alice",
                role="developer",
                password_hash="temp",
            )
            session.add(emp)

            # Pre-populate refresh token
            token_val = f"some_refresh_token_to_rotate_{uuid.uuid4()}"
            token_hash = hash_token(token_val)
            db_refresh = RefreshToken(
                employee_id=emp_id,
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            session.add(db_refresh)

    # Simulate two concurrent refresh requests
    # Since refresh modifies the database, we can send two requests simultaneously
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac1, \
               AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac2:
        
        ac1.cookies.set("refresh_token", token_val)
        ac2.cookies.set("refresh_token", token_val)

        # Execute concurrently
        tasks = [
            ac1.post("/auth/refresh"),
            ac2.post("/auth/refresh"),
        ]
        results = await asyncio.gather(*tasks)

        # Assert exactly one succeeded (200) and one failed (401)
        status_codes = [r.status_code for r in results]
        assert 200 in status_codes
        assert 401 in status_codes


@pytest.mark.asyncio
async def test_redis_pubsub_multi_node_propagation():
    # Instantiate a second "node" RevocationCache bypass singleton block
    cache2 = object.__new__(RevocationCache)
    cache2._revoked_jtis = {}
    cache2._pubsub_task = None
    
    await cache2.hydrate()
    await cache2.start_listener()
    
    try:
        # Give background listener task time to connect and subscribe
        await asyncio.sleep(0.1)

        jti = str(uuid.uuid4())
        expiry = time.time() + 300
        
        # Revoke on primary node
        await revocation_cache.revoke(jti, expiry)
        
        # Wait up to 1 second for propagation
        for _ in range(20):
            if cache2.is_revoked(jti):
                break
            await asyncio.sleep(0.05)
            
        assert cache2.is_revoked(jti), "Second node cache did not receive revocation message via Pub/Sub"
    finally:
        await cache2.stop_listener()
