# Automation Ingress Module

## Domain Responsibilities & Boundary
The `automation_ingress` module serves as the communication gateway between the core user-facing API and the isolated Celery automation worker environment. It dispatches scraping tasks and validates callback results returned by the worker.

## Prime Directives Enforced
* **Directive #6 (Automation Sandboxing & Signature Verification):** The automation worker runs in an isolated network segment without direct DB access. It returns scraping results via a POST request to `/internal/automation/callback`.
* **HMAC Signature Verification:** The callback endpoint verifies the `X-Signature` header computed from the raw request body bytes and a shared secret:
  ```python
  hmac.new(shared_secret, raw_body_bytes, hashlib.sha256).hexdigest()
  ```
  This is compared using `hmac.compare_digest` to prevent timing attacks.
* **Tenant Re-Derivation:** The callback payload is untrusted. The API loads the original `AutomationJob` record using a superuser session, retrieves the true `organization_id` and `user_id` from the database, and processes the results in that verified tenant context.
  * *Code reference:* `apps/api/src/modules/automation_ingress/router.py#L90-L162`.

## Primary Entry Points
* **Router:** `apps/api/src/modules/automation_ingress/router.py`
  * `POST /automation-jobs` - Creates a job record and dispatches a Celery task (Admin only).
  * `POST /internal/automation/callback` - Authenticates and processes the signed callback payload from the worker (Public, HMAC-signed).

## Operational Gotchas & DB Locking
* **Raw Body Reading:** The signature must be computed against the raw, unparsed request bytes. Accessing `request.body()` inside FastAPI requires careful handling to avoid reading issues in downstream dependencies.
* **No Database Credentials on Worker:** The Celery worker must never be configured with the database URL. Any attempt to import database model modules or execute queries on the worker will violate network isolation and security boundaries.
