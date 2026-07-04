import hmac
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.main import app
from src.core.config import settings
from src.core.celery_client import celery_app
from src.db.base import async_sessionmaker_factory, superuser_sessionmaker
from src.db.models.employee import Employee
from src.db.models.organization import Organization
from src.db.models.automation_job import AutomationJob
from src.db.session import tenant_scoped_session
from src.modules.auth.helpers import hash_password, create_access_token


@pytest.mark.asyncio
async def test_create_automation_job_success():
    # 1. Seed organization & admin employee
    org_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    email_val = f"admin_{uuid.uuid4()}@test.com"
    access_token, _, _ = create_access_token(emp_id, org_id, "admin")

    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Test Org")
            session.add(org)

            emp = Employee(
                id=emp_id,
                organization_id=org_id,
                email=email_val,
                full_name="Admin User",
                role="admin",
                timezone="UTC",
                status="active",
                password_hash=hash_password("admin_pass"),
            )
            session.add(emp)

    # 2. Trigger job creation endpoint with mocked celery
    with patch.object(celery_app, "send_task") as mock_send_task:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
            res = await ac.post(
                "/automation-jobs",
                json={
                    "target_url": "https://example.com/corporate-verify",
                    "extraction_type": "domain_ownership",
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )
            
            assert res.status_code == 201
            data = res.json()
            assert "id" in data
            assert data["status"] == "queued"
            assert data["target_url"] == "https://example.com/corporate-verify"
            assert data["extraction_type"] == "domain_ownership"

            # Check if celery send_task was called with correct arguments
            mock_send_task.assert_called_once()
            called_args, called_kwargs = mock_send_task.call_args
            assert called_args[0] == "run_automation_job"
            task_kwargs = called_kwargs["kwargs"]
            assert task_kwargs["job_id"] == data["id"]
            assert task_kwargs["target_url"] == "https://example.com/corporate-verify"
            assert task_kwargs["extraction_type"] == "domain_ownership"
            
            # Critical Security Rule check: Ensure organization_id is NOT in celery payload
            assert "organization_id" not in task_kwargs


@pytest.mark.asyncio
async def test_automation_callback_valid_signature():
    # 1. Seed organization & create a job
    org_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Test Org Callback")
            session.add(org)

            job = AutomationJob(
                id=job_id,
                organization_id=org_id,
                status="queued",
                target_url="https://test.com",
                extraction_type="test",
            )
            session.add(job)

    # 2. Construct valid signed payload
    payload = {
        "job_id": str(job_id),
        "extracted_text": "Successfully extracted text content.",
        "issued_at": int(time.time()),
    }
    raw_body = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    secret = settings.AUTOMATION_CALLBACK_SECRET.get_secret_value()
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # 3. Post callback
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/internal/automation/callback",
            content=raw_body,
            headers={"X-Signature": signature, "Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json() == {"status": "success"}

    # 4. Verify job status updated to completed in DB
    async with superuser_sessionmaker() as session:
        stmt = select(AutomationJob).where(AutomationJob.id == job_id)
        db_job = (await session.execute(stmt)).scalar_one()
        assert db_job.status == "completed"
        assert db_job.result_text == "Successfully extracted text content."
        assert db_job.completed_at is not None


@pytest.mark.asyncio
async def test_automation_callback_tampered_body():
    org_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Test Org Callback Tamper")
            session.add(org)

            job = AutomationJob(
                id=job_id,
                organization_id=org_id,
                status="queued",
                target_url="https://test.com",
                extraction_type="test",
            )
            session.add(job)

    # Compute signature for original body
    payload = {
        "job_id": str(job_id),
        "extracted_text": "Successfully extracted text content.",
        "issued_at": int(time.time()),
    }
    raw_body = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    secret = settings.AUTOMATION_CALLBACK_SECRET.get_secret_value()
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Tamper with the body (change extracted_text) but send the old signature
    payload["extracted_text"] = "Hacked/modified extraction text."
    tampered_body = json.dumps(payload, separators=(',', ':')).encode("utf-8")

    # Send callback
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/internal/automation/callback",
            content=tampered_body,
            headers={"X-Signature": signature, "Content-Type": "application/json"},
        )
        # Should be rejected with 401
        assert res.status_code == 401

    # Verify job status remains queued
    async with superuser_sessionmaker() as session:
        stmt = select(AutomationJob).where(AutomationJob.id == job_id)
        db_job = (await session.execute(stmt)).scalar_one()
        assert db_job.status == "queued"
        assert db_job.result_text is None


@pytest.mark.asyncio
async def test_automation_callback_stale_timestamp():
    org_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with superuser_sessionmaker() as session:
        async with session.begin():
            org = Organization(id=org_id, name="Test Org Callback Stale")
            session.add(org)

            job = AutomationJob(
                id=job_id,
                organization_id=org_id,
                status="queued",
                target_url="https://test.com",
                extraction_type="test",
            )
            session.add(job)

    # Payload with timestamp older than 5 minutes (e.g., 10 minutes ago)
    stale_issued_at = int(time.time()) - 600
    payload = {
        "job_id": str(job_id),
        "extracted_text": "Extracted text content.",
        "issued_at": stale_issued_at,
    }
    raw_body = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    secret = settings.AUTOMATION_CALLBACK_SECRET.get_secret_value()
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/internal/automation/callback",
            content=raw_body,
            headers={"X-Signature": signature, "Content-Type": "application/json"},
        )
        assert res.status_code == 401
        assert "Request expired" in res.json()["detail"]

    # Verify job remains queued
    async with superuser_sessionmaker() as session:
        stmt = select(AutomationJob).where(AutomationJob.id == job_id)
        db_job = (await session.execute(stmt)).scalar_one()
        assert db_job.status == "queued"


