"""add camera.roi_auto_margin (ROI อัตโนมัติจากช่องจอด, FR-4)

Revision ID: c4d8f2a61e93
Revises: a7c3e91d2b40
Create Date: 2026-10-23 16:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d8f2a61e93'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91d2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # nullable: กล้องเดิมทั้งหมดได้ค่า NULL = ปิด ROI (ใช้ภาพเต็มเหมือนเดิมทุกอย่าง)
    op.add_column('cameras', sa.Column('roi_auto_margin', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('cameras') as batch_op:
        batch_op.drop_column('roi_auto_margin')
