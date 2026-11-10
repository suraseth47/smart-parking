"""ผังช่องจอดหน้าสาธารณะแบบกำหนดเอง (zones.map_layout)

ใส่ผังเริ่มต้นให้โซนที่มีช่อง A-01..A-21 ครบพอดี (ลานจอดรถหน้าสำนักงานเทศบาลเมืองสระบุรี)
ให้ตรงกับภาพจริง: แถวซ้ายชิดกำแพง A-07→A-01 · ทางวิ่ง/เขตห้ามจอด · แถวกลาง A-16→A-08 · แถวขวาชิดขอบทาง A-21→A-17
(เฉพาะโซนที่ยังไม่มีผัง — แก้ภายหลังได้ที่ โซนและการปิดโซน → ผังหน้าบ้าน)

Revision ID: c9e4a1f7b352
Revises: b7d4c2e9f135
Create Date: 2026-11-10 22:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e4a1f7b352'
down_revision: Union[str, Sequence[str], None] = 'b7d4c2e9f135'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MUNICIPAL_LAYOUT = (
    "# มองจากฝั่งกล้อง/ทางเข้า (ล่างจอ) เข้าไปด้านใน (บนจอ)\n"
    "A-07..A-01 เริ่ม 3\n"
    "| ทางวิ่งรถ (ห้ามจอด)\n"
    "A-16..A-08\n"
    "A-21..A-17 เริ่ม 3\n"
)
MUNICIPAL_CODES = {f"A-{i:02d}" for i in range(1, 22)}


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('zones', sa.Column('map_layout', sa.Text(), nullable=True))
    conn = op.get_bind()
    zone_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM zones WHERE map_layout IS NULL"))]
    for zone_id in zone_ids:
        codes = {r[0] for r in conn.execute(
            sa.text("SELECT code FROM slots WHERE zone_id = :z AND is_active = 1 AND layout_status = 'PUBLISHED'"),
            {"z": zone_id},
        )}
        if codes == MUNICIPAL_CODES:
            conn.execute(sa.text("UPDATE zones SET map_layout = :t WHERE id = :z"), {"t": MUNICIPAL_LAYOUT, "z": zone_id})


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('zones') as batch_op:
        batch_op.drop_column('map_layout')
