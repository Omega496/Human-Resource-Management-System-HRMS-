import asyncio
import hashlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from src.main import app
from src.db.base import superuser_sessionmaker
from src.db.models.organization import Organization
from src.db.models.employee import Employee
from src.db.models.invitation import Invitation
from src.modules.auth.helpers import hash_password, create_access_token


@pytest.mark.asyncio
async def test_invitation_lifecycle_and_security():
    # 1. Setup organization and admin + developer employees
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    dev_id = uuid.uuid4()
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Invite Corp")
            session.add(org)
            
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@invite.com",
                full_name="Admin User",
                role="admin",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(admin)
            
            dev = Employee(
                id=dev_id,
                organization_id=org_id,
                email=f"dev_{uuid.uuid4()}@invite.com",
                full_name="Dev User",
                role="developer",
                status="active",
                password_hash=hash_password("dev_pass"),
            )
            session.add(dev)

    # Generate tokens
    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")
    dev_token, _, _ = create_access_token(dev_id, org_id, "developer")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        # 2. Test RLS / Role check: Developer should be forbidden to invite
        fail_invite_res = await ac.post(
            "/invitations",
            headers={"Authorization": f"Bearer {dev_token}"},
            json={"email": "new_hire@invite.com", "role": "developer"},
        )
        assert fail_invite_res.status_code == 403
        assert fail_invite_res.json()["detail"] == "Only admins can issue invitations"

        # 3. Happy path invitation creation by Admin
        invite_email = f"invited_{uuid.uuid4()}@invite.com"
        invite_res = await ac.post(
            "/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"email": invite_email, "role": "developer"},
        )
        assert invite_res.status_code == 201
        data = invite_res.json()
        assert "raw_token" in data
        assert "invitation_link" in data
        assert data["email"] == invite_email
        assert data["role"] == "developer"
        raw_token = data["raw_token"]

        # 4. Accept Invitation (Happy Path)
        accept_res = await ac.post(
            "/invitations/accept",
            json={
                "email": invite_email,
                "raw_token": raw_token,
                "full_name": "New Developer",
                "password": "super_secure_new_password_123",
            },
        )
        assert accept_res.status_code == 200
        assert accept_res.json()["detail"] == "Account registered successfully"

        # Verify new employee is created and can login
        async with superuser_sessionmaker() as session:
            stmt = select(Employee).where(Employee.email == invite_email)
            res = await session.execute(stmt)
            new_emp = res.scalar_one_or_none()
            assert new_emp is not None
            assert new_emp.role == "developer"
            assert new_emp.organization_id == org_id

        # Try to login with the newly created employee
        login_res = await ac.post(
            "/auth/login",
            json={"email": invite_email, "password": "super_secure_new_password_123"},
        )
        assert login_res.status_code == 200
        assert "access_token" in login_res.json()


@pytest.mark.asyncio
async def test_invitation_rejections():
    # Setup organization and admin
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    invite_email = f"invited_{uuid.uuid4()}@invite.com"
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Reject Corp")
            session.add(org)
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@reject.com",
                full_name="Admin User",
                role="admin",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(admin)

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        # Create a valid token first
        invite_res = await ac.post(
            "/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"email": invite_email, "role": "developer"},
        )
        assert invite_res.status_code == 201
        raw_token = invite_res.json()["raw_token"]
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        # A. Mismatched email rejection
        mismatched_res = await ac.post(
            "/invitations/accept",
            json={
                "email": "attacker@reject.com",
                "raw_token": raw_token,
                "full_name": "Attacker",
                "password": "password123",
            },
        )
        assert mismatched_res.status_code == 400
        assert mismatched_res.json()["detail"] == "This invitation link is invalid or has expired."

        # B. Expired token rejection
        # Manually expire the token in database
        async with superuser_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    Invitation.__table__.update()
                    .where(Invitation.token_hash == token_hash)
                    .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
                )

        expired_res = await ac.post(
            "/invitations/accept",
            json={
                "email": invite_email,
                "raw_token": raw_token,
                "full_name": "Late Developer",
                "password": "password123",
            },
        )
        assert expired_res.status_code == 400
        assert expired_res.json()["detail"] == "This invitation link is invalid or has expired."

        # C. Already-used token rejection
        # Reset the token validity but set used_at
        async with superuser_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    Invitation.__table__.update()
                    .where(Invitation.token_hash == token_hash)
                    .values(
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                        used_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                    )
                )

        used_res = await ac.post(
            "/invitations/accept",
            json={
                "email": invite_email,
                "raw_token": raw_token,
                "full_name": "Late Developer",
                "password": "password123",
            },
        )
        assert used_res.status_code == 400
        assert used_res.json()["detail"] == "This invitation link is invalid or has expired."


@pytest.mark.asyncio
async def test_concurrent_invitation_accept_safety():
    # Setup organization and admin
    org_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    invite_email = f"invited_{uuid.uuid4()}@concur.com"
    
    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Concur Invite Corp")
            session.add(org)
            admin = Employee(
                id=admin_id,
                organization_id=org_id,
                email=f"admin_{uuid.uuid4()}@concur.com",
                full_name="Admin User",
                role="admin",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(admin)

    admin_token, _, _ = create_access_token(admin_id, org_id, "admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac1, \
               AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac2:
        # Create the invitation
        invite_res = await ac1.post(
            "/invitations",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"email": invite_email, "role": "developer"},
        )
        assert invite_res.status_code == 201
        raw_token = invite_res.json()["raw_token"]

        # Run two acceptance calls concurrently
        payload = {
            "email": invite_email,
            "raw_token": raw_token,
            "full_name": "Concurrent Dev",
            "password": "securepassword123",
        }
        
        tasks = [
            ac1.post("/invitations/accept", json=payload),
            ac2.post("/invitations/accept", json=payload),
        ]
        results = await asyncio.gather(*tasks)

        # Assert exactly one succeeded (200) and one failed (400)
        status_codes = [r.status_code for r in results]
        assert 200 in status_codes
        assert 400 in status_codes
        
        # Verify the failure got the exact uniform error
        failed_res = [r for r in results if r.status_code == 400][0]
        assert failed_res.json()["detail"] == "This invitation link is invalid or has expired."
