# Zero-Trust HRMS (Human Resource Management System)

Zero-Trust HRMS is a secure, multi-tenant enterprise human resource management system. It is designed around a hardened API backend and two decoupled client interfaces: the **Employee Self-Service Portal** and the **Admin/HR Control Center**.

The project enforces zero-trust security invariants directly at the database layer (via PostgreSQL Row-Level Security, exclusion constraints, and temporal rule queries), ensuring that tenant boundaries, session states, and historical financial records remain tamper-proof.

---

## Architectural Highlights

* **Tenant Isolation:** Enforced using Row-Level Security (RLS) in PostgreSQL. Tenant context is resolved dynamically on a per-request transaction scope, not trusted from client-side parameters.
* **Instant Session Revocation:** A high-performance, tiered caching strategy. Decoded access token IDs (`jti`) are checked against an in-memory per-process blacklist, synchronized in near real-time across nodes via Redis Pub/Sub.
* **Leave Overlap Safety:** Uses database-level PostgreSQL GiST exclusion constraints (`EXCLUDE USING gist`) to prevent overlapping leave bookings, preventing race conditions.
* **Ledger Immutability:** Closed payroll months cannot be updated or deleted. Historical corrections are recorded as delta adjustment lines in the current open month, referencing the original closed line.
* **Offboarding Pipeline:** Adheres to GDPR "Right to be Forgotten" via a pseudonymization service. Identifiable employee data is scrubbed, while structural aggregates are preserved for tax/auditing purposes.
* **Automation Sandboxing:** Scraping/automation jobs (Crawl4AI + Playwright) run in an isolated network segment without DB credentials. Communication with the API is secured via HMAC-SHA256 signed callbacks.

For more details, see [system_architecture.md](system_architecture.md) and [AGENT.md](AGENT.md).

---

## Repository Layout

```
hrms/
├── AGENT.md                     # Coding playbook and prime directives
├── system_architecture.md       # Detailed technical design document
├── docker-compose.yml           # Local multi-container development environment
├── apps/
│   ├── api/                     # FastAPI backend monolith
│   ├── worker/                  # Celery background task worker & beat
│   ├── automation/              # Crawl4AI/Playwright scraping sandbox
│   ├── web-employee/            # Vite + React employee portal
│   └── web-admin/               # Vite + React admin control center
└── packages/
    └── shared-types/            # OpenAPI-generated TypeScript schemas
```

---

## Local Development Setup & Verification

Before running commands, ensure you have PostgreSQL and Redis instances configured, or use the Docker Compose environment.

### 1. Database & Backend API Setup

Run the following commands inside the `apps/api/` directory:

```bash
cd apps/api

# Install backend dependencies via uv
uv sync

# Run database migrations using Alembic
uv run alembic upgrade head

# Start local FastAPI development server (reloads on change)
uv run uvicorn src.main:app --reload
```

### 2. Background Workers Setup

Start Celery and Celery Beat in separate terminal sessions or run them via background processes:

```bash
cd apps/api

# Start default queue worker
uv run celery -A src.worker.celery_app worker -l info -Q default

# Start scheduler beat (handles recurring tasks like ledger closes)
uv run celery -A src.worker.celery_app beat -l info
```

### 3. Frontend App Setup

Initialize and run either frontend client (`web-employee` or `web-admin`):

```bash
cd apps/web-employee  # Or apps/web-admin
npm install
npm run dev
```

---

## Running Verification Commands

All backend checks must be run with a cleared `PYTHONPATH` to ensure system libraries (e.g., ROS) do not conflict with dependency imports.

```bash
cd apps/api

# Run entire test suite (unit & integration)
PYTHONPATH="" uv run pytest

# Run adversarial RLS tests only
PYTHONPATH="" uv run pytest -m rls

# Check code formatting & linting
uv run ruff check .

# Validate static types
uv run mypy src
```

For the frontend applications, verify typescript safety:

```bash
cd apps/web-employee  # Or apps/web-admin
npm run typecheck
npm run lint
npm run build
```
