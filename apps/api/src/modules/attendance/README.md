# Attendance Module

## Domain Responsibilities & Boundary
The `attendance` module tracks employee clock-in and clock-out events, maintains active status logs, and provides retrieval interfaces for individual and organizational attendance histories.

## Prime Directives Enforced
* **Directive #1 (Tenant Isolation):** The `clock_events` table enforces multi-tenancy at the database layer via PostgreSQL RLS.
  * *DB Policy:* Filters reads/writes based on the transaction's `app.current_organization_id`.
* **Zero Client-Clock Trust (Directive #9 check):** Clock-in and clock-out endpoints do not accept client-provided timestamps. The server clock (`datetime.now(timezone.utc)`) is the sole source of truth for the event recording.
  * *Code reference:* `apps/api/src/modules/attendance/router.py#L67` and `L126`.

## Primary Entry Points
* **Router:** `apps/api/src/modules/attendance/router.py`
  * `POST /attendance/clock-in` - Record a new clock-in event for the authenticated user.
  * `POST /attendance/clock-out` - Record a clock-out event for the authenticated user.
  * `GET /attendance/history` - Query attendance history (Employees see their own; Admins see the organization's).

## Operational Gotchas & DB Locking
* **Linear State Machine:** Clock events must be alternating (In -> Out -> In). To enforce this and prevent duplicate clock-ins/outs:
  * The system performs a point lookup of the employee's most recent `clock_event` record before inserting the next event.
  * In high-concurrency or automated setups, race conditions are mitigated by database-level constraints or application-level locks.
