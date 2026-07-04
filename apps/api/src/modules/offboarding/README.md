# Offboarding Module

## Domain Responsibilities & Boundary
The `offboarding` module implements the GDPR "Right to be Forgotten" (pseudonymization) workflow. It verifies termination preconditions, destroys personally identifiable information (PII) by replacing fields with peppered hashes, rolls organizational properties into cohorts, and preserves anonymized ledger history.

## Prime Directives Enforced
* **Directive #1 (Tenant Isolation):** All offboarding-related tables (`pseudonymization_keys`) use Postgres RLS to ensure tenant data is secure.
* **Directive #5 (GDPR Pseudonymization & Financial History Preservation):** Hard deletes on employee records are prohibited. The offboarding service scrubs identity fields (`full_name`, `email`, `password_hash`) and replaces them with a cryptographic pseudonym hash. It retains aggregate payroll history for tax and accounting audits.
  * *Code reference:* `apps/api/src/modules/offboarding/service.py#L21-L98`.

## Primary Entry Points
* **Router:** `apps/api/src/modules/offboarding/router.py`
  * `POST /offboarding/{employee_id}/forget` - Initiates the pseudonymization pipeline for the terminated employee.
* **Service:** `apps/api/src/modules/offboarding/service.py` (`PseudonymizationService`)
  * Validates preconditions, computes cohort summaries, updates the employee record, and creates a pseudonymization record.

## Operational Gotchas & DB Locking
* **Precondition Check:** The employee's status must be `'terminated'` and `deleted_at` must not be null. Active employees cannot be pseudonymized.
* **Database Lock during Update:** The service locks the employee row (`SELECT FOR UPDATE`) at the start of the pseudonymization transaction to prevent concurrent updates or race conditions with other operations.
