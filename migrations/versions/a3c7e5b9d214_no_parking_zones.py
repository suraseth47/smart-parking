"""เขตห้ามจอด / รถจอดซ้อนคัน (cameras.no_parking_*) + ไม่นับกล้อง/สถานที่ทดสอบ (counted)

Revision ID: a3c7e5b9d214
Revises: e8a2f5c7d913
Create Date: 2026-11-02 21:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c7e5b9d214'
down_revision: Union[str, Sequence[str], None] = 'e8a2f5c7d913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('cameras', sa.Column('no_parking_zones', sa.JSON(), nullable=True))
    op.add_column('cameras', sa.Column('no_parking_dwell_min', sa.Integer(), nullable=False, server_default='5'))
    op.add_column('cameras', sa.Column('no_parking_state', sa.JSON(), nullable=True))
    op.add_column('cameras', sa.Column('counted', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('sites', sa.Column('counted', sa.Boolean(), nullable=False, server_default='1'))
    # กล้องทดสอบไม่นับรวมยอดช่องจอด (ปรับต่อได้ที่ ตั้งค่าระบบ → การนับช่องจอด)
    test_cams = sa.table('cameras', sa.column('name', sa.String), sa.column('counted', sa.Boolean))
    op.execute(test_cams.update().where(test_cams.c.name == 'ValidationTestCam').values(counted=False))

    # เตรียมทดสอบลานหน้าเทศบาล (3 พ.ย. 2569): กล้องเทศบาลตั้ง NMS 0.65 (รถจอดชิดกัน) + เปิดช่องจำรถ
    # เฉพาะกรณียังไม่เคยตั้ง NMS เอง (ค่าว่าง) — ถ้าผู้ดูแลตั้งไว้แล้วจะไม่ทับ · ชื่อไม่ตรง = ไม่มีผลอะไร
    cameras = sa.table('cameras', sa.column('name', sa.String), sa.column('nms_threshold', sa.Float),
                       sa.column('slot_memory_enabled', sa.Boolean))
    name = 'ลานจอดรถหน้าสำนักงานเทศบาล-1'
    op.execute(cameras.update().where(cameras.c.name == name, cameras.c.nms_threshold.is_(None)).values(nms_threshold=0.65))
    op.execute(cameras.update().where(cameras.c.name == name).values(slot_memory_enabled=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('sites') as batch_op:
        batch_op.drop_column('counted')
    with op.batch_alter_table('cameras') as batch_op:
        batch_op.drop_column('counted')
        batch_op.drop_column('no_parking_state')
        batch_op.drop_column('no_parking_dwell_min')
        batch_op.drop_column('no_parking_zones')
