import os
import sys

# Set test environment variables before any app imports happen
os.environ["DATABASE_URL"] = "postgresql+asyncpg://hrms_app:hrms_app_password@localhost:5433/hrms_db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["JWT_SIGNING_KEY"] = "test_signing_key_not_for_prod"
os.environ["ENVIRONMENT"] = "local"

# Ensure src is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
