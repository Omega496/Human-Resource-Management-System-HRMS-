"""create_automation_jobs_table

Revision ID: b315a4e564af
Revises: 4272e5be28d6
Create Date: 2026-07-04 14:52:00.048702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b315a4e564af'
down_revision: Union[str, Sequence[str], None] = '4272e5be28d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('automation_jobs',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(), server_default='queued', nullable=False),
        sa.Column('target_url', sa.String(), nullable=False),
        sa.Column('extraction_type', sa.String(), nullable=False),
        sa.Column('result_text', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.execute("ALTER TABLE automation_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE automation_jobs FORCE ROW LEVEL SECURITY")

    op.execute("""
    CREATE POLICY tenant_isolation_automation_jobs ON automation_jobs
        USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
        WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON automation_jobs TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('automation_jobs')
