"""สิทธิ์รายเมนู (users/invitations.permissions) + วิธีส่งและข้อความของคำเชิญ

Revision ID: f5c3d18e7a26
Revises: e2b7a90c5d14
Create Date: 2026-10-23 16:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5c3d18e7a26'
down_revision: Union[str, Sequence[str], None] = 'e2b7a90c5d14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NULL = สิทธิ์ตามบทบาท ผู้ใช้เดิมทั้งหมดจึงได้สิทธิ์เหมือนเดิมทุกอย่าง
    op.add_column('users', sa.Column('permissions', sa.JSON(), nullable=True))
    op.add_column('invitations', sa.Column('permissions', sa.JSON(), nullable=True))
    op.add_column('invitations', sa.Column('method', sa.String(length=10), nullable=False, server_default='link'))
    op.add_column('invitations', sa.Column('message', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('invitations') as batch_op:
        batch_op.drop_column('message')
        batch_op.drop_column('method')
        batch_op.drop_column('permissions')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('permissions')
