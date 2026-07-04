import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request

from contextlib import asynccontextmanager

from src.core.config import settings
from src.core.logging import setup_logging
from src.core.redis import redis_client
from src.db.base import async_sessionmaker_factory
from src.middleware.tenant import TenantContextMiddleware
from src.modules.auth.router import router as auth_router
from src.modules.invitations.router import router as invitations_router
from src.modules.employees.router import router as employees_router
from src.modules.attendance.router import router as attendance_router
from src.modules.leave.router import router as leave_router
from src.modules.payroll.router import router as payroll_router
from src.modules.offboarding.router import router as offboarding_router

# Setup logging
setup_logging()
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Hydrate cache and start Redis Pub/Sub listener
    from src.core.revocation import revocation_cache
    await revocation_cache.hydrate()
    await revocation_cache.start_listener()
    yield
    # Shutdown: Stop listener
    from src.core.revocation import revocation_cache
    await revocation_cache.stop_listener()


app = FastAPI(title="Zero-Trust HRMS API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(invitations_router)
app.include_router(employees_router)
app.include_router(attendance_router)
app.include_router(leave_router)
app.include_router(payroll_router)
app.include_router(offboarding_router)

# Add middleware
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Request failed",
                exc_info=exc,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    **self._get_tenant_context_fields(request),
                },
            )
            raise exc

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Request completed: {request.method} {request.url.path} -> {response.status_code}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                **self._get_tenant_context_fields(request),
            },
        )

        response.headers["X-Request-ID"] = request_id
        return response

    def _get_tenant_context_fields(self, request: Request) -> dict[str, Any]:
        ctx = getattr(request.state, "tenant_context", None)
        if ctx:
            return {
                "organization_id": str(ctx.organization_id),
                "user_id": str(ctx.user_id),
            }
        return {}


app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(TenantContextMiddleware)

# Configure CORS
if settings.ENVIRONMENT == "local":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


async def check_db_health() -> bool:
    try:
        async with async_sessionmaker_factory() as session:
            await session.execute(text("SELECT 1"))
            return True
    except Exception:
        logger.exception("Database health check failed")
        return False


async def check_redis_health() -> bool:
    try:
        await redis_client.ping()
        return True
    except Exception:
        logger.exception("Redis health check failed")
        return False


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()

    if not db_ok or not redis_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "database": "ok" if db_ok else "down",
            "redis": "ok" if redis_ok else "down",
        }

    return {"status": "healthy", "database": "ok", "redis": "ok"}
