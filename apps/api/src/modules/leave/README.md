# Leave Module

## Domain Responsibilities & Boundary
The `leave` module handles requesting, approving, rejecting, and listing employee leave requests. It enforces date/time boundary constraints and ensures no double-booking occurs.

## Prime Directives Enforced
* **Directive #1 (Tenant Isolation):** Row-Level Security (RLS) is active on the `leave_requests` table, restricting access to requests within the employee's or admin's organization.
* **Directive #3 (Leave Overlap Protection):** Double-booking protection is enforced strictly by the database using a PostgreSQL GiST exclusion constraint:
  ```sql
  CONSTRAINT no_overlapping_active_leave EXCLUDE USING gist (
      employee_id WITH =,
      tstzrange(start_time, end_time, '[]') WITH &&
  ) WHERE (status IN ('pending', 'approved'))
  ```
  Any concurrent inserts that violate this range overlap will be immediately aborted by the Postgres engine, eliminating race conditions.
  * *Code reference:* `apps/api/src/modules/leave/router.py#L93-L121` handles the resulting database exceptions.

## Primary Entry Points
* **Router:** `apps/api/src/modules/leave/router.py`
  * `GET /leave-requests` - List leave requests (employees get their own, admins get organization-wide).
  * `POST /leave-requests` - Submit a new leave request.
  * `PATCH /leave-requests/{request_id}/approve` - Approve a pending request (Admin only).
  * `PATCH /leave-requests/{request_id}/reject` - Reject a request, immediately releasing the time slot (Admin only).

## Operational Gotchas & DB Locking
* **Transaction Abort & Diagnostics:** When the GiST exclusion constraint is triggered, Postgres aborts the current transaction with SQLSTATE `23P01`. To report a friendly error message, the service must perform a diagnostic query inside a *separate* database session to fetch the details of the conflicting request.
* **Exclusion Release on Rejection:** Since the exclusion constraint index is filtered `WHERE status IN ('pending', 'approved')`, changing a request's status to `'rejected'` immediately removes it from the index, allowing new requests for that time range to succeed without conflict.
