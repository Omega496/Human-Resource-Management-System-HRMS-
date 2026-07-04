# Invitations Module

## Domain Responsibilities & Boundary
The `invitations` module manages the lifecycle of email-bound signup invitations. It generates secure invitation links containing unique, single-use tokens, validates them upon account registration, and handles the initial creation of employee profile/auth records.

## Prime Directives Enforced
* **Directive #1 (Tenant Isolation):** The `invitations` table has PostgreSQL Row-Level Security (RLS) enabled. Admins can only view and generate invitations for their own organization.
  * *DB Policy:* Filters `WHERE organization_id = current_setting('app.current_organization_id')`.
* **Tenant Re-Derivation:** During registration (`/invitations/accept`), the client does not yet possess tenant credentials. A superuser database session retrieves the target invitation, verifies it, and creates the employee record scoped to the organization specified *by the invitation record itself*, never trusting any client-provided organization IDs.
  * *Code reference:* `apps/api/src/modules/invitations/router.py#L113-L163`.

## Primary Entry Points
* **Router:** `apps/api/src/modules/invitations/router.py`
  * `GET /invitations` - List invitations for the organization (Admin only).
  * `POST /invitations` - Create and issue a new invitation (Admin only).
  * `POST /invitations/accept` - Validate a token, claim it, and register the new employee (Public).

## Operational Gotchas & DB Locking
* **Single-Use Enforcement:** The token is hashed with SHA-256 before storage. Acceptance claims are enforced in a single transaction via a conditional update:
  ```python
  update(Invitation)
  .where(
      Invitation.id == invitation.id,
      Invitation.used_at.is_(None),
      Invitation.expires_at > datetime.now(timezone.utc),
  )
  .values(used_at=datetime.now(timezone.utc))
  ```
  If the conditional update returns zero rows, registration fails, preventing race conditions where the same link is accepted concurrently.
