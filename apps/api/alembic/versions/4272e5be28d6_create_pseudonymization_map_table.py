"""create_pseudonymization_map_table

Revision ID: 4272e5be28d6
Revises: 97174933302e
Create Date: 2026-07-04 14:45:53.733610

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4272e5be28d6'
down_revision: Union[str, Sequence[str], None] = '97174933302e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE pseudonymization_map (
        original_employee_id  UUID PRIMARY KEY REFERENCES employees(id),
        organization_id       UUID NOT NULL REFERENCES organizations(id),
        pseudonym_hash        TEXT NOT NULL UNIQUE,
        structural_cohort     TEXT NOT NULL,
        pseudonymized_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        requested_by          TEXT NOT NULL
    )
    """)

    op.execute("ALTER TABLE pseudonymization_map ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pseudonymization_map FORCE ROW LEVEL SECURITY")

    op.execute("""
    CREATE POLICY tenant_isolation_pseudonymization_map ON pseudonymization_map
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON pseudonymization_map TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("pseudonymization_map")
