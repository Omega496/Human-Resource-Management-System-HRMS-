# ADR-0001: GDPR Pseudonymization Pepper Storage

- **Status**: Accepted
- **Context**: 
  The GDPR "Right to be Forgotten" (Article 17) requires that personal data of terminated employees be fully erased or anonymized upon request. However, to preserve the mathematical and structural integrity of historical payroll logs for financial audits, some connection must exist between the redacted records without exposing the employee's original personal identifying information (PII).
  
  The system architecture mandates "a deterministic, cryptographically peppered/salted hash stored securely outside the database." A deterministic hash requires a secret pepper key to prevent dictionary and brute-force search attacks against the hashes. If the pepper key is stored in the database, a database compromise would expose both the hashes and the key, allowing an attacker to reconstruct the employee IDs. 
  
  Therefore, we need to define the exact storage mechanism, cryptographic algorithm, and configuration pattern for the pseudonymization pepper key.

- **Decision**:
  1. **Algorithmic Standard**: We will use HMAC-SHA256 to compute the deterministic pseudonym hash from the employee ID.
  2. **Secret Pepper Location**: The pepper key will live strictly outside the PostgreSQL database. It will be loaded at runtime from a secure environment variable (`GDPR_PSEUDONYMIZATION_PEPPER`) populated by the infrastructure's secrets management provider (e.g., AWS Secrets Manager or HashiCorp Vault).
  3. **No Local Persistence**: The pepper key must never be logged, persisted to disk, or committed to version control.
  4. **Database Storage**: Only the resulting SHA-256 hash output will be saved in `pseudonymization_map.pseudonym_hash`.

- **Consequences**:
  - *Benefits*:
    - Strictly upholds **Prime Directive #5** (GDPR Soft-Deletes & Anonymization) and safeguards employee anonymity even in the event of a full database leak.
    - Preserves deterministic mapping for financial audits and structural cohort calculations without exposing PII.
  - *Trade-offs*:
    - Introduces a dependency on external secrets orchestration during deployment.
    - Loss of the pepper key is irreversible: if the pepper key is rotated or lost, historical pseudonymized records can never be re-linked to their cohorts or audited, making key backup/recovery critical.

- **Alternatives considered**:
  - *Storing the pepper in a secure database configuration table*: Rejected because any SQL injection or database backup leak would compromise the pepper key.
  - *Generating a unique random salt per employee*: Rejected because the hashes would no longer be deterministic across tables, preventing the finance team from performing audit reconciliations by cohort.
