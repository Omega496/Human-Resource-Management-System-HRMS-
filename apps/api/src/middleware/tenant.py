import uuid

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.core.config import settings
from src.core.context import TenantContext


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        debug_org_id = request.headers.get("X-Debug-Org-Id")

        if debug_org_id:
            if settings.ENVIRONMENT != "local":
                # Raise hard error outside local environment
                raise HTTPException(
                    status_code=400,
                    detail="X-Debug-Org-Id header is only allowed in local environment",
                )
            try:
                org_uuid = uuid.UUID(debug_org_id)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid X-Debug-Org-Id header value. Must be a valid UUID",
                )

            # Placholders for user_id and role
            user_uuid = uuid.UUID("00000000-0000-0000-0000-000000000000")
            request.state.tenant_context = TenantContext(
                organization_id=org_uuid,
                user_id=user_uuid,
                role="admin",
            )
        else:
            request.state.tenant_context = None

        response = await call_next(request)
        return response
