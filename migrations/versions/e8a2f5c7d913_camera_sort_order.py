"""ลำดับการแสดงกล้อง (cameras.sort_order)

Revision ID: e8a2f5c7d913
Revises: d6e1a4b9c2f7
Create Date: 2026-11-02 20:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8a2f5c7d913'
down_revision: Union[str, Sequence[str], None] = 'd6e1a4b9c2f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # กล้องเดิมได้ 100 เท่ากันหมด = เรียงตาม id เหมือนเดิม (ปรับได้ในฟอร์มแก้ไขกล้อง)
    op.add_column('cameras', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='100'))
    # ลำดับที่ผู้ดูแลขอ (2 พ.ย. 2569): กล้องวัดปากคลองก่อน · ลานจอดเทศบาลถัดไป · กล้องทดสอบไว้ล่างสุด
    # (ชื่อไม่ตรง = ไม่มีผลอะไร · ปรับต่อได้ที่ฟอร์มแก้ไขกล้อง → ลำดับการแสดง)
    cameras = sa.table('cameras', sa.column('name', sa.String), sa.column('sort_order', sa.Integer))
    for name, order in (('Cam1-AI_Outdoor', 1), ('ลานจอดรถหน้าสำนักงานเทศบาล-1', 2), ('ValidationTestCam', 999)):
        op.execute(cameras.update().where(cameras.c.name == name).values(sort_order=order))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('cameras') as batch_op:
        batch_op.drop_column('sort_order')