@pytest.mark.asyncio
async def test_automation_callback_tenant_isolation():
    # 1. Seed two organizations
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with superuser_sessionmaker() as session:
        async with session.begin():
            org_a = Organization(id=org_a_id, name="Org A")
            org_b = Organization(id=org_b_id, name="Org B")
            session.add(org_a)
            session.add(org_b)

            # Job belongs to Org A
            job = AutomationJob(
                id=job_id,
                organization_id=org_a_id,
                status="queued",
                target_url="https://test.com",
                extraction_type="test",
            )
            session.add(job)

    # 2. Construct signed callback payload but try to inject a fraudulent organization_id field
    payload = {
        "job_id": str(job_id),
        "organization_id": str(org_b_id),  # Claim to belong to Org B
        "extracted_text": "Extracted text under Org A job.",
        "issued_at": int(time.time()),
    }
    raw_body = json.dumps(payload, separators=(',', ':')).encode("utf-8")
    secret = settings.AUTOMATION_CALLBACK_SECRET.get_secret_value()
    signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # 3. Post callback (should process successfully but ignore organization_id claim)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        res = await ac.post(
            "/internal/automation/callback",
            content=raw_body,
            headers={"X-Signature": signature, "Content-Type": "application/json"},
        )
        assert res.status_code == 200

    # 4. Verify job is completed under Org A, and Org B does not own/access it
    async with superuser_sessionmaker() as session:
        stmt = select(AutomationJob).where(AutomationJob.id == job_id)
        db_job = (await session.execute(stmt)).scalar_one()
        assert db_job.status == "completed"
        assert db_job.organization_id == org_a_id

    # 5. Verify Org B tenant session cannot read this job row due to RLS
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_b_id)) as session_b:
        stmt_b = select(AutomationJob).where(AutomationJob.id == job_id)
        job_in_b = (await session_b.execute(stmt_b)).scalar_one_or_none()
        assert job_in_b is None, "Org B tenant session must not read Org A's job record"

    # 6. Verify Org A tenant session can read it
    async with tenant_scoped_session(async_sessionmaker_factory, str(org_a_id)) as session_a:
        stmt_a = select(AutomationJob).where(AutomationJob.id == job_id)
        job_in_a = (await session_a.execute(stmt_a)).scalar_one_or_none()
        assert job_in_a is not None, "Org A tenant session should read its own job record"
