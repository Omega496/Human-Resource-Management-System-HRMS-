# ADR-0002: Bulk Revocation using Valid-After Watermark

- **Status**: Accepted
- **Context**:
  To protect against token-compromise attacks and support security flows like forcing a password reset or closing all active sessions for a compromised user account, the system needs a way to instantly invalidate all outstanding tokens issued to a specific employee. 
  
  The default strategy is a JTI-based blacklist in Redis. However, if a user has many active sessions (e.g., across multiple devices), tracking, broadcasting, and checking every individual `jti` in real-time creates a significant caching overhead. Additionally, if the Redis key space is corrupted or evicted, some active compromised sessions might fail to revoke.
  
  Therefore, we need to decide if and how to implement a user-scoped bulk revocation watermark.

- **Decision**:
  1. We will implement the proposed bulk-revocation extension by maintaining a Redis key `tokens_valid_after:<user_id> = <timestamp>` whenever a user triggers a bulk logout, password reset, or admin-initiated termination.
  2. The authorization middleware will perform two checks for every incoming request:
     - Check if the JWT's `jti` is present in the local/Redis token blacklist.
     - Check if the JWT's `iat` (issued at timestamp) is less than the timestamp stored in `tokens_valid_after:<user_id>`. If it is, the token is rejected.
  3. When bulk logout is triggered, the watermark will be updated to the current time, and a Redis Pub/Sub notification will be broadcast to all instances to update their local in-memory watermarks for that user.

- **Consequences**:
  - *Benefits*:
    - Strictly upholds **Prime Directive #2** (Near-instant session revocation).
    - Drastically reduces memory consumption in Redis compared to blacklisting hundreds of individual JTIs.
    - Allows immediate, reliable key rotation/invalidation across all user devices.
  - *Trade-offs*:
    - Requires JWTs to carry a precise `iat` (issued-at) timestamp.
    - Middleware must query/cache the watermark value, slightly increasing the validation check scope.

- **Alternatives considered**:
  - *Individual JTI Blacklisting Only*: Rejected because bulk logout of many sessions requires storing many JTIs in memory and searching them, causing potential performance degradation.
  - *Querying Database on Every Request*: Rejected because hitting the PostgreSQL database on every API call breaks performance requirements.
