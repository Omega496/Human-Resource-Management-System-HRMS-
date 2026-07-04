from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.context import TenantContext
from src.db.base import async_sessionmaker_factory


@asynccontextmanager
async def tenant_scoped_session(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: str,
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :org_id, true)"),
                {"org_id": organization_id},
            )
            yield session
        # COMMIT happens automatically on clean exit of session.begin();
        # ROLLBACK happens automatically if an exception propagates.


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    ctx: TenantContext | None = getattr(request.state, "tenant_context", None)
    if ctx is None:
        raise RuntimeError("Tenant context missing from request state")
    async with tenant_scoped_session(async_sessionmaker_factory, str(ctx.organization_id)) as session:
        yield session
