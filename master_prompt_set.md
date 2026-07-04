# Master Prompt Set — Zero-Trust HRMS

Every prompt below is written to be pasted directly into Antigravity (or an equivalent autonomous
coding agent) as a fresh task. Each one assumes the agent has read access to the repository and,
critically, to `AGENT.md` and `system_architecture.md` at the repo root — every prompt references
those files rather than restating their contents, so keep them up to date as the source of truth.
Placeholders are marked `{{LIKE_THIS}}`. Replace every placeholder before sending.

Prompts are grouped by workflow phase. Use the numbering to track which ones a given task has
already run through (e.g., a new feature typically runs Prompt 2's pattern, then 15, then 19).

---

## Group A — Scaffolding

### PROMPT 1: Monorepo & Environment Scaffolding
**Purpose**: The very first prompt for this project. Run once, before any feature work, to stand up the empty repository skeleton, tooling, and local dev environment.

**Prompt**:
```
You are scaffolding a new monorepo from scratch for a project called "Zero-Trust HRMS." Before
writing any code, read the two files I will attach: AGENT.md and system_architecture.md. Treat
every rule in AGENT.md as a hard constraint on the structure you create, and use §4 of AGENT.md
(Repository Layout) as the exact target directory tree — do not deviate from it without asking me
first.

Your task:
1. Create the top-level directory structure exactly as specified in AGENT.md §4.
2. Initialize `apps/api` as a `uv`-managed Python project (Python 3.12), with `pyproject.toml`
   declaring: fastapi, uvicorn[standard], pydantic>=2, sqlalchemy[asyncio], asyncpg, alembic,
   redis, celery, python-jose[cryptography] (or a maintained equivalent JWT library — tell me
   which you chose and why), passlib[bcrypt], pytest, pytest-asyncio, httpx, ruff, mypy.
2a. Run `uv sync` and confirm it completes with a committed `uv.lock`.
3. Initialize `apps/web-employee` and `apps/web-admin` as two independent Vite + React +
   TypeScript projects (`npm create vite@latest -- --template react-ts`), each with
   `"strict": true` in tsconfig, ESLint, and Prettier configured identically across both.
4. Create `packages/shared-types` as an empty TypeScript package for now (a placeholder
   `package.json` and `README.md` explaining it will later hold OpenAPI-generated types) — do not
   generate types yet, there's no API schema to generate from.
5. Write a root `docker-compose.yml` that brings up: `postgres:16` (with `btree_gist`, `citext`,
   and `pgcrypto` extensions enabled via an init script), `redis:7`, and placeholder service blocks
   for `api`, `worker`, and `automation` (these can `command: sleep infinity` for now — we'll fill
   in real Dockerfiles in later prompts).
6. Add a root `.gitignore` covering Python, Node, and Docker artifacts.
7. Do NOT write any application code yet — this prompt is scaffolding only. Stop and show me the
   resulting tree structure before doing anything else.

Confirm before proceeding: does the AGENT.md repository layout conflict with anything about how
Vite structures a fresh project? If so, tell me the conflict and propose a resolution rather than
silently picking one.
```

**Expected Output**: A committed initial tree matching `AGENT.md` §4, a working `docker compose up`
that starts Postgres/Redis cleanly, both frontend projects running `npm run dev` with a default Vite
splash page, and an explicit written confirmation of any structural conflicts found.

**Notes**: Run this exactly once. If the repo already exists and you need to add a *new* app
(e.g., a future mobile client), write a fresh, narrower scaffolding prompt rather than re-running
this one, since re-running against an existing structure risks the agent "fixing" things you
already customized.

---

### PROMPT 2: Backend Service Bootstrap
**Purpose**: Stand up the actual FastAPI application skeleton (settings, DB session plumbing, health check) inside the `apps/api` scaffold created by Prompt 1, before any feature module exists.

**Prompt**:
```
Working inside `apps/api` (already scaffolded per AGENT.md §4). Read AGENT.md §5–§8 and
system_architecture.md §3 before starting — the tenant-context session pattern in
system_architecture.md §3 is not optional and must be implemented exactly as described there, not
approximated.

Build the following, in this order, running tests after each step:

1. `src/core/config.py`: a Pydantic v2 `Settings` (BaseSettings) class reading from environment
   variables — `DATABASE_URL`, `REDIS_URL`, `JWT_SIGNING_KEY`, `JWT_ACCESS_TOKEN_TTL_SECONDS`
   (default 600), `ENVIRONMENT`. No secret may have a hardcoded default value.
2. `src/db/base.py`: SQLAlchemy async engine + `async_sessionmaker`, plus a declarative `Base`.
3. `src/db/session.py`: implement `tenant_scoped_session()` and the `get_db()` FastAPI dependency
   EXACTLY as specified in system_architecture.md §3's code sample — including the `SET LOCAL
   app.current_organization_id` call inside the same transaction, and the `true` fail-closed
   pattern from §4.2 for reading it back.
4. A placeholder `TenantContext` dataclass (`organization_id`, `user_id`, `role`) and a stub
   `request.state.tenant_context` — full JWT-based population of this comes in Prompt 5; for now,
   stub it with a `X-Debug-Org-Id` header ONLY when `ENVIRONMENT=local`, and raise a hard error if
   that header is used outside `local`.
5. `src/main.py`: FastAPI app instance, CORS configured for `http://localhost:5173` and
   `http://localhost:5174` (the two Vite dev servers) in local only, structured JSON logging setup
   (one log line per request including `request_id`), and a `GET /healthz` endpoint that checks
   both the DB and Redis connections and returns 200/503 accordingly.
6. Write a test in `src/tests/test_health.py` that boots the app against the docker-compose
   Postgres/Redis and asserts `/healthz` returns 200.

After each numbered step, run `uv run pytest -q` and `uv run mypy src` and paste me the output
before moving to the next step. Do not proceed to step N+1 if step N's tests are red.
```

**Expected Output**: A running `uvicorn` app with a green `/healthz`, a fully implemented
`get_db()` dependency matching the architecture doc, clean `mypy`/`ruff`, and a short summary of
what was built at each step with its test output.

**Notes**: The debug-header tenant stub in step 4 is deliberately temporary scaffolding — Prompt 5
replaces it entirely with real JWT-derived tenant context. If the agent tries to "keep it around as
a backdoor for testing," push back; it should be deleted, not merely gated, once Prompt 5 lands.

---

### PROMPT 3: Core Database Schema & Alembic Migration Baseline
**Purpose**: Establish the foundational tables (`organizations`, `employees`) and the Alembic migration discipline the rest of the project will follow. Run once, early, before any feature-specific tables.

**Prompt**:
```
Working in `apps/api`. Read AGENT.md §8 (Database & Migration Discipline) and
system_architecture.md §4.1–§4.2 before starting.

1. Configure Alembic (`alembic init alembic`, wired to read `DATABASE_URL` from our Settings class,
   async-compatible env.py using `run_sync`).
2. Write the first migration, enabling extensions only (nothing else in this migration):
   `btree_gist`, `citext`, `pgcrypto`.
3. Write a second migration creating `organizations`:
   - id UUID PK default gen_random_uuid()
   - name TEXT NOT NULL
   - created_at TIMESTAMPTZ NOT NULL DEFAULT now()
4. Write a third migration creating `employees`:
   - id UUID PK default gen_random_uuid()
   - organization_id UUID NOT NULL REFERENCES organizations(id)
   - email CITEXT NOT NULL
   - full_name TEXT NOT NULL
   - role TEXT NOT NULL
   - timezone TEXT NOT NULL DEFAULT 'UTC'  -- IANA string, validated at the application layer, not by a DB constraint
   - status TEXT NOT NULL DEFAULT 'active'  -- active | terminated
   - deleted_at TIMESTAMPTZ  -- soft-delete marker, NULL while active
   - created_at TIMESTAMPTZ NOT NULL DEFAULT now()
   - UNIQUE (organization_id, email)
   In the SAME migration, enable and force RLS on `employees` and add the tenant-isolation policy,
   using the exact pattern from system_architecture.md §4.2. Do not create the table in one
   migration and RLS in a later one — for this table they ship together.
5. Write corresponding SQLAlchemy ORM models in `src/db/models/organization.py` and
   `src/db/models/employee.py`.
6. Every migration must implement a working `downgrade()`. Prove it by running, for each
   migration in turn: `alembic upgrade head`, then `alembic downgrade -1`, then `alembic upgrade
   head` again, and pasting the output showing no errors.
7. Write a test that opens a session as Org A (via the debug header from Prompt 2), inserts an
   employee, opens a second session as Org B, and asserts a `SELECT * FROM employees` from Org B's
   session returns zero rows even though Org A's row physically exists in the table. This is the
   first RLS proof point — Prompt 16 will build the full adversarial suite later, but do not skip
   this minimal version now.

Show me the migration files, the ORM models, and the up/down/up test output before considering this
done.
```

**Expected Output**: Three clean, reversible migrations; `employees` with RLS enabled and forced
from the moment it's created; a passing cross-tenant isolation test; ORM models matching the schema
exactly (including the `CITEXT` and soft-delete columns).

**Notes**: The temptation here is to create the table first and "add RLS later" — explicitly forbid
that in the prompt (already done above) because a table that ever existed without RLS, even
briefly, is a window where a bug could have shipped against it unprotected.

---

## Group B — Core Feature Implementation

### PROMPT 4: Row-Level Security Tenant Isolation — Full Rollout
**Purpose**: Apply the RLS pattern established in Prompt 3 to every subsequent tenant-scoped table as the project grows, and to retrofit it if a table is ever found missing it. Use this prompt every time a new tenant-scoped table is proposed.

**Prompt**:
```
I am adding a new table, `{{TABLE_NAME}}`, to the HRMS schema. Read system_architecture.md §4.2
and AGENT.md Prime Directive #1 before doing anything.

The table's columns are:
{{PASTE_PROPOSED_COLUMN_LIST_HERE}}

Requirements, all in a single Alembic migration:
1. Create the table with an `organization_id UUID NOT NULL REFERENCES organizations(id)` column
   (add it to the column list above if I forgot it — do not create a tenant-scoped table without
   it, and ask me to confirm if it's genuinely unnecessary for this table rather than assuming).
2. `ALTER TABLE {{TABLE_NAME}} ENABLE ROW LEVEL SECURITY;` and `FORCE ROW LEVEL SECURITY;` in the
   same migration as table creation, never a follow-up migration.
3. A policy named `tenant_isolation_{{TABLE_NAME}}` using exactly this pattern (adapt only the
   table name):
   ```sql
   CREATE POLICY tenant_isolation_{{TABLE_NAME}} ON {{TABLE_NAME}}
       USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
       WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);
   ```
4. An ORM model in `src/db/models/{{module_name}}.py` matching the schema.
5. A new test case added to the RLS adversarial suite (`src/tests/test_rls_adversarial.py` — create
   this file if Prompt 16 hasn't run yet) proving: (a) an Org A session cannot read an Org B row in
   this table, (b) an Org A session cannot write a row with Org B's `organization_id` — the
   `WITH CHECK` clause should reject it, and the test should assert on that rejection specifically,
   not just on the row being absent afterward.
6. Verify migration reversibility (up/down/up) and paste the output.

If `{{TABLE_NAME}}` is one of the tables with special behavior described in
system_architecture.md (`leave_requests`' exclusion constraint, `payroll_ledger_lines`' immutability
trigger), stop and tell me — those need Prompt 8 or Prompt 9 instead of this generic one, since they
have additional requirements beyond RLS alone.
```

**Expected Output**: A migration, ORM model, and adversarial test for the new table, following the
exact same pattern as every prior tenant-scoped table, with no drift in policy naming or structure.

**Notes**: This prompt is meant to be run dozens of times over the project's life — its value is in
forcing every new table through the identical checklist rather than letting RLS become
inconsistent across tables as the schema grows.

---

### PROMPT 5: JWT Auth + Redis Tiered Session Revocation
**Purpose**: Implement the full authentication and session-revocation architecture described in system_architecture.md §5. This replaces the debug-header stub from Prompt 2.

**Prompt**:
```
Read system_architecture.md §5 in full before starting — the two-tier (local cache + Redis
Pub/Sub) revocation design is the actual point of this task, not just "add JWT auth."

Build, in `src/modules/auth/`:

1. `POST /auth/login` — accepts email + password (bcrypt-verified via passlib), issues:
   - an access token: JWT signed with our `JWT_SIGNING_KEY`, claims `sub` (employee id), `org_id`,
     `role`, `jti` (a fresh UUID4 per token), `iat`, `exp` (now + `JWT_ACCESS_TOKEN_TTL_SECONDS`).
   - a refresh token: a high-entropy random string (NOT a JWT), stored hashed in a new
     `refresh_tokens` table (id, employee_id, token_hash, expires_at, revoked_at, created_at),
     delivered as an `HttpOnly`, `Secure`, `SameSite=Strict` cookie. Refresh tokens are NOT
     tenant-scoped RLS-wise in the same sense as business data, but the table still needs
     appropriate access control — no employee should be able to query another's refresh tokens
     through any endpoint.

2. `POST /auth/refresh` — reads the refresh cookie, looks up its hash, checks `revoked_at IS NULL`
   and `expires_at > now()`, and ROTATES it: marks the old one revoked and issues a brand new
   refresh token + new access token in the same request. This must be race-safe — use a conditional
   update (`UPDATE ... WHERE id = :id AND revoked_at IS NULL RETURNING id`) the same way the
   invitation single-use check works, so two concurrent refresh attempts with the same (stolen or
   duplicated) token can't both succeed.

3. `POST /auth/logout` — revokes the current refresh token AND writes `revoked_jti:<jti>` to Redis
   with a TTL equal to the token's remaining lifetime, then `PUBLISH`es the jti on channel
   `session_revocations`, exactly as diagrammed in system_architecture.md §5.

4. A `RevocationCache` singleton (`src/core/revocation.py`) — an in-process TTL dict — that:
   - subscribes to Redis channel `session_revocations` on app startup and adds any received jti.
   - on app startup, before accepting traffic, also hydrates from whatever mechanism you choose in
     Redis for currently-active revocations (state your choice and why — e.g., a Redis sorted set
     keyed by expiry timestamp, scannable in bulk) so a freshly started node isn't vulnerable to a
     stale-cache window.
   - exposes `is_revoked(jti: str) -> bool`, checked purely from memory, no network call.

5. Replace the Prompt 2 debug-header stub entirely: the real auth middleware now verifies the JWT
   signature/exp, calls `RevocationCache.is_revoked(claims["jti"])` and rejects with 401 if true,
   and populates `request.state.tenant_context` from the verified claims. Delete the debug header
   path completely — do not leave it gated behind an environment check "just in case."

6. Tests: successful login/refresh/logout cycle; a revoked-then-reused access token rejected;
   simulate two concurrent refresh attempts with the same token and assert exactly one succeeds;
   a Redis Pub/Sub integration test proving a second simulated "node" (a second `RevocationCache`
   instance in the test) picks up the revocation within a short bounded time.

Paste all new/changed files and full test output when done.
```

**Expected Output**: Working login/refresh/logout, a demonstrably race-safe refresh rotation, a
revocation cache that other "nodes" (simulated in tests) converge on within milliseconds, and
complete removal of the Prompt 2 debug stub.

**Notes**: The hardest part to get right is the startup-hydration step — if the agent skips it, flag
it explicitly, since a rolling deploy that spins up new nodes would otherwise have a real (if brief)
window where a just-revoked token is still accepted by the newest node.

---

### PROMPT 6: Tokenized Invitation System
**Purpose**: Implement the invitation-only registration flow described in system_architecture.md §7. Depends on Prompt 5 (auth) existing first.

**Prompt**:
```
Read system_architecture.md §7 before starting. Public sign-up must never exist in this system —
`POST /auth/register` (without a valid invitation) should not exist as a route at all, not merely
be disabled.

Build, in `src/modules/invitations/`:

1. The `invitations` table exactly as specified in system_architecture.md §7 (id, organization_id,
   email CITEXT, token_hash, role, invited_by, expires_at, used_at, created_at). Ship RLS on this
   table in the same migration, following Prompt 4's pattern (an admin issuing invitations should
   only ever see their own org's invitations).

2. `POST /invitations` (admin-only role check, in addition to the standard RLS-scoped session):
   generates a cryptographically random raw token (`secrets.token_urlsafe(32)` or equivalent),
   stores only `sha256(raw_token)` as `token_hash`, sets `expires_at = now() + 24 hours`, and
   returns/emails a registration link containing the RAW token (never store the raw token anywhere
   — if you find yourself wanting to log it "for debugging," don't).

3. `POST /invitations/accept`: given `{{email}}`, `{{raw_token}}`, and new account details (name,
   password): 
   - compute `sha256(raw_token)`, look up the invitation by `token_hash`.
   - verify `email` matches the invitation's `email` exactly (case-insensitively, via CITEXT).
   - perform the single-use claim via the conditional update pattern from
     system_architecture.md §7:
     ```sql
     UPDATE invitations
        SET used_at = now()
      WHERE id = :id AND used_at IS NULL AND expires_at > now()
     RETURNING id;
     ```
   - if zero rows returned, respond with one single generic error ("This invitation link is
     invalid or has expired.") regardless of whether the real cause was "already used," "expired,"
     or "not found" — do not let the error message distinguish these cases.
   - on success, create the `employees` row in the SAME transaction as the invitations update.

4. Tests: happy path; expired token rejected; already-used token rejected; mismatched email
   rejected; and a concurrency test firing two simultaneous `accept` calls with the same valid raw
   token, asserting exactly one succeeds and the other gets the generic error, not a 500.

Show me the full diff and test output.
```

**Expected Output**: An invitation-only registration path with no public sign-up route at all, a
provably single-use accept flow under concurrency, and a uniform error message that doesn't leak
which failure mode occurred.

**Notes**: If the agent's first draft returns different error messages for "expired" vs
"already used," that's an information-disclosure regression against system_architecture.md §7 —
send it back rather than accepting it as a minor detail.

---

### PROMPT 7: Server-Side Attendance Engine
**Purpose**: Implement clock-in/clock-out recording per system_architecture.md §6, where the server clock — never the client — is authoritative.

**Prompt**:
```
Read system_architecture.md §6 before starting.

Build, in `src/modules/attendance/`:

1. `clock_events` table: id, organization_id, employee_id, event_type TEXT ('clock_in' |
   'clock_out'), recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(), client_reported_at TIMESTAMPTZ
   (nullable, diagnostic-only field for measuring client clock skew — never used for anything
   authoritative), created_at TIMESTAMPTZ NOT NULL DEFAULT now(). RLS enabled/forced per Prompt 4's
   pattern.

2. `employees.timezone`: add server-side validation (on employee create/update) that the supplied
   string is a real IANA timezone — reject the request with a 422 if `zoneinfo.ZoneInfo(tz)` raises.

3. `POST /attendance/clock-in` and `POST /attendance/clock-out`: the request body may optionally
   include a client-reported timestamp for skew diagnostics ONLY — the endpoint must ignore it for
   the actual `recorded_at` value, which is always the database's `now()` at insert time (do not
   even accept a `recorded_at` field from the client; only accept `client_reported_at`, named
   differently on purpose so there's no ambiguity in the code about which one is authoritative).
   Enforce that clock-in/clock-out alternate correctly (cannot clock in twice without clocking out
   in between) via a check against the employee's most recent event.

4. `GET /attendance/history?employee_id=&from=&to=`: returns events with `recorded_at` converted to
   the employee's local time via `recorded_at AT TIME ZONE employees.timezone` at query time (not
   stored pre-converted), alongside the raw UTC value.

5. Tests: clock-in then clock-out succeeds; clocking in twice in a row without clocking out is
   rejected; a `client_reported_at` that's wildly different from server time does not affect the
   stored `recorded_at`; timezone conversion in the history endpoint is correct for at least two
   different IANA zones including one with a non-whole-hour offset (e.g., `Asia/Kolkata`,
   UTC+5:30) to catch any lazy whole-hour-only conversion bugs.

Paste the diff and test output.
```

**Expected Output**: An attendance API where server time is unambiguously authoritative, correct
timezone-aware reporting, and tests that specifically probe the "trust the server, not the client"
invariant rather than only testing the happy path.

**Notes**: The half-hour-offset timezone test is the one most likely to catch a shortcut
implementation — insist on it even if the agent's first draft "passes" without it.

---

### PROMPT 8: Leave Scheduler with Exclusion Constraints
**Purpose**: Implement the leave-request system with database-enforced overlap protection, per system_architecture.md §4.3. This is one of the harder tasks in the project — treat it accordingly.

**Prompt**:
```
Read system_architecture.md §4.3 in full and AGENT.md Prime Directive #3 before starting. The
authority for overlap prevention is a PostgreSQL EXCLUDE constraint, not Python logic — any
Python-side overlap check you write is UX sugar only and must be clearly commented as such.

Build, in `src/modules/leave/`:

1. Migration creating `leave_requests` EXACTLY as specified in system_architecture.md §4.3:
   ```sql
   CREATE EXTENSION IF NOT EXISTS btree_gist;

   CREATE TABLE leave_requests (
       id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       organization_id  UUID NOT NULL REFERENCES organizations(id),
       employee_id      UUID NOT NULL REFERENCES employees(id),
       start_time       TIMESTAMPTZ NOT NULL,
       end_time         TIMESTAMPTZ NOT NULL,
       status           TEXT NOT NULL DEFAULT 'pending',
       period           TSTZRANGE GENERATED ALWAYS AS (tstzrange(start_time, end_time, '[]')) STORED,
       created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
       CONSTRAINT valid_leave_range CHECK (end_time > start_time)
   );

   ALTER TABLE leave_requests ENABLE ROW LEVEL SECURITY;
   ALTER TABLE leave_requests FORCE ROW LEVEL SECURITY;
   CREATE POLICY tenant_isolation_leave_requests ON leave_requests
       USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
       WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid);

   ALTER TABLE leave_requests
       ADD CONSTRAINT no_overlapping_active_leave
       EXCLUDE USING gist (
           employee_id WITH =,
           period WITH &&
       ) WHERE (status IN ('pending', 'approved'));
   ```

2. `POST /leave-requests`: attempt the insert directly. Catch the Postgres `exclusion_violation`
   (SQLSTATE `23P01`) specifically and map it to a `409 Conflict` with a message naming the
   conflicting date range if you can retrieve it cheaply; do not pre-query for overlaps as the
   primary check and skip the insert-time handling — the insert attempt itself IS the check.
   You may add a cheap pre-query purely to return a friendlier error before hitting the DB, but the
   409-on-`23P01` handling must exist regardless and must be what the tests actually exercise.

3. `PATCH /leave-requests/{{id}}/approve` and `.../reject`: plain status updates. Explain in a code
   comment why a rejected request no longer blocks new overlapping requests (the partial WHERE
   clause on the exclusion constraint).

4. Tests — this is the important part:
   - Sequential: request A (Mon–Wed) succeeds; request B (Tue–Thu, same employee) fails with 409.
   - Non-overlapping: request A (Mon–Wed) and request B (Thu–Fri) both succeed.
   - Different employees, same dates: both succeed (constraint is scoped by `employee_id`).
   - Rejected requests don't block: reject request A, then request B (Tue–Thu) succeeds.
   - **Concurrency test (mandatory, do not skip)**: using `asyncio.gather` (or equivalent),
     fire two overlapping insert attempts for the same employee at effectively the same instant and
     assert exactly one succeeds and the other raises the mapped 409 — this is the test that
     actually proves the race condition is closed at the database level, not just that sequential
     requests behave.

Paste the migration, endpoint code, and full test output — especially the concurrency test.
```

**Expected Output**: A working leave-request API where the exclusion constraint, not application
logic, is what a concurrency test actually observes preventing a double-booking.

**Notes**: If the agent's concurrency test "passes" without ever actually triggering a
`23P01` (e.g., because the two inserts accidentally ran sequentially due to connection pooling or
test setup), that's a false-positive test — check the test actually forces true concurrency (e.g.,
two separate connections/sessions, started before either commits) before accepting it.

---

### PROMPT 9: Temporal Rule Engine & Payroll Ledger
**Purpose**: Implement the immutable payroll ledger and the temporal rule engine that computes back-dated adjustments, per system_architecture.md §4.4. The most complex feature in the project — expect this prompt to take multiple iterations.

**Prompt**:
```
Read system_architecture.md §4.4 in full and AGENT.md Prime Directive #4 before starting.

Build, in `src/modules/payroll/`:

1. Migrations creating `payroll_rules` and `payroll_ledger_lines` exactly as specified in
   system_architecture.md §4.4, including the `prevent_closed_ledger_mutation()` trigger function
   and its `BEFORE UPDATE OR DELETE` trigger on `payroll_ledger_lines`. RLS enabled/forced on both
   tables per the standard pattern.

2. A `PayrollRuleResolver` service: given `organization_id`, `rule_type`, `rule_key`, and an
   `as_of: date`, returns the single rule row where `valid_from <= as_of AND (valid_to IS NULL OR
   valid_to > as_of)`. Add a unique partial index or a check to make this resolution unambiguous —
   tell me how you're preventing two overlapping-validity rules for the same
   `(organization_id, rule_type, rule_key)` from both existing at once (this is the payroll
   equivalent of the leave-overlap problem — consider whether an exclusion constraint belongs here
   too, and justify your choice either way).

3. `POST /payroll/close-month`: given `organization_id` and `ledger_month`, sets
   `status = 'closed', closed_at = now()` on all currently-open lines for that month. This is the
   ONLY code path allowed to set a line's status to closed. After this runs, the trigger from
   step 1 makes those rows physically un-mutable.

4. `POST /payroll/adjustments`: given `{{original_line_id}}` and a reason, the service must:
   a. Look up the original line (must be `status = 'closed'` — adjustments only make sense against
      closed history; adjusting an open line should just be a normal update instead, reject
      otherwise).
   b. Re-resolve, via `PayrollRuleResolver`, the rule(s) that were valid as of the ORIGINAL line's
      `ledger_month` (not today's rules).
   c. Recompute what the correct amount would have been under those rules, diff against the
      original line's `amount_cents`, and INSERT a new row in the CURRENT open month with
      `line_type = 'adjustment'`, `amount_cents = <delta>`, `adjustment_of = original_line_id`.
   d. Never touch the original row. Prove this with a test that hashes/checksums the original row's
      full column set before and after the adjustment call and asserts byte-for-byte equality.

5. Tests: closing a month, then attempting a direct `UPDATE` against a closed line and asserting
   the trigger raises; an adjustment against a rule that has since changed, proving the
   recomputation used the OLD rule (construct a test where the current rule and the as-of-March
   rule produce different numbers, and assert the adjustment matches the March number, not
   today's); the checksum-equality test from 4d.

Paste all migrations, service code, and test output, especially the "old rule was used, not
today's rule" test — that's the one most likely to be silently wrong if the resolver's `as_of`
logic has an off-by-one on the boundary dates.
```

**Expected Output**: An append-only payroll ledger with a database-enforced immutability guarantee,
a temporal rule resolver with an explicit, justified answer to how overlapping rule validity is
prevented, and a test suite that specifically proves historical recomputation uses the
period-appropriate rule rather than the current one.

**Notes**: This is the single most likely feature to get subtly wrong (boundary conditions on
`valid_from`/`valid_to`, and forgetting that "closed" should block updates AND deletes). Budget for
at least one review-and-revise round after the first draft; don't treat the first green test run as
sufficient without inspecting the boundary-date test specifically.

---

### PROMPT 10: GDPR Pseudonymization Pipeline
**Purpose**: Implement the right-to-be-forgotten offboarding pipeline per system_architecture.md §4.5. Depends on employees already having a soft-delete/termination flow.

**Prompt**:
```
Read system_architecture.md §4.5 in full and AGENT.md Prime Directive #5 before starting.
Note the explicit design decision documented there: the HMAC pepper lives in a secrets manager,
never in the database; only the resulting hash is persisted. Build against that interpretation, and
flag clearly in your response if you think a different reading is more correct so a human can
confirm.

Build, in `src/modules/offboarding/`:

1. First, if it doesn't already exist: a termination flow — `POST /employees/{{id}}/terminate` sets
   `status = 'terminated', deleted_at = now()` on the employees row (soft-delete, per Prime
   Directive #5). This must exist and be enforced BEFORE pseudonymization can ever run — add a
   guard that rejects a pseudonymization request against an employee who is not already terminated.

2. `pseudonymization_map` table exactly as specified in system_architecture.md §4.5.

3. A `PseudonymizationService`:
   a. Fetches the pepper from the configured secrets source (stub this behind an interface —
      `SecretsProvider.get("pseudonymization_pepper")` — with a local-dev implementation reading
      from an env var, clearly commented that production must swap this for a real secrets-manager
      client).
   b. Computes `hash = hmac.new(pepper, employee_id.bytes, hashlib.sha256).hexdigest()`.
   c. In a single transaction: inserts the `pseudonymization_map` row; updates the `employees` row
      to redact `full_name` and `email` (define exactly what "redacted" means — e.g.,
      `full_name = 'Deleted User'`, `email = NULL`); updates any high-entropy descriptive fields on
      historical `clock_events`/`leave_requests`/`payroll_ledger_lines` rows tied to this employee
      to roll up into a `structural_cohort` string (e.g., derived from the employee's department +
      region at time of termination) — and explicitly does NOT touch `amount_cents` or any other
      numeric field on those historical rows.
   d. Is idempotent — calling it twice for the same employee should not error or double-insert; the
      second call should be a no-op (check `pseudonymization_map` first).

4. `POST /offboarding/{{employee_id}}/forget`: admin- or employee-triggered endpoint invoking the
   service above.

5. Tests: pseudonymizing a non-terminated employee is rejected; after pseudonymization, a query for
   the original name/email returns nothing recognizable; SUM(amount_cents) grouped by
   structural_cohort across the employee's payroll_ledger_lines is IDENTICAL before and after
   pseudonymization (this is the test that actually proves "mathematical integrity" was preserved,
   not just that the pipeline ran without error); calling the endpoint twice is idempotent.

Paste the service code and test output, especially the SUM-equality test.
```

**Expected Output**: A pseudonymization pipeline that is idempotent, gated behind prior termination,
and provably preserves aggregate payroll math while destroying re-identifiable fields.

**Notes**: Watch for an agent that pseudonymizes by deleting historical rows instead of rolling up
fields on them — that would break the "preserve structural integrity" requirement even though it
also "removes the identifying data." Deletion of historical financial rows is never correct here.

---

### PROMPT 11: Sandboxed Automation & Scraping Ingress
**Purpose**: Build the isolated Crawl4AI/Playwright automation service and its signed-callback communication path back into the API, per system_architecture.md §8.

**Prompt**:
```
Read system_architecture.md §8 in full and AGENT.md Prime Directive #6 before starting. The
automation service and the API must remain two genuinely separate deployable units with no shared
database credentials — do not take a shortcut where the automation container imports API code that
happens to include a DB session.

Part A — in `apps/automation/` (its own `pyproject.toml`, its own `uv.lock`, isolated from
`apps/api`):
1. A Celery worker that consumes a `run_automation_job` task with payload `{job_id: str, target_url:
   str, extraction_type: str}`.
2. Using Crawl4AI/Playwright, perform the extraction (start with a simple, safe placeholder
   extraction — e.g., page title + visible text — since the specific corporate-verification logic
   is a separate concern to design later).
3. POST the result to `{{API_INTERNAL_BASE_URL}}/internal/automation/callback` with body
   `{job_id, extracted_text, issued_at}` and a header `X-Signature` computed as
   `hmac.new(shared_secret, raw_request_body_bytes, hashlib.sha256).hexdigest()`. The shared secret
   comes from env/secrets, identical to what the API side expects — do not derive it independently
   on each side.

Part B — in `apps/api/src/modules/automation_ingress/`:
1. An `automation_jobs` table: id, organization_id, status ('queued'|'processing'|'completed'|
   'failed'), target_url, extraction_type, result_text (nullable), created_at, completed_at. RLS
   enabled/forced per the standard pattern.
2. `POST /automation-jobs` (internal admin trigger): creates the job row with `status='queued'`,
   enqueues the Celery task with just `job_id` (and whatever non-sensitive params the task needs) —
   never put `organization_id` inside the payload sent to the automation container as something it
   echoes back; the callback handler must look it up itself from the job row.
3. `POST /internal/automation/callback` (not exposed through the public router prefix used by the
   two frontends — mount it separately):
   a. Recompute the HMAC over the raw request body using the shared secret; reject with 401 on any
      mismatch, using a constant-time comparison (`hmac.compare_digest`).
   b. Reject if `issued_at` is older than a configurable replay window (default 5 minutes).
   c. Look up `automation_jobs` by `job_id` to get `organization_id` — this, not any field in the
      request body, is the tenant context used to write the result. Explicitly show in code review
      that the body's own claims about tenant are never trusted.
   d. Update the job row with the result and `status='completed'` inside a tenant-scoped session
      per system_architecture.md §3.

4. Tests: valid signature accepted; tampered body rejected even with a copied-looking signature;
   stale `issued_at` rejected even with a valid signature; a job's result lands in the correct
   organization's data regardless of what (if anything) the callback body claims about org identity.

Paste the Part A and Part B code and full test output, and confirm explicitly: does the
`apps/automation` service have ANY database or Redis connection string in its configuration? It
should not.
```

**Expected Output**: Two genuinely separate services communicating only over one signed HTTP
callback, with tests proving signature verification, replay protection, and tenant-context
re-derivation all function independently of anything the untrusted callback body claims.

**Notes**: The explicit closing question ("does the automation service have any DB/Redis
connection string?") is there on purpose — it's the single fastest way to catch an agent that took
a shortcut and gave the "isolated" service direct data access anyway.

---

## Group C — Frontend

### PROMPT 12: Employee Self-Service Portal — Core Screens
**Purpose**: Build the primary employee-facing screens against the API modules already built in Group B. Run after Prompts 5–8 exist.

**Prompt**:
```
Working in `apps/web-employee`. Read AGENT.md §7 (Frontend Coding Conventions) before starting.
The API is already implemented per Prompts 5 (auth), 7 (attendance), and 8 (leave) — read their
resulting OpenAPI schema at `{{API_BASE_URL}}/openapi.json` and generate types into
`packages/shared-types` before writing any component code, rather than hand-typing request/response
shapes.

Build these screens, one at a time, each with its own feature folder per AGENT.md §7:

1. `features/auth/`: login screen. On success, store the access token in memory (a simple module
   or a lightweight state store — do not use localStorage/sessionStorage for it) and redirect to
   the dashboard. Wire this against the shared Axios client that Prompt 14 will define — if Prompt
   14 hasn't run yet, stub a minimal client here and flag that it needs to be replaced once Prompt
   14 lands, rather than building two divergent HTTP client setups.

2. `features/attendance/`: a dashboard showing current clock-in/out status and a single prominent
   button that toggles state (Clock In / Clock Out), calling the attendance endpoints. Show the
   employee's attendance history for the last 14 days in their local timezone (using the value the
   API already converts server-side — do not re-implement timezone math on the frontend).

3. `features/leave/`: a form to request leave (date range picker), submitting to
   `POST /leave-requests`. On a 409 response, show the specific "these dates conflict with an
   existing request" message rather than a generic error. A list view of the employee's own past
   and pending requests with status badges.

For each screen, write a component test (React Testing Library) covering: the happy path, and the
409-conflict-message case for the leave form specifically (since that's the one place a
generic-error fallback would hide a real, important signal from the user).

Show me each screen's code and its test output before moving to the next one.
```

**Expected Output**: Three working feature folders, type-safe against the generated OpenAPI client,
with the 409-specific leave-conflict UX explicitly tested, not just visually eyeballed.

**Notes**: If Prompt 14 hasn't been run yet when this one is, expect to revisit the auth wiring
once it has — say so explicitly rather than letting two different HTTP client patterns coexist
long-term.

---

### PROMPT 13: Admin/HR Control Center — Core Screens
**Purpose**: Build the primary admin-facing screens: org/employee management, invitations, and payroll oversight. Run after Prompts 5, 6, 9, and 10 exist.

**Prompt**:
```
Working in `apps/web-admin`. Read AGENT.md §7 before starting, and confirm the generated OpenAPI
types in `packages/shared-types` are current for the invitation, payroll, and offboarding modules —
regenerate them if the schema has changed since Prompt 12 last ran.

Build these screens:

1. `features/invitations/`: a form to issue a new invitation (email, role), calling
   `POST /invitations`. A table of pending/expired/used invitations for the organization,
   reflecting `status` derived client-side from `used_at`/`expires_at` (do not add a redundant
   status field on the frontend that could drift from those two source-of-truth timestamps).

2. `features/employees/`: a table of the organization's employees with a "Terminate" action calling
   the termination endpoint, and — for a terminated employee — a clearly separated, visually
   distinct "Process Right-to-be-Forgotten Request" action calling the offboarding endpoint from
   Prompt 10. This second action must require an explicit confirmation dialog stating that it is
   irreversible, since AGENT.md Prime Directive #5 makes this a one-way operation.

3. `features/payroll/`: a view of an employee's ledger lines for a given month, clearly
   distinguishing `open` vs `closed` status, with a "Record Adjustment" action available only on
   closed-month lines (disable/hide it for open lines, since adjusting an open line should go
   through a normal edit path instead, not the adjustment endpoint). A "Close Month" action for
   admins with a confirmation dialog.

For each screen, write a test asserting the irreversible actions (terminate → forget, close month)
require confirmation before the underlying API call fires — simulate a user dismissing the
confirmation dialog and assert the API was NOT called.

Show me each screen's code and test output.
```

**Expected Output**: Admin screens where every irreversible action is gated behind an explicit
confirmation, tested by simulating dismissal and asserting no API call occurred.

**Notes**: The "dismiss the dialog, assert no API call" test is the one most likely to be skipped in
favor of "assert the dialog renders" — insist on the stronger version, since it's what actually
prevents an accidental irreversible action.

---

### PROMPT 14: Secure Axios Interceptor for Cookie-Refresh Loop
**Purpose**: Build the single shared HTTP client module (per system_architecture.md §9) used by both frontend apps, handling silent token refresh without duplicating logic or racing concurrent refresh attempts.

**Prompt**:
```
Read system_architecture.md §9 in full before starting. This module will be duplicated (not
imported as a shared package, unless you set up `packages/shared-types` or a new
`packages/api-client` to actually be consumed by both Vite apps — tell me which approach you're
taking and why) into both `apps/web-employee/src/lib/apiClient.ts` and
`apps/web-admin/src/lib/apiClient.ts`, and both copies must stay behaviorally identical.

Requirements:
1. A single Axios instance with `withCredentials: true` (so the HttpOnly refresh cookie is sent
   automatically) and `baseURL` from an environment variable.
2. Access token held in a module-level variable (not React state, not localStorage), with a setter
   called after login and after every successful refresh.
3. A response interceptor: on a 401 response (and only on 401 — not on other 4xx/5xx), attempt a
   silent refresh via `POST /auth/refresh`. While a refresh is already in flight, ANY other request
   that also receives a 401 must await the SAME in-flight refresh promise rather than each firing
   its own `POST /auth/refresh` — implement this with a shared, nulled-out-after-resolution promise
   variable, and write a test proving that three simultaneous 401s result in exactly one
   `POST /auth/refresh` call, not three.
4. On successful refresh, retry the original failed request(s) exactly once with the new access
   token. On refresh failure (itself a 401, meaning the refresh token is also invalid/expired),
   clear the in-memory access token and redirect to `/login` — do not retry again, and do not loop.
5. A test proving a request that fails with a 401 even after a successful refresh (e.g., the access
   token was valid for refresh purposes but the specific resource now returns 403 for a role
   reason) does NOT trigger an infinite refresh loop — it should surface as a normal error after the
   single retry.

Write this once in `apps/web-employee`, get it fully working and tested, then copy it verbatim
(only changing anything genuinely app-specific, like error-toast wiring) into `apps/web-admin` and
run the same test suite there too.
```

**Expected Output**: An interceptor module, proven by test to coalesce concurrent 401s into a
single refresh call, retry exactly once, and fail safely (redirect, no loop) when refresh itself
fails — identical behavior in both frontend apps.

**Notes**: The "three concurrent 401s → one refresh call" test is the single most important
assertion here; a naive interceptor implementation almost always fails this on the first attempt by
firing a separate refresh per failed request, which can invalidate the very refresh token another
in-flight request is about to use.

---

## Group D — Testing

### PROMPT 15: Unit & Integration Test Suite Generation (Reusable)
**Purpose**: A general-purpose prompt to generate a thorough test suite for any backend module after its implementation lands, when the feature-specific prompts above (5–11) haven't already fully specified the test list. Use this to fill gaps or to test a module not covered by a dedicated prompt.

**Prompt**:
```
Read AGENT.md §10 (Testing Bar) before starting. I've just implemented (or am about to review)
`{{MODULE_PATH}}`, which does: {{ONE_SENTENCE_DESCRIPTION_OF_MODULE_RESPONSIBILITY}}.

Generate a test suite covering, at minimum:
1. The happy path for every public function/endpoint in this module.
2. Every explicit validation error the module can raise (list them from the code, don't guess) —
   one test per distinct error condition, asserting the correct status code / exception type.
3. At least one adversarial case per AGENT.md Prime Directive this module touches — name which
   directive(s) apply before writing the test (e.g., if this module writes to a tenant-scoped
   table, there must be a cross-tenant isolation test even if Prompt 16's full suite will also
   cover it generally).
4. Boundary conditions on any date/time range, numeric threshold, or pagination limit present in
   the module.
5. Idempotency: if an operation is meant to be safely retryable (e.g., anything triggered by a
   Celery task, which may redeliver), test that calling it twice with the same input doesn't
   double-apply an effect.

For each test, the test name should describe the behavior being proven, not the implementation
detail (`test_rejects_expired_invitation`, not `test_accept_endpoint_case_3`).

After generating the tests, run them and paste the output. If any fail against the current
implementation, do not "fix the test to match the bug" — tell me which is wrong, the test's
expectation or the code, and wait for my confirmation before changing either.
```

**Expected Output**: A test file with clearly named test functions covering happy paths, validation
errors, directive-specific adversarial cases, boundaries, and idempotency, plus an honest report of
any failures found rather than a suite silently adjusted to match buggy behavior.

**Notes**: The last instruction (don't quietly "fix" a failing test to match the code) is the most
important part of this prompt — without it, an agent under implicit pressure to show green tests
will sometimes weaken an assertion instead of surfacing a real bug.

---

### PROMPT 16: RLS Adversarial Test Suite (Full Sweep)
**Purpose**: Build (or extend, table by table) the comprehensive cross-tenant isolation test suite that is the actual proof behind Prime Directive #1. Run once to establish the suite, then re-run per new table per Prompt 4.

**Prompt**:
```
Read system_architecture.md §4.2 and AGENT.md Prime Directive #1 before starting. Your job is to
try to break tenant isolation, not to confirm it looks fine.

For EVERY table in the schema carrying `organization_id` (enumerate them by inspecting the ORM
models — list the tables you found before writing any tests), write, in
`src/tests/test_rls_adversarial.py`:

1. **Read isolation**: insert a row as Org A (real tenant-scoped session with `SET LOCAL
   app.current_organization_id` set to Org A). Open a fresh session as Org B. Assert a plain
   `SELECT *` from Org B's session returns zero rows referencing Org A's data, even when queried by
   the Org A row's known primary key directly (`WHERE id = '<org_a_row_id>'`) — this specifically
   catches a policy that only filters list queries but not point lookups.
2. **Write isolation**: as Org B's session, attempt an `INSERT` supplying Org A's `organization_id`
   explicitly in the values. Assert this is rejected by the `WITH CHECK` clause (a Postgres
   `insufficient_privilege`/policy violation), not merely "succeeds but is invisible later."
3. **Update isolation**: as Org B's session, attempt to `UPDATE` a row that (if RLS were absent)
   exists with Org A's `organization_id`, targeting it by its known primary key. Assert zero rows
   affected (RLS makes it invisible to the UPDATE's WHERE-matching, not merely "not allowed").
4. **No-tenant-context fail-closed check**: open a raw session and run a query against this table
   WITHOUT ever calling `SET LOCAL app.current_organization_id`. Assert zero rows are returned
   (proving the `current_setting(..., true)` NULL-fallback in system_architecture.md §4.2 fails
   closed rather than accidentally returning everything).
5. **ORM-shortcut check**: if the codebase has any raw/bypass query path (e.g., a raw SQL admin
   tool, a bulk-import script, a platform-superadmin dependency), test that path too — RLS applies
   to it exactly as much as to normal request-scoped code UNLESS it explicitly uses the separate
   `get_platform_db`-style dependency called out in system_architecture.md §3, which must itself be
   tested for requiring an explicit elevated role check.

Run the suite and paste full output, including the list of tables you enumerated at the start, so I
can independently confirm none were missed.
```

**Expected Output**: A test file with (read/write/update/fail-closed/bypass-path) tests for every
tenant-scoped table, an explicit enumerated table list to cross-check against the actual schema, and
a passing run proving each isolation property empirically rather than by code inspection alone.

**Notes**: The point-lookup-by-known-primary-key variant of the read test is the one most likely to
be skipped in a lazy first draft (it's easy to only test list endpoints) — insist on it, since it's
also the most realistic version of an actual cross-tenant leak (an ID guessed or leaked from a log,
then queried directly).

---

### PROMPT 17: Concurrency / Race-Condition Test Pass
**Purpose**: A focused, reusable prompt for stress-testing every place in the system where two concurrent requests could otherwise create an inconsistent state — leave overlaps, invitation single-use, refresh-token rotation, and any future case with the same shape.

**Prompt**:
```
Read AGENT.md Prime Directives #3 and the general "database is the authority, not application
logic" theme running through system_architecture.md before starting.

Audit the codebase for every operation that (a) checks a condition, then (b) writes, where two
concurrent requests could both pass the check before either commits. For each one you find,
including but not limited to:
- Leave request overlap (Prompt 8)
- Invitation/refresh-token single-use claims (Prompts 5, 6)
- {{ANY_OTHER_CHECK_THEN_WRITE_PATTERN_YOU_HAVE_ADDED_SINCE}}

Confirm the actual enforcement is a database-level constraint or a conditional
`UPDATE ... WHERE <not-yet-claimed> RETURNING id` pattern — not a read-then-write race in
application code — and if you find one that IS just a read-then-write race, do not fix it silently;
report it first, since the fix might need a schema change (a new constraint) rather than a pure code
change.

For each confirmed-safe pattern, write (or verify the existence of) a genuine concurrency test using
real parallel execution — `asyncio.gather` over two independent DB sessions/connections started
before either commits, not two sequential awaited calls that merely look concurrent in the test
code. State explicitly, for each test, why you're confident it exercises a true race rather than an
accidentally-sequential one (e.g., "both sessions began their transaction and issued their insert
before either received a response, confirmed via a short artificial delay inserted only in the
test").

Report back: a list of every check-then-write pattern found, which ones are already safe (with test
names), which ones are unsafe and need a schema-level fix, and — for unsafe ones — a proposed fix
for me to review before you implement it.
```

**Expected Output**: An audit report enumerating every check-then-write pattern in the codebase,
test coverage (or a flagged gap) for each, and a clear separation between "already safe, here's the
proof" and "unsafe, here's my proposed fix, awaiting approval."

**Notes**: Run this prompt periodically as the codebase grows (e.g., before each release), not just
once — new check-then-write patterns are easy to introduce accidentally in unrelated feature work.

---

## Group E — Debugging & Review

### PROMPT 18: Systematic Debugging Prompt (Reusable)
**Purpose**: The default prompt for any bug report, from either automated test failure or a user-reported issue, to keep debugging structured rather than trial-and-error patching.

**Prompt**:
```
I have a bug. Do not attempt a fix until you've completed steps 1–3 below, in order.

Bug report: {{PASTE_BUG_DESCRIPTION_OR_FAILING_TEST_OUTPUT_OR_ERROR_LOG_HERE}}
Where it was observed: {{ENDPOINT_OR_SCREEN_OR_JOB_NAME}}
Steps to reproduce (if known): {{STEPS_OR_"UNKNOWN"}}

1. **Reproduce it.** Write the smallest possible failing test that demonstrates this bug against
   the current code, and run it to confirm it actually fails for the reason described (not for some
   unrelated setup issue). Paste the failing output.
2. **Localize it.** Trace the failure to the specific function/query/component responsible. State
   your hypothesis for the root cause explicitly, in one or two sentences, before writing any fix.
   If the bug could plausibly involve a violated invariant from AGENT.md §2 (tenant isolation,
   session revocation, leave overlap, payroll immutability, GDPR pseudonymization, or automation
   sandboxing), say so explicitly and treat the fix with the corresponding extra scrutiny — a bug in
   one of these areas is a security/compliance issue, not just a functional one.
3. **Fix it.** Implement the minimal correct fix. Do not silently refactor unrelated code in the
   same change. If the "correct" fix is larger than the reported bug warrants (e.g., it reveals a
   deeper design issue), implement the minimal safe fix for the reported bug now and separately
   propose the larger fix as its own follow-up rather than expanding scope silently.
4. **Prove it.** Re-run the failing test from step 1 and confirm it now passes, then run the full
   relevant test file (not just the one new test) to confirm nothing else broke.
5. **Prevent recurrence.** If this bug reveals a gap in the general test suites from Prompts 15–17
   (e.g., a check-then-write race that wasn't covered), say so and propose adding it there, not just
   in this one-off test.

Report back following exactly this structure: Hypothesis → Fix → Proof → Suggested suite additions.
```

**Expected Output**: A reproduction test, a stated root-cause hypothesis, a scoped fix, a proof that
the specific bug and the surrounding test suite both pass, and — where relevant — a flagged
connection to one of the six Prime Directives plus a suggestion for the general test suites.

**Notes**: If the agent jumps straight to "fixed it" without a reproduction step, the response is
incomplete even if the fix happens to be correct — send it back for the reproduction test
specifically, since that's what proves the bug was understood rather than guessed at.

---

### PROMPT 19: Code Review Prompt (Reusable, Security-Focused)
**Purpose**: Run against any non-trivial PR/diff before merge, especially anything touching a Prime Directive area.

**Prompt**:
```
Review the following diff as a senior engineer on this project would, with AGENT.md and
system_architecture.md as your standard of correctness — not general best practices in the
abstract, but specifically whether this diff upholds every Prime Directive in AGENT.md §2 that it
touches.

Diff / PR description:
{{PASTE_DIFF_OR_LINK_TO_PR_HERE}}

Go through this checklist explicitly, answering each with evidence from the diff (a line reference
or a quoted snippet), not just "looks fine":

1. Does this diff touch any tenant-scoped table? If so, does the RLS policy already exist for it,
   or does this diff add/modify one? Confirm the migration and policy ship together if new.
2. Does this diff introduce any check-then-write pattern (see Prompt 17)? If so, is the actual
   enforcement a DB constraint/conditional update, or a race-prone application-level check?
3. Does this diff touch anything payroll-related? If so, does it ever `UPDATE`/`DELETE` a row that
   could be `status='closed'`, even conditionally or via an ORM cascade the author might not have
   noticed?
4. Does this diff touch employee deletion/offboarding? Confirm it's a soft-delete/pseudonymization
   path, never a hard `DELETE`.
5. Does this diff touch anything communicating with the automation sandbox? If so, confirm the
   tenant context is re-derived from a server-side record, never trusted from the untrusted
   payload, and confirm the HMAC verification uses a constant-time comparison.
6. Are there any new secrets, and are they read from config/secrets-management rather than
   hardcoded or logged?
7. Is test coverage proportionate to risk — i.e., does a change to a Prime-Directive-adjacent area
   have an adversarial test, not just a happy-path one?
8. General code quality: naming, layering (router/service/repository per AGENT.md §6), and whether
   error handling swallows exceptions silently.

Conclude with a clear verdict: **Approve**, **Approve with minor comments**, or **Request changes**,
and if the latter, an itemized list of what must change before this can merge — distinguish clearly
between "must fix" and "consider for later."
```

**Expected Output**: A structured review walking through all eight checklist items with specific
evidence, ending in an unambiguous verdict and, if changes are requested, a prioritized list.

**Notes**: A review that answers every checklist item with a generic "looks good" instead of citing
specific lines/snippets has not actually done the review — treat that as a sign to re-run the prompt
more narrowly (e.g., paste smaller diff chunks) rather than accepting a rubber-stamp response.

---

## Group F — Documentation

### PROMPT 20: API Documentation & README Generation
**Purpose**: Generate developer-facing documentation once a module (or the whole API) has stabilized enough to document. Run per-module after its feature prompt (5–11) is complete, and once at the end for the top-level README.

**Prompt**:
```
Read the implemented code in `{{MODULE_PATH}}` (do not guess at behavior from the prompt that
originally created it — the implementation is the source of truth, and it may have evolved since).

1. Enrich the FastAPI route definitions with docstrings and `response_model`/`status_code`
   annotations wherever missing, so the auto-generated OpenAPI schema at `/openapi.json` accurately
   documents every endpoint's request/response shape and possible error status codes — do not hand
   write a separate API reference document that could drift from the code; the OpenAPI schema
   generated from the code IS the reference.
2. Write or update `{{MODULE_PATH}}/README.md` covering: what this module owns, which Prime
   Directive(s) from AGENT.md it's responsible for upholding, its main entry points (endpoints or
   Celery tasks), and any non-obvious operational detail (e.g., "adjustments only apply to closed
   months; see system_architecture.md §4.4 for why").
3. If this is the final documentation pass for the whole project, also update the root `README.md`
   with: a project overview (2–3 paragraphs, not a restatement of the entire architecture doc),
   local dev setup steps (should match AGENT.md §5 exactly — if they've diverged, fix whichever one
   is stale), and a pointer to `AGENT.md` and `system_architecture.md` as the canonical references
   for contributors and coding agents.

Do not duplicate content that already lives in AGENT.md or system_architecture.md — link to the
relevant section instead of restating it, so there's a single source of truth per topic.
```

**Expected Output**: An accurate, current OpenAPI schema, a per-module README explaining ownership
and operational quirks without restating the architecture doc, and (on the final pass) a concise
root README pointing to the two canonical documents.

**Notes**: Watch for documentation drift — if the agent documents behavior that doesn't match what
Prompt 15/16's tests actually assert, that's a signal either the docs or the tests (or the code) are
wrong; resolve the discrepancy rather than documenting the bug as if it were intended behavior.

---

### PROMPT 21: Architecture Decision Record (ADR) Generator
**Purpose**: Produce a durable, dated record whenever a non-trivial design choice is made or changed during implementation — especially resolutions to the "Open Design Decisions" flagged in system_architecture.md §13, or any deviation from this document discovered necessary during implementation.

**Prompt**:
```
We just made (or need to make) a design decision that isn't fully settled in system_architecture.md,
or that deviates from what it currently says.

Context: {{DESCRIBE_THE_SITUATION_AND_WHY_THE_EXISTING_DOC_DOESN'T_ALREADY_COVER_IT}}
Options considered: {{LIST_THE_ALTERNATIVES_YOU_SAW}}
Decision (if already made) or recommendation (if you're asking me to decide): {{FILL_IN_OR_LEAVE_FOR_AGENT_TO_PROPOSE}}

Write an ADR as a new file `docs/adr/{{NNNN}}-{{short-slug}}.md` using this structure:
- **Status**: Proposed | Accepted | Superseded by ADR-XXXX
- **Context**: what prompted this decision, in enough detail that someone with no memory of this
  conversation understands the problem.
- **Decision**: the specific choice made, stated unambiguously.
- **Consequences**: what this makes easier, what it makes harder, and any Prime Directive or
  existing architecture-doc section it interacts with.
- **Alternatives considered**: briefly, why each was not chosen.

After writing the ADR, tell me explicitly whether `system_architecture.md` itself needs a
corresponding edit (e.g., resolving one of its §13 "Open Design Decisions," or noting a deviation) —
if so, propose the specific diff to that file rather than letting the ADR and the architecture doc
silently disagree with each other.
```

**Expected Output**: A well-formed ADR file plus an explicit proposed edit to
`system_architecture.md` if the decision affects something that document already asserts, so the two
never silently drift apart.

**Notes**: Use this prompt every time an implementation prompt (Group B) surfaces a judgment call
that wasn't already pinned down — accumulating these keeps the architecture doc from going stale as
the single source of truth.

---

## Group G — Deployment & Operations

### PROMPT 22: CI/CD Pipeline Setup
**Purpose**: Build the automated pipeline that runs the test suites from Group D on every PR, before any deployment automation exists.

**Prompt**:
```
Read AGENT.md §10 (Testing Bar) and §11 (Git/PR workflow) before starting.

Create `.github/workflows/ci.yml` with these jobs, running on every PR against `main`:
1. `backend-checks`: spin up Postgres 16 (with `btree_gist`/`citext`/`pgcrypto` available) and
   Redis 7 as service containers, `uv sync` in `apps/api`, run `alembic upgrade head` against the
   ephemeral DB, then `ruff check`, `mypy src`, and `pytest -q --maxfail=1`, explicitly including the
   `-m rls` marker so the RLS adversarial suite (Prompt 16) always runs — never let it be an
   optional/manual job.
2. `frontend-checks` (matrix over `apps/web-employee` and `apps/web-admin`): `npm ci`,
   `npm run typecheck`, `npm run lint`, `npm run test`, `npm run build`.
3. `automation-checks`: `uv sync` in `apps/automation`, run its own (much smaller) test suite,
   and — as an explicit assertion, not just a convention — grep its dependency files/config to
   confirm no `DATABASE_URL`/`REDIS_URL`-shaped secret is referenced anywhere in `apps/automation`,
   failing the build if one is found, as an automated tripwire for AGENT.md Prime Directive #6.

All three jobs must be required status checks before merge is allowed (document this as a note for
whoever configures branch protection in the GitHub UI, since that part isn't expressible in the YAML
itself).

Paste the full workflow file and explain the tripwire check in step 3 in enough detail that someone
maintaining this later understands why it exists, not just what it does.
```

**Expected Output**: A CI workflow with backend, frontend, and automation-isolation jobs, including
an automated check that specifically guards Prime Directive #6 rather than relying on code review
alone to catch a violation.

**Notes**: The automation-isolation tripwire in job 3 is the most novel part of this pipeline —
don't let it get simplified away as "redundant with code review" during implementation; it's meant
to catch exactly the kind of accidental regression review might miss.

---

### PROMPT 23: Production Deployment & Container Orchestration
**Purpose**: Translate the docker-compose-based local topology (system_architecture.md §10) into production-ready container definitions and orchestration manifests, preserving the network segmentation the architecture depends on.

**Prompt**:
```
Read system_architecture.md §10 in full before starting — the network segmentation described there
(public / application / data / sandbox networks, with the sandbox network having explicitly NO
route to Postgres or Redis) is a security property this deployment must preserve, not just a
diagram to loosely approximate.

1. Write production `Dockerfile`s for `apps/api`, `apps/worker`, and `apps/automation` as separate
   images (the automation image must not include the API's dependency tree or any DB
   driver/connection library at all — verify this by listing the final image's installed packages
   and confirming no Postgres/Redis client library appears in `apps/automation`'s image).
2. Write {{ORCHESTRATION_TARGET: e.g., "Kubernetes manifests" or "an ECS task-definition set" —
   FILL IN based on our actual target}} that implement the four-network topology from
   system_architecture.md §10: specifically, confirm the mechanism you're using to guarantee the
   automation workload cannot reach the data network even if misconfigured application-side (e.g.,
   a NetworkPolicy / security group with an explicit deny, not merely "we didn't give it the
   credentials" — credentials-only isolation is not the same guarantee as network-level isolation).
3. Externalize every secret (`JWT_SIGNING_KEY`, DB credentials, Redis URL, the automation HMAC
   shared secret, the pseudonymization pepper) via {{SECRETS_MECHANISM: e.g., "Kubernetes Secrets
   backed by an external secrets operator" or your actual target}} — none may appear in the
   Dockerfiles, images, or committed manifests.
4. Confirm a rolling-deploy strategy for `apps/api` that's compatible with the session-revocation
   architecture in system_architecture.md §5 — specifically, new pods/tasks must complete their
   Redis-hydration startup step (Prompt 5, step 4) and pass a readiness probe BEFORE receiving
   traffic, so a freshly started replica is never live before its local revocation cache is warm.
5. Add a readiness probe hitting `/healthz` (from Prompt 2) and a liveness probe, tuned so a replica
   that loses its Redis connection is marked not-ready rather than silently serving requests with a
   stale/empty revocation cache.

Paste all Dockerfiles and manifests, and explicitly answer: what mechanism enforces that the
automation network cannot reach Postgres/Redis, at the network level, independent of application
configuration?
```

**Expected Output**: Production container definitions and orchestration manifests with a genuine
network-level (not merely credential-level) guarantee isolating the automation workload, secrets
fully externalized, and a rollout strategy that respects the revocation-cache warm-up requirement.

**Notes**: `{{ORCHESTRATION_TARGET}}` and `{{SECRETS_MECHANISM}}` must be filled in based on the
team's actual infrastructure before sending this prompt — sending it with those still as
placeholders will produce a generic, non-committal answer.

---

### PROMPT 24: Security / Zero-Trust Pre-Release Audit
**Purpose**: A comprehensive, whole-system pass run before any production release (and periodically afterward), pulling together every Prime Directive into one audit rather than checking them piecemeal per-PR.

**Prompt**:
```
Read AGENT.md and system_architecture.md in full. This is a pre-release audit — assume nothing
from prior reviews still holds; verify each item fresh against the current state of the codebase.

For each Prime Directive in AGENT.md §2, produce a section with:
- **Claim**: restate the directive in one sentence.
- **Evidence**: name the specific test(s) (from Prompts 15–17) that currently prove it, with a
  pass/fail status from actually running them just now, not from memory of a past run.
- **Gaps**: anything the directive requires that you could not find a test for. Do not mark a
  directive "satisfied" on code-inspection alone if no test proves it — a missing test is itself a
  finding, not a pass.

Additionally, specifically check:
1. Every tenant-scoped table (re-enumerate from the ORM models, don't reuse an old list) has RLS
   enabled AND forced — query `pg_tables`/`pg_policies` against a real running instance to confirm,
   don't just grep migration files (a migration could have been reverted or a table added without
   following Prompt 4).
2. No endpoint accepts a client-supplied `organization_id`, timestamp-of-record, or payroll-period
   date where the server should be authoritative — grep for any request-body field name suggestive
   of this and manually justify each one found.
3. No secret (signing keys, HMAC secret, pseudonymization pepper, DB/Redis credentials) appears
   anywhere in the git history of tracked files, not just the current working tree.
4. The automation sandbox's network isolation (Prompt 23) is actually in effect in the current
   deployment config, not just documented as a goal.

Conclude with an overall **Release Blocker** / **Release OK with noted follow-ups** verdict, and if
blockers exist, rank them by which Prime Directive they violate.
```

**Expected Output**: A directive-by-directive audit with fresh evidence (test runs, live database
queries, git-history secret scans) rather than a restatement of design intent, ending in an explicit
release-readiness verdict.

**Notes**: The instruction to re-run tests "just now, not from memory of a past run" and to query
`pg_policies` against a live instance rather than grepping migrations matters — a stale audit that
just re-asserts what earlier prompts already claimed provides no new assurance before a release.

---

### PROMPT 25: Performance & Load Testing Pass
**Purpose**: Validate the system under the specific load patterns implied by the project's two very different usage profiles — high-concurrency employee actions (clock-in) and heavier, less frequent admin/batch operations (payroll close). Run before release and after any significant change to the attendance or payroll modules.

**Prompt**:
```
Read system_architecture.md §11 (Observability & Operational Concerns) for the illustrative latency
targets before starting, and treat them as targets to validate or explicitly revise with real
numbers, not as already-proven facts.

1. **Clock-in burst test**: using {{LOAD_TESTING_TOOL: e.g., "Locust" or "k6" — state which and
   why}}, simulate {{N}} employees across {{M}} organizations all clocking in within the same
   60-second window (the realistic "everyone arrives at 9am" pattern). Measure p50/p95/p99 latency
   on `POST /attendance/clock-in`, and separately measure whether the RLS/tenant-context overhead
   (§3) shows up as a measurable tax under this load compared to a control endpoint with no
   tenant-scoped query.
2. **Leave-scheduler contention test**: simulate a smaller number of employees firing overlapping
   leave requests concurrently against the SAME employee record repeatedly (deliberately trying to
   trigger the exclusion constraint under load, not avoid it), and confirm the 409 rate matches
   expectations and that legitimate non-overlapping requests from other employees in the same load
   window are unaffected in latency.
3. **Payroll close batch test**: simulate closing a month for an organization with {{N}} employees'
   worth of ledger lines, and confirm: (a) it completes within {{TARGET_WINDOW}}, (b) if
   artificially interrupted partway through, re-running it is safe and idempotent (already-closed
   lines are skipped, not double-closed or errored on), per the resumability requirement in
   system_architecture.md §11.
4. **Session-revocation propagation test**: with multiple simulated API node processes running
   locally, measure actual wall-clock time from a revocation event to all nodes' local caches
   reflecting it, and compare against the ~2-second illustrative target in system_architecture.md
   §11 — report the real number either way.

For each test, report actual measured numbers (not pass/fail against a guess) and, if a target in
system_architecture.md §11 turns out to be unrealistic in either direction, propose a specific
updated number via Prompt 21 (ADR) rather than silently leaving the stale target in the doc.
```

**Expected Output**: Real measured latency/throughput numbers for all four scenarios, an explicit
comparison against the architecture doc's illustrative targets, and — where a target was wrong — a
proposed ADR updating it rather than a silent mismatch between documentation and reality.

**Notes**: `{{LOAD_TESTING_TOOL}}`, `{{N}}`, `{{M}}`, and `{{TARGET_WINDOW}}` need real values
appropriate to the expected production scale before sending this prompt — generic placeholder-scale
numbers will produce a load test that doesn't actually validate anything meaningful about production
readiness.
