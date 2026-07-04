import os
import hmac
import hashlib
import time
import json
import logging
from celery import Celery
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("automation_worker")

# Read settings from environment only (No database or Redis connection string hardcoded or in config)
broker_url = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL")
if not broker_url:
    logger.warning("No CELERY_BROKER_URL or REDIS_URL found in environment. Defaulting to redis://localhost:6379/0 for development.")
    broker_url = "redis://localhost:6379/0"

# Initialize Celery
app = Celery("automation", broker=broker_url)

@app.task(name="run_automation_job")
def run_automation_job(job_id: str, target_url: str, extraction_type: str) -> None:
    logger.info(f"Starting automation job {job_id} for url {target_url} (type: {extraction_type})")
    
    extracted_text = ""
    try:
        # Perform extraction using Playwright
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(target_url, timeout=30000)
            
            title = page.title()
            body_text = page.locator("body").inner_text()
            extracted_text = f"Title: {title}\n\nContent:\n{body_text}"
            browser.close()
    except Exception as e:
        logger.exception(f"Playwright extraction failed for {target_url}. Falling back to placeholder extraction.")
        extracted_text = f"Placeholder extraction for {target_url} (type: {extraction_type}). Error: {str(e)}"
    
    # Get internal callback base URL from env
    api_base_url = os.environ.get("API_INTERNAL_BASE_URL", "http://localhost:8000")
    callback_url = f"{api_base_url.rstrip('/')}/internal/automation/callback"
    
    # Construct signed payload
    issued_at = int(time.time())
    payload = {
        "job_id": job_id,
        "extracted_text": extracted_text,
        "issued_at": issued_at
    }
    
    # Serialize to raw bytes exactly as it will be posted
    raw_request_body_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    
    # Retrieve the shared secret from environment
    shared_secret = os.environ.get("AUTOMATION_CALLBACK_SECRET")
    if not shared_secret:
        raise ValueError("AUTOMATION_CALLBACK_SECRET environment variable is not set")
    
    # Compute signature
    signature = hmac.new(
        shared_secret.encode('utf-8'),
        raw_request_body_bytes,
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature
    }
    
    logger.info(f"Posting result for job {job_id} to {callback_url}")
    try:
        response = httpx.post(callback_url, content=raw_request_body_bytes, headers=headers, timeout=10)
        logger.info(f"Callback responded with status {response.status_code}: {response.text}")
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Callback failed: {e}")
        raise e
