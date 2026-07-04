"""add_password_hash_to_employees

Revision ID: a8c91381e607
Revises: eab82542252b
Create Date: 2026-07-04 14:23:26.111349

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8c91381e607'
down_revision: Union[str, Sequence[str], None] = 'eab82542252b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'employees',
        sa.Column('password_hash', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('employees', 'password_hash')
