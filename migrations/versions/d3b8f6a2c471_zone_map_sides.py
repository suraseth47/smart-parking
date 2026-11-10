"""ป้ายรอบลาน (บน / ล่าง / ซ้าย / ขวา) ในผังหน้าบ้านของลานจอดรถหน้าสำนักงานเทศบาล

เติมให้เฉพาะโซนที่ยังใช้ผังเริ่มต้นจาก c9e4a1f7b352 อยู่ (ยังไม่มีใครแก้) — แก้ต่อได้ที่ โซนและการปิดโซน → ผังหน้าบ้าน

Revision ID: d3b8f6a2c471
Revises: c9e4a1f7b352
Create Date: 2026-11-10 22:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3b8f6a2c471'
down_revision: Union[str, Sequence[str], None] = 'c9e4a1f7b352'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_DEFAULT = (
    "# มองจากฝั่งกล้อง/ทางเข้า (ล่างจอ) เข้าไปด้านใน (บนจอ)\n"
    "A-07..A-01 เริ่ม 3\n"
    "| ทางวิ่งรถ (ห้ามจอด)\n"
    "A-16..A-08\n"
    "A-21..A-17 เริ่ม 3\n"
)
SIDES = (
    "บน: ด้านในลาน\n"
    "ล่าง: ทางเข้า · ฝั่งกล้อง\n"
    "ซ้าย: รั้ว · ถนน\n"
    "ขวา: 🏢 อาคารสำนักงานเทศบาล\n"
)


def upgrade() -> None:
    """Upgrade data."""
    op.get_bind().execute(
        sa.text("UPDATE zones SET map_layout = :new WHERE map_layout = :old"),
        {"new": OLD_DEFAULT + SIDES, "old": OLD_DEFAULT},
    )


def downgrade() -> None:
    """Downgrade data."""
    op.get_bind().execute(
        sa.text("UPDATE zones SET map_layout = :old WHERE map_layout = :new"),
        {"new": OLD_DEFAULT + SIDES, "old": OLD_DEFAULT},
    )
