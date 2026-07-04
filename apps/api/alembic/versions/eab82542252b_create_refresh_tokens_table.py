"""create_refresh_tokens_table

Revision ID: eab82542252b
Revises: 936c1edda95e
Create Date: 2026-07-04 14:22:58.111349

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eab82542252b'
down_revision: Union[str, Sequence[str], None] = '936c1edda95e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash')
    )
    # Grant permissions to hrms_app role
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO hrms_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('refresh_tokens')
