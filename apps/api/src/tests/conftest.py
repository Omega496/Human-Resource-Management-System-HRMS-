import os
import sys

# Set test environment variables before any app imports happen
os.environ["DATABASE_URL"] = "postgresql+asyncpg://hrms_app:hrms_app_password@localhost:5433/hrms_db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["JWT_SIGNING_KEY"] = "test_signing_key_not_for_prod"
os.environ["ENVIRONMENT"] = "local"
os.environ["AUTOMATION_CALLBACK_SECRET"] = "test_automation_callback_secret_123456789"
os.environ["REPLAY_WINDOW_SECONDS"] = "300"

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import pytest_asyncio
from src.core.redis import redis_client
from src.db.base import engine, superuser_engine


@pytest_asyncio.fixture(autouse=True)
async def cleanup_connections():
    yield
    # Close Redis client connections to prevent loop mismatch
    await redis_client.aclose()
    # Dispose database engines to prevent loop mismatch
    await engine.dispose()
    await superuser_engine.dispose()
