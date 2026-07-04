"""create_clock_events_table

Revision ID: 200f686efb5d
Revises: 560c13188f58
Create Date: 2026-07-04 14:35:50.018010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '200f686efb5d'
down_revision: Union[str, Sequence[str], None] = '560c13188f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "clock_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("employee_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("event_type IN ('clock_in', 'clock_out')", name="chk_clock_events_event_type"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id")
    )

    # Enable and force RLS
    op.execute("ALTER TABLE clock_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clock_events FORCE ROW LEVEL SECURITY")

    # Add tenant isolation policy
    op.execute("""
        CREATE POLICY tenant_isolation_clock_events ON clock_events
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    # Grant permissions to hrms_app role
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON clock_events TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("clock_events")
