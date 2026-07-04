# Authentication (auth) Module

## Domain Responsibilities & Boundary
The `auth` module manages user authentication, token issuance, refresh token rotation (cookie-based), and session revocation. It does not manage employee profile details or roles directly, but interacts with the database to verify credentials and retrieve roles.

## Prime Directives Enforced
* **Directive #2 (Near-Instant Session Revocation):** Access token claims (`jti` and `exp`) are validated on each request. Revoked tokens are published to a Redis Pub/Sub channel and cached in memory per-process to ensure near-instant revocation without database round-trips.
  * *Code references:* `src/core/revocation.py` manages hydration and pub/sub listening. `src/modules/auth/router.py` calls `revocation_cache.revoke()` upon logout.

## Primary Entry Points
* **Router:** `apps/api/src/modules/auth/router.py`
  * `POST /auth/login` - Validate password, save `RefreshToken` record, set `refresh_token` HttpOnly cookie, and return JWT access token.
  * `POST /auth/refresh` - Rotate refresh token (race-safely) and issue a new access token.
  * `POST /auth/logout` - Revoke tokens, delete cookie.
* **Helpers:** `apps/api/src/modules/auth/helpers.py` (hashing, verify password, create/decode token).

## Operational Gotchas & DB Locking
* **Refresh Token Rotation Race Safety:** When rotating tokens, a conditional update is executed:
  ```python
  update(RefreshToken)
  .where(RefreshToken.id == db_token.id, RefreshToken.revoked_at.is_(None))
  .values(revoked_at=datetime.now(timezone.utc))
  ```
  This ensures that concurrent refresh requests using the same token cannot succeed twice, mitigating token-reuse/replay attacks.
