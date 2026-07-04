# Employees Module

## Domain Responsibilities & Boundary
The `employees` module manages employee identities, profile data, self-service fields (e.g. name, contact info), and organizational status (active vs. terminated). It serves as the primary source of truth for user profiles in the system.

## Prime Directives Enforced
* **Directive #1 (Tenant Isolation):** Every query against the `employees` table is isolated at the database level via Postgres Row-Level Security (RLS) policies.
  * *DB Policy:* Scopes operations to the active tenant in the transaction context.
* **Directive #5 (Soft-Delete Termination):** An employee record must never be deleted from the database (`DELETE FROM employees` is strictly forbidden). Offboarding begins with a soft-delete status update:
  ```python
  employee.status = "terminated"
  employee.deleted_at = datetime.now(timezone.utc)
  ```
  This preserves the referential integrity of historical attendance logs, leave records, and payroll ledgers.
  * *Code reference:* `apps/api/src/modules/employees/router.py#L182-L219`.

## Primary Entry Points
* **Router:** `apps/api/src/modules/employees/router.py`
  * `GET /employees` - List all employees in the organization (Admin only).
  * `GET /employees/me` - Fetch own profile details.
  * `PATCH /employees/me` - Self-service profile updates (e.g., name).
  * `PATCH /employees/{employee_id}` - Administrative profile updates (Admin only).
  * `POST /employees/{employee_id}/terminate` - Terminate an employee record (Admin only).

## Operational Gotchas & DB Locking
* **Admin-only status transitions:** Regular employees can call `PATCH /employees/me` to update basic profile details, but any fields mutating roles or statuses must be ignored or rejected to prevent privilege escalation.
* **Cascading Effects:** Changing status to `terminated` should trigger checks (e.g., revoking active refresh tokens or canceling future pending leave requests).
