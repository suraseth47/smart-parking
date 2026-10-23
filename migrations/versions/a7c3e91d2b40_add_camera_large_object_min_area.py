"""add camera.large_object_min_area (โหมดนับวัตถุขนาดใหญ่เป็นรถ)

Revision ID: a7c3e91d2b40
Revises: 6cd7ed65a0ee
Create Date: 2026-10-23 14:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91d2b40'
down_revision: Union[str, Sequence[str], None] = '6cd7ed65a0ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # nullable: กล้องเดิมทั้งหมดได้ค่า NULL = ปิดโหมดนี้ (ทำงานเหมือนเดิมทุกอย่าง)
    op.add_column('cameras', sa.Column('large_object_min_area', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('cameras') as batch_op:
        batch_op.drop_column('large_object_min_area')
