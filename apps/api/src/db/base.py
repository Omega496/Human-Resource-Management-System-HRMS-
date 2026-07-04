from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    poolclass=pool.NullPool,  # Use NullPool to prevent event loop mismatch in tests
)

# Async sessionmaker factory
async_sessionmaker_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

def get_superuser_url(url: str) -> str:
    import os
    env_val = os.environ.get("SUPERUSER_DATABASE_URL")
    if env_val:
        return env_val
    return url.replace("hrms_app:hrms_app_password", "hrms_user:hrms_password")

# Superuser engine & sessionmaker for RLS-bypassing operations (e.g. auth lookup)
superuser_engine = create_async_engine(
    get_superuser_url(settings.DATABASE_URL),
    echo=False,
    future=True,
    poolclass=pool.NullPool,
)

superuser_sessionmaker = async_sessionmaker(
    bind=superuser_engine,
    expire_on_commit=False,
)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# Import models to register them with Base.metadata
from src.db.models.employee import Employee
from src.db.models.organization import Organization

