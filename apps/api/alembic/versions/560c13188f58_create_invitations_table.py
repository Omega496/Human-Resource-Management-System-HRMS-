"""create_invitations_table

Revision ID: 560c13188f58
Revises: a8c91381e607
Create Date: 2026-07-04 14:32:41.482069

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '560c13188f58'
down_revision: Union[str, Sequence[str], None] = 'a8c91381e607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


from sqlalchemy.dialects.postgresql import CITEXT


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "invitations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["invited_by"], ["employees.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash")
    )

    # Enable and force RLS
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE invitations FORCE ROW LEVEL SECURITY")

    # Add tenant isolation policy
    op.execute("""
        CREATE POLICY tenant_isolation_invitations ON invitations
            USING (organization_id = current_setting('app.current_organization_id', true)::uuid)
            WITH CHECK (organization_id = current_setting('app.current_organization_id', true)::uuid)
    """)

    # Grant permissions to hrms_app role
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON invitations TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("invitations")
