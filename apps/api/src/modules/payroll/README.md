# Payroll Module

## Domain Responsibilities & Boundary
The `payroll` module manages payroll rules (temporal rule engine), ledger lines (earnings, deductions, adjustments), month closing operations, and adjustment creation. It ensures financial integrity and auditing standards.

## Prime Directives Enforced
* **Directive #1 (Tenant Isolation):** Row-Level Security (RLS) is active on all payroll-related tables (`payroll_ledger_lines`, `payroll_rules`), preventing cross-tenant access.
* **Directive #4 (Ledger Immutability):** Closed payroll months are strictly immutable. Once `status` becomes `'closed'`, the records cannot be modified or deleted by any user or script. Updates require inserting an adjustment line in the *currently open month*, pointing back to the original line via the `adjustment_of` foreign key.
  * *Code reference:* `apps/api/src/modules/payroll/router.py#L182-L215` enforces that adjustments are only created against closed lines, and the adjustment line itself is written to the current open month.

## Primary Entry Points
* **Router:** `apps/api/src/modules/payroll/router.py`
  * `GET /payroll/lines` - Fetch ledger lines for an employee and month (Admin only).
  * `POST /payroll/close-month` - Lock all open lines for a month (Admin only).
  * `POST /payroll/adjustments` - Create a back-dated adjustment (Admin only).
* **Resolver:** `apps/api/src/modules/payroll/resolver.py` (`PayrollRuleResolver`)
  * Resolves temporal rules using `valid_from` and `valid_to` timestamps.

## Operational Gotchas & DB Locking
* **Temporal Rule Resolution:** Adjustments must reconstruct "what rule was active on date X" using the resolver, rather than applying current rules retrospectively.
* **Month Close Locks:** Closing a month is a bulk update operation that changes the status of all open lines to `closed`. Future calculations or pipelines must check the ledger status before appending details.
