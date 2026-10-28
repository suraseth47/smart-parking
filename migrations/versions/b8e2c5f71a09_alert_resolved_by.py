"""alerts: บันทึกผู้กดรับทราบ/ปิดแจ้งเตือน (resolved_by)

Revision ID: b8e2c5f71a09
Revises: a1d9e47b3c58
Create Date: 2026-10-28 07:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2c5f71a09'
down_revision: Union[str, Sequence[str], None] = 'a1d9e47b3c58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('alerts', sa.Column('resolved_by', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('alerts') as batch_op:
        batch_op.drop_column('resolved_by')
