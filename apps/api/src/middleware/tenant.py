import logging
import uuid

import jwt
from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from src.core.context import TenantContext
from src.modules.auth.helpers import decode_access_token
from src.core.revocation import revocation_cache

logger = logging.getLogger(__name__)

# Paths that do not require JWT authentication
EXEMPT_PATHS = {"/healthz", "/auth/login", "/auth/refresh"}


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Check path exemption (including FastAPI auto-docs)
        if (
            path in EXEMPT_PATHS
            or path.startswith("/docs")
            or path.startswith("/openapi.json")
            or path.startswith("/redoc")
        ):
            request.state.tenant_context = None
            return await call_next(request)

        # Extract and verify authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid authorization credentials"},
            )

        token = auth_header.split(" ", 1)[1]
        try:
            claims = decode_access_token(token)
            jti = claims.get("jti")
            if not jti or revocation_cache.is_revoked(jti):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Token is revoked"},
                )

            # Populate tenant context from verified claims
            request.state.tenant_context = TenantContext(
                organization_id=uuid.UUID(claims["org_id"]),
                user_id=uuid.UUID(claims["sub"]),
                role=claims["role"],
            )
        except jwt.InvalidTokenError as e:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": str(e)},
            )
        except Exception as e:
            logger.error(f"Authentication error: {e}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication failed"},
            )

        return await call_next(request)
