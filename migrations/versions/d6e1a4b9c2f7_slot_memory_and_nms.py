"""ช่องจำรถ (slot memory) + เกณฑ์ NMS รายกล้อง

Revision ID: d6e1a4b9c2f7
Revises: c3f9a2d84e17
Create Date: 2026-11-02 17:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e1a4b9c2f7'
down_revision: Union[str, Sequence[str], None] = 'c3f9a2d84e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # nms_threshold NULL = ใช้ค่าเริ่ม 0.45 เหมือนเดิม · ช่องจำรถเปิดให้ทุกกล้องเดิม (ปิดรายกล้องได้)
    op.add_column('cameras', sa.Column('nms_threshold', sa.Float(), nullable=True))
    op.add_column('cameras', sa.Column('slot_memory_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('slot_state', sa.Column('memory_sig', sa.Text(), nullable=True))
    op.add_column('slot_state', sa.Column('held_since', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('slot_state') as batch_op:
        batch_op.drop_column('held_since')
        batch_op.drop_column('memory_sig')
    with op.batch_alter_table('cameras') as batch_op:
        batch_op.drop_column('slot_memory_enabled')
        batch_op.drop_column('nms_threshold')
