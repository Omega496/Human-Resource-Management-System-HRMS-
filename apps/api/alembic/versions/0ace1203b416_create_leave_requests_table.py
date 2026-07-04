"""create_leave_requests_table

Revision ID: 0ace1203b416
Revises: 200f686efb5d
Create Date: 2026-07-04 14:42:19.153253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ace1203b416'
down_revision: Union[str, Sequence[str], None] = '200f686efb5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.execute("""
    CREATE TABLE leave_requests (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id  UUID NOT NULL REFERENCES organizations(id),
        employee_id      UUID NOT NULL REFERENCES employees(id),
        start_time       TIMESTAMPTZ NOT NULL,
        end_time         TIMESTAMPTZ NOT NULL,
        status           TEXT NOT NULL DEFAULT 'pending',
        period           TSTZRANGE GENERATED ALWAYS AS (tstzrange(start_time, end_time, '[]')) STORED,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT valid_leave_range CHECK (end_time > start_time)
    )
    """)

    op.execute("ALTER TABLE leave_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_requests FORCE ROW LEVEL SECURITY")

    op.execute("""
    CREATE POLICY tenant_isolation_leave_requests ON leave_requests
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    op.execute("""
    ALTER TABLE leave_requests
        ADD CONSTRAINT no_overlapping_active_leave
        EXCLUDE USING gist (
            employee_id WITH =,
            period WITH &&
        ) WHERE (status IN ('pending', 'approved'))
    """)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON leave_requests TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("leave_requests")
