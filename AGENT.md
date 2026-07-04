# AGENT.md — Zero-Trust HRMS

## 0. What this file is

This is the operating manual for any coding agent (Antigravity, Claude Code, Cursor, or a human
following the same playbook) working in this repository. `system_architecture.md` explains **how**
the system is designed. This file explains **how an agent must behave** while building inside that
design.

Read this file in full before writing, editing, or generating a plan for any code in this repo.
If a prompt in `master_prompt_set.md`, a ticket, or an ad-hoc instruction conflicts with a rule in
this file, **this file wins**, unless the human explicitly overrides it in writing in that
instruction (and even then, Section 2 rules should trigger a confirmation question, not silent
compliance).

---

## 1. Project Identity

- **Name:** Zero-Trust HRMS
- **Shape:** One hardened API surface, two frontends — the **Employee Self-Service Portal**
  (high-concurrency, narrow permissions) and the **Admin/HR Control Center** (low-concurrency,
  broad permissions, complex workflows).
- **Security posture:** Zero-trust. No layer trusts another layer's judgment about tenant identity,
  session validity, financial-period mutability, or deletion status — each of those is enforced at
  the layer closest to the data (mostly PostgreSQL), not only in application code.
- **Multi-tenancy model:** Shared database, shared schema, per-row isolation via PostgreSQL
  Row-Level Security. There is no per-tenant database or schema.
- **Explicit non-goals** (do not build unless a human explicitly asks): public self-service
  sign-up, native mobile apps, multi-region active-active deployment, offline-first clients.

---

## 2. Prime Directives — Non-Negotiable Invariants

These map directly to the six architectural pillars in `system_architecture.md`. An agent must
treat every one of these as a hard constraint, not a style preference. If a task appears to require
violating one of these, **stop and ask** rather than finding a clever workaround.

1. **Tenant isolation is a database property, not an application property.**
   Every table containing tenant-scoped data must have RLS enabled and forced
   (`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`), with a policy keyed on
   `current_setting('app.current_organization_id')`. Application-level `WHERE organization_id = …`
   clauses are **defense in depth only** — they must never be treated as the actual isolation
   mechanism, and their presence or absence must never be the reviewer's basis for approving a
   query as tenant-safe. Never write a query against a raw `asyncpg`/SQLAlchemy connection that
   bypasses the session that has had `SET LOCAL app.current_organization_id` applied.

2. **Session revocation must be near-instant and must not add a database round-trip to every request.**
   Access-token validity is checked against an in-memory, per-process blacklist of `jti` values,
   kept in sync via Redis Pub/Sub. Never introduce a synchronous DB lookup on the hot request path
   to check "is this user still active" — that defeats the entire point of this architecture.

3. **Leave overlap protection lives in the database, not in Python.**
   The authority for "do these two leave requests overlap" is the PostgreSQL exclusion constraint
   (`btree_gist` + `EXCLUDE USING gist`). Application-level overlap checks (e.g., querying existing
   rows and comparing ranges in Python before insert) may exist only as a **fast-fail UX
   convenience** to produce a friendly error message before hitting the DB — they must never be the
   sole protection, because they cannot close a race condition between two concurrent requests.

4. **Closed payroll months are immutable. Full stop.**
   Once a `payroll_ledger_lines` row's month is closed, no code path — including admin tools,
   support scripts, or "just this once" hotfixes — may `UPDATE` or `DELETE` it. Every back-dated
   correction is a new row in the currently open month, referencing the original line via
   `adjustment_of`. If an agent is asked to "just fix the number in last month's ledger," the correct
   implementation is always an adjustment row, never a mutation, even under time pressure.

5. **Offboarding is soft-delete first, pseudonymization second, and never a hard delete of financial history.**
   `DELETE FROM employees` (or equivalent ORM `.delete()`) must never be used for offboarding.
   Right-to-be-forgotten requests run through the pseudonymization pipeline described in
   `system_architecture.md §4.5`, which preserves aggregate/structural integrity of payroll history
   while destroying re-identifiable links.

6. **Browser automation and scraping never run in the same container, process, or network segment as the
   user-facing API.** Crawl4AI/Playwright workloads are dispatched via Celery to an isolated worker
   network with no direct database credentials. They return data only via an HMAC-SHA256-signed
   callback to a dedicated internal endpoint, which independently re-derives the tenant context from
   the original job record — never from a field inside the untrusted callback payload alone.

---

## 3. Tech Stack & Pinned Choices

