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


class Base(AsyncAttrs, DeclarativeBase):
    pass


# Import models to register them with Base.metadata
from src.db.models.employee import Employee
from src.db.models.organization import Organization

