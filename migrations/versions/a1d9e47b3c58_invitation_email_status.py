"""invitations: สถานะการส่งอีเมลโดยระบบ (SMTP)

Revision ID: a1d9e47b3c58
Revises: f5c3d18e7a26
Create Date: 2026-10-23 17:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1d9e47b3c58'
down_revision: Union[str, Sequence[str], None] = 'f5c3d18e7a26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('invitations', sa.Column('email_status', sa.String(length=10), nullable=True))
    op.add_column('invitations', sa.Column('email_error', sa.String(length=255), nullable=True))
    op.add_column('invitations', sa.Column('email_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('invitations') as batch_op:
        batch_op.drop_column('email_sent_at')
        batch_op.drop_column('email_error')
        batch_op.drop_column('email_status')