| Layer | Choice | Notes |
|---|---|---|
| API framework | FastAPI (async) | All I/O-bound endpoints are `async def`. No blocking calls (`requests`, sync psycopg2, sync file I/O) inside async routes — use `httpx.AsyncClient`, `asyncpg`/`SQLAlchemy[asyncio]`, or offload to a thread pool via `run_in_threadpool`. |
| Validation | Pydantic v2 | Use `model_config = ConfigDict(...)`, not the v1 `class Config`. Use `field_validator`/`model_validator`, not `@validator`. |
| Package/env manager | `uv` | `uv.lock` is committed and authoritative. Never hand-edit lockfiles. Never `pip install` directly inside the repo's venv. |
| Primary datastore | PostgreSQL (15+) | Required extensions: `btree_gist`, `pgcrypto` (or `uuid-ossp`) for UUID generation, `citext` for case-insensitive email columns. |
| Cache / pub-sub / locks | Redis | Three distinct logical uses — session-revocation broadcast, distributed locks (`SET NX PX`), and short-lived caches. Keep these on separate key prefixes/namespaces even if sharing one Redis instance in dev. |
| Background jobs | Celery + Celery Beat | Beat owns cron-style jobs (midnight delta sync, ledger close). Regular Celery workers own request-triggered async jobs (invitation emails, automation dispatch). |
| Automation sandbox | Crawl4AI + Playwright | Runs in its own container/network. Never imported into the `api` service's dependency tree. |
| Frontend | TypeScript + React + Vite | `strict: true` in `tsconfig.json`. No `any` without an inline comment justifying it. |
| HTTP client (frontend) | Axios (or native `fetch`, but not both in the same app) | Wrapped in one shared interceptor module — see `master_prompt_set.md` Prompt 14. |

---

## 4. Repository Layout

```
hrms/
├── AGENT.md
├── system_architecture.md
├── docker-compose.yml
├── apps/
│   ├── api/                     # FastAPI monolith (single API surface for both frontends)
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── core/             # settings, security primitives, tenant-context plumbing
│   │   │   ├── db/               # session factory, base models, RLS-aware session dependency
│   │   │   ├── modules/
│   │   │   │   ├── auth/         # login, refresh, logout, session revocation
│   │   │   │   ├── invitations/
│   │   │   │   ├── attendance/
│   │   │   │   ├── leave/
│   │   │   │   ├── payroll/
│   │   │   │   ├── offboarding/  # GDPR pipeline
│   │   │   │   └── automation_ingress/  # signed-callback endpoint only, no automation code
│   │   │   └── tests/
│   │   └── alembic/
│   │       ├── env.py
│   │       └── versions/
│   ├── worker/                   # Celery worker + beat entrypoints, shares `api` package
│   ├── automation/                # Crawl4AI/Playwright sandbox — isolated pyproject, isolated network
│   ├── web-employee/              # Vite + React, employee self-service
│   └── web-admin/                 # Vite + React, admin/HR control center
├── packages/
│   └── shared-types/               # OpenAPI-generated TS types, consumed by both frontends
└── infra/
    ├── docker/
    └── ci/
```

An agent must not invent an alternative top-level layout without flagging it as a proposal first.

---

## 5. Environment Setup & Common Commands

```bash
# Backend
cd apps/api
uv sync                                  # install pinned deps
uv run alembic upgrade head               # apply migrations
uv run uvicorn src.main:app --reload      # local dev server

# Migrations
uv run alembic revision --autogenerate -m "{{description}}"
uv run alembic upgrade head
uv run alembic downgrade -1               # every migration must support this

# Workers
uv run celery -A src.worker.celery_app worker -l info -Q default
uv run celery -A src.worker.celery_app beat -l info

# Tests
uv run pytest -q                          # unit + integration
uv run pytest -q -m rls                   # RLS-specific adversarial suite
uv run ruff check .
uv run mypy src

# Frontend (run in apps/web-employee and apps/web-admin independently)
npm install
npm run dev
npm run typecheck
npm run test
npm run build

# Full stack, local
docker compose up --build
```

---

## 6. Backend Coding Conventions

- **Layering:** `router -> service -> repository -> ORM model`. Routers parse/validate input and
  serialize output only. Business logic lives in services. Repositories are the only layer allowed
  to hold raw SQL/ORM queries.
- **Tenant context is a request-scoped dependency**, not a global variable, not a `contextvars`
  singleton set once at process start. It must be re-derived per-request from the authenticated
  session, and applied via `SET LOCAL` inside the same transaction that will run the subsequent
  queries (see `system_architecture.md §3`).
