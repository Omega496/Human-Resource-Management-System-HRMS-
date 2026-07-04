import hmac
import hashlib
import json
import time
import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.celery_client import celery_app
from src.db.session import get_db, tenant_scoped_session
from src.db.base import async_sessionmaker_factory, superuser_sessionmaker
from src.db.models.automation_job import AutomationJob

logger = logging.getLogger(__name__)

# Standard router (public/admin facing)
public_router = APIRouter(tags=["automation"])

# Internal router (callback endpoint, not exposed publicly)
internal_router = APIRouter(tags=["automation_internal"])


class AutomationJobCreate(BaseModel):
    target_url: HttpUrl
    extraction_type: str


@public_router.post("/automation-jobs", status_code=status.HTTP_201_CREATED)
async def create_automation_job(
    payload: AutomationJobCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    
    # 1. Create the job row with status='queued'
    # Tenant context is active because of get_db dependency, which forces RLS
    job = AutomationJob(
        organization_id=ctx.organization_id,
        target_url=str(payload.target_url),
        extraction_type=payload.extraction_type,
        status="queued"
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    
    # 2. Enqueue Celery task with only non-sensitive params (never organization_id)
    # Task receives job_id, target_url, extraction_type
    celery_app.send_task(
        "run_automation_job",
        kwargs={
            "job_id": str(job.id),
            "target_url": job.target_url,
            "extraction_type": job.extraction_type,
        }
    )
    
    return {
        "id": job.id,
        "status": job.status,
        "target_url": job.target_url,
        "extraction_type": job.extraction_type,
        "created_at": job.created_at
    }


@internal_router.post("/internal/automation/callback", status_code=status.HTTP_200_OK)
async def automation_callback(request: Request):
    # a. Recompute HMAC over raw request body using shared secret
    body_bytes = await request.body()
    
    # Get signature from header
    signature = request.headers.get("X-Signature")
    if not signature:
        logger.warning("Callback received without X-Signature header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature"
        )
    
    shared_secret = settings.AUTOMATION_CALLBACK_SECRET.get_secret_value()
    expected_signature = hmac.new(
        shared_secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256
    ).hexdigest()
    
    # Reject with 401 on any signature mismatch using constant-time comparison
    if not hmac.compare_digest(expected_signature, signature):
        logger.warning("Callback signature mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )
    
    # Parse body
    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    # Extract payload fields
    job_id_str = payload.get("job_id")
    extracted_text = payload.get("extracted_text")
    issued_at = payload.get("issued_at")
    
    # Validate payload parameters
    if not job_id_str or issued_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields in payload"
        )
    
    try:
        job_id = uuid.UUID(job_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format"
        )
        
    # b. Reject if issued_at is older than the allowed replay window
    now_ts = int(time.time())
    replay_window = settings.REPLAY_WINDOW_SECONDS
    if now_ts - issued_at > replay_window:
        logger.warning(f"Callback rejected due to stale timestamp: issued_at={issued_at}, now={now_ts}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Request expired (replay protection)"
        )
        
    # c. Look up automation_jobs by job_id to get organization_id (Tenant context re-derivation).
    # Since we are outside the request's default tenant session context, we query using
    # superuser_sessionmaker to bypass RLS reads and discover the tenant identity.
    async with superuser_sessionmaker() as super_db:
        stmt = select(AutomationJob).where(AutomationJob.id == job_id)
        res = await super_db.execute(stmt)
        job = res.scalar_one_or_none()
        
    if not job:
        logger.warning(f"Job not found for ID: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation job not found"
        )
        
    # Security Rule enforcement:
    # Never trust the callback body's own claims about tenant identity/organization_id.
    # We log a warning if it tries to pass one, but we never use it.
    if "organization_id" in payload:
        logger.warning(
            "Security notice: callback payload supplied 'organization_id' which will be ignored. "
            "Tenant context is derived only from the database job record."
        )

    # d. Update the job row with result and status='completed' inside a tenant-scoped session.
    organization_id = job.organization_id
    
    async with tenant_scoped_session(async_sessionmaker_factory, str(organization_id)) as tenant_db:
        stmt = (
            update(AutomationJob)
            .where(AutomationJob.id == job_id)
            .values(
                status="completed",
                result_text=extracted_text,
                completed_at=datetime.now(timezone.utc)
            )
        )
        await tenant_db.execute(stmt)

    return {"status": "success"}
