"""อีเมลแจ้งเตือนผู้ดูแล (alerts.emailed_at, alerts.resolved_emailed_at)

Revision ID: b7d4c2e9f135
Revises: a3c7e5b9d214
Create Date: 2026-11-02 22:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4c2e9f135'
down_revision: Union[str, Sequence[str], None] = 'a3c7e5b9d214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('alerts', sa.Column('emailed_at', sa.DateTime(), nullable=True))
    op.add_column('alerts', sa.Column('resolved_emailed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('alerts') as batch_op:
        batch_op.drop_column('resolved_emailed_at')
        batch_op.drop_column('emailed_at')