- **Every new table** ships in the same PR as: its RLS policy, an entry in the RLS adversarial test
  suite (Prompt 16), and a rollback-tested Alembic migration.
- **Money is always integer minor units** (`amount_cents: BIGINT`), never `FLOAT`/`NUMERIC` floats
  in application code paths that do arithmetic — `NUMERIC` is fine at rest in Postgres, but
  arithmetic in Python must go through a `Money` value object, not raw floats.
- **All timestamps are `TIMESTAMPTZ`, stored and compared in UTC.** Local-time display is a
  presentation-layer conversion using the employee's stored IANA timezone string, done at the
  edge (API response or frontend), never baked into a stored column.
- **Structured logging only** — one JSON line per log event, always including `request_id` and
  `organization_id` (when available). Never `print()`.
- **No bare `except:`** and no swallowing exceptions silently. Domain errors are explicit exception
  classes mapped to HTTP responses at the router boundary.

---

## 7. Frontend Coding Conventions

- **Feature-folder structure**, not type-folder structure: `features/leave-requests/{api,components,hooks,types}`,
  not a global `components/` dumping ground.
- **One shared Axios (or fetch) client module per app**, wrapping the cookie-refresh interceptor
  (Prompt 14). Feature code never constructs its own HTTP client instance.
- **Server state and client state are not the same state.** Prefer a dedicated data-fetching layer
  (e.g., TanStack Query) for anything that comes from the API, and reserve local component
  state/context for pure UI state (open modals, form drafts). This is a recommended default, not
  mandated by the source plan — flag it if the team wants to swap it for hand-rolled fetching.
- **No component reaches into `localStorage`/`sessionStorage` for auth tokens.** Access tokens live
  in memory only; refresh tokens are `HttpOnly` cookies the frontend never reads directly.
- **Strict TypeScript.** API request/response types are generated from the backend's OpenAPI schema
  into `packages/shared-types`, never hand-duplicated in each app.

---

## 8. Database & Migration Discipline

- Table names: `snake_case`, plural (`employees`, `leave_requests`, `payroll_ledger_lines`).
- Every tenant-scoped table has an `organization_id UUID NOT NULL` column, a matching FK to
  `organizations(id)`, and an RLS policy — no exceptions, including junction/audit tables.
- Every migration must be reversible (`downgrade()` implemented and tested), even for
  RLS/constraint/trigger changes.
- Destructive migrations (drop column, drop table) require an explicit human sign-off flagged in
  the PR description — an agent must not silently generate one as part of a larger autogenerated
  diff without calling it out.
- New extensions (`btree_gist`, `citext`, etc.) are enabled via a dedicated migration, not inline in
  a feature migration, so they're easy to audit.

---

## 9. Security Rules Every Agent Must Enforce (checklist)

Before marking any backend PR "ready for review," confirm:

- [ ] No endpoint trusts a client-supplied `organization_id` for anything other than an
      administrative "which org am I acting on" selector that is itself re-validated server-side
      against the authenticated user's memberships.
