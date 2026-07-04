"""create_payroll_tables

Revision ID: 97174933302e
Revises: 0ace1203b416
Create Date: 2026-07-04 14:44:00.749239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97174933302e'
down_revision: Union[str, Sequence[str], None] = '0ace1203b416'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create payroll_rules table
    op.execute("""
    CREATE TABLE payroll_rules (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id   UUID NOT NULL REFERENCES organizations(id),
        rule_type         TEXT NOT NULL,
        rule_key          TEXT NOT NULL,
        rule_value        JSONB NOT NULL,
        valid_from        TIMESTAMPTZ NOT NULL,
        valid_to          TIMESTAMPTZ,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT valid_rule_range CHECK (valid_to IS NULL OR valid_to > valid_from)
    )
    """)

    op.execute("""
    CREATE INDEX idx_payroll_rules_lookup
        ON payroll_rules (organization_id, rule_type, rule_key, valid_from)
    """)

    # Exclusion constraint on payroll_rules to prevent overlapping rule validity ranges.
    # We use tstzrange(valid_from, valid_to, '[)') where a NULL upper bound represents infinity.
    op.execute("""
    ALTER TABLE payroll_rules
        ADD CONSTRAINT no_overlapping_payroll_rules
        EXCLUDE USING gist (
            organization_id WITH =,
            rule_type WITH =,
            rule_key WITH =,
            (tstzrange(valid_from, valid_to, '[)')) WITH &&
        )
    """)

    # Enable RLS on payroll_rules
    op.execute("ALTER TABLE payroll_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payroll_rules FORCE ROW LEVEL SECURITY")
    op.execute("""
    CREATE POLICY tenant_isolation_payroll_rules ON payroll_rules
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    # 2. Create payroll_ledger_lines table
    op.execute("""
    CREATE TABLE payroll_ledger_lines (
        id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id           UUID NOT NULL REFERENCES organizations(id),
        employee_id               UUID NOT NULL REFERENCES employees(id),
        ledger_month              DATE NOT NULL,
        line_type                 TEXT NOT NULL,
        amount_cents              BIGINT NOT NULL,
        currency                  CHAR(3) NOT NULL,
        status                    TEXT NOT NULL DEFAULT 'open',
        adjustment_of             UUID REFERENCES payroll_ledger_lines(id),
        computed_from_rule_id     UUID REFERENCES payroll_rules(id),
        created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
        closed_at                 TIMESTAMPTZ
    )
    """)

    # Enable RLS on payroll_ledger_lines
    op.execute("ALTER TABLE payroll_ledger_lines ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payroll_ledger_lines FORCE ROW LEVEL SECURITY")
    op.execute("""
    CREATE POLICY tenant_isolation_payroll_ledger_lines ON payroll_ledger_lines
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    # 3. Create closed-ledger immutability trigger function and trigger
    op.execute("""
    CREATE OR REPLACE FUNCTION prevent_closed_ledger_mutation() RETURNS TRIGGER AS $$
    BEGIN
        IF OLD.status = 'closed' THEN
            RAISE EXCEPTION 'payroll_ledger_lines % is closed and cannot be modified (month=%)',
                OLD.id, OLD.ledger_month
                USING ERRCODE = 'raise_exception';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)

    op.execute("""
    CREATE TRIGGER trg_prevent_closed_ledger_mutation
        BEFORE UPDATE OR DELETE ON payroll_ledger_lines
        FOR EACH ROW EXECUTE FUNCTION prevent_closed_ledger_mutation()
    """)

    # 4. Grants to app role
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_rules TO hrms_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_ledger_lines TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_closed_ledger_mutation ON payroll_ledger_lines")
    op.execute("DROP FUNCTION IF EXISTS prevent_closed_ledger_mutation")
    op.drop_table("payroll_ledger_lines")
    op.drop_table("payroll_rules")