- [ ] No endpoint trusts client-supplied timestamps for attendance, leave, or payroll-effective
      dates where the server clock is the source of truth (client-supplied *intent* like "requested
      leave start date" is fine; *recorded fact* like "clock-in time" is never client-supplied).
- [ ] Every new secret (JWT signing key, HMAC callback secret, pseudonymization pepper) is read from
      environment/secrets manager, never hard-coded, never logged.
- [ ] Every new admin-privileged endpoint has both an authn check (valid session) and an authz
      check (correct role/permission for that organization) — a valid session is not sufficient.
- [ ] Every place that used to call `.delete()` on an `Employee` row instead performs a soft-delete
      (`status = 'terminated'`, `deleted_at = now()`).

---

## 10. Testing Bar

A change is not "done" until:

- Unit tests cover new service-layer logic, including at least one deliberately adversarial case per
  prime directive it touches (e.g., a leave-scheduler test that fires two conflicting inserts
  concurrently and asserts exactly one succeeds).
- Any new or modified table with RLS has a corresponding test in the RLS adversarial suite proving a
  session scoped to Org A cannot read/write a row belonging to Org B, even via an ORM shortcut.
- Integration tests for payroll changes assert that closed-month rows are provably unchanged
  (checksum/hash comparison before and after) and that an adjustment produced the expected delta.
- Frontend changes touching data-fetching or auth include a test proving the request retries once
  after a silent token refresh and does not retry infinitely on a hard 401.
- `ruff`, `mypy`, and the frontend `typecheck`/lint scripts are clean — an agent should never turn
  off a lint rule to make a check pass without flagging that as a proposal for human sign-off.

---

## 11. Git, Commits, PRs

- Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`).
- Branch naming: `feature/{{ticket-id}}-{{short-slug}}`, `fix/{{ticket-id}}-{{short-slug}}`.
- Every PR description answers: *which prime directive(s) from Section 2 does this touch, and how
  was each one verified (test name / manual check)?* If none apply, say so explicitly rather than
  omitting the section.
- No PR mixes an unrelated dependency bump with a feature change.

---

## 12. Domain Glossary

| Term | Meaning |
|---|---|
| **Tenant / Organization** | A customer company using the HRMS. All tenant data is scoped by `organization_id`. |
| **RLS (Row-Level Security)** | PostgreSQL feature that filters rows per-query based on a session-level setting, enforced by the database engine regardless of application code. |
| **`app.current_organization_id`** | The Postgres session variable (`SET LOCAL`) carrying the active tenant for the current transaction. |
| **`jti`** | JWT ID claim — a unique identifier per issued access token, used as the revocation-blacklist key. |
| **Exclusion constraint** | A Postgres constraint (via `btree_gist`) that rejects a row if it conflicts with an existing row under a specified condition (here: same employee, overlapping time range). |
| **Temporal Rule Engine** | The `valid_from`/`valid_to`-bounded rule table that lets payroll calculations reconstruct "what rule was active on date X," even long after that rule was superseded. |
| **Ledger close** | The point at which a payroll month's lines become immutable (`status = 'closed'`). |
| **Adjustment line** | A new ledger row in the current open month that carries a delta correcting a prior closed month, referencing the original via `adjustment_of`. |
| **Pseudonymization** | The GDPR offboarding step that replaces an employee's identifying fields with a peppered hash and rolls detailed org data up into a broad "structural cohort," while leaving payroll math intact. |
| **Structural Cohort** | A broad, non-identifying grouping (e.g., "Engineering Dept," "Region: East") that pseudonymized records are rolled up into, so historical payroll aggregates remain meaningful. |
| **Automation sandbox** | The isolated container/network running Crawl4AI/Playwright, communicating with the API only via signed callback. |
| **HMAC callback** | The signed POST from the automation sandbox back to the API, verified via HMAC-SHA256 before its payload is trusted. |

---

## 13. Forbidden Patterns (explicit anti-examples)

```python
# ❌ FORBIDDEN — filtering by org_id in application code as the *only* protection
async def get_employee(db: AsyncSession, employee_id: UUID, org_id: UUID):
    return await db.scalar(
        select(Employee).where(Employee.id == employee_id, Employee.organization_id == org_id)
    )
    # Even if this looks safe, if RLS is ever disabled/misconfigured on `employees`,
    # this is a cross-tenant leak waiting to happen. RLS must be doing the real work.

# ❌ FORBIDDEN — checking leave overlap only in Python before insert
existing = await db.execute(select(LeaveRequest).where(LeaveRequest.employee_id == emp_id))
if any(overlaps(r, new_start, new_end) for r in existing.scalars()):
    raise HTTPException(409, "Overlapping leave")
await db.execute(insert(LeaveRequest).values(...))
# Two concurrent requests can both pass the check before either commits. The EXCLUDE
# constraint, not this check, is what must actually prevent the double-booking.

# ❌ FORBIDDEN — mutating a closed payroll line
await db.execute(
    update(PayrollLedgerLine).where(PayrollLedgerLine.id == line_id).values(amount_cents=new_amount)
)
# Must instead insert a new adjustment row referencing `line_id` in the open month.

# ❌ FORBIDDEN — hard-deleting an employee on offboarding
await db.execute(delete(Employee).where(Employee.id == employee_id))
# Must soft-delete, and route GDPR requests through the pseudonymization pipeline.
```

---

## 14. Escalation — When an Agent Should Stop and Ask

Stop and ask a human (do not guess, do not silently pick the "safer-looking" interpretation) when:

- A task seems to require disabling, weakening, or working around any Prime Directive in Section 2.
- A task asks for a one-off script that touches production payroll or employee PII data outside the
  documented pipelines.
- A migration is destructive (drops a column/table with data) and no explicit sign-off is present in
  the ticket.
- Requirements for a new feature don't specify which frontend (Employee Portal vs Admin Control
  Center) it belongs to, and the permission model would differ significantly between the two.

When in doubt, produce the implementation plan / task list artifact and flag the specific open
question in it, rather than proceeding on an assumption for anything security- or finance-adjacent.
