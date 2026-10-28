"""หลายสถานที่ (TOR 4.6): ตาราง sites + zones/cameras.site_id + สิทธิ์รายสถานที่ของผู้ใช้/คำเชิญ

ข้อมูลเดิมทั้งหมดถูกย้ายเข้า "สถานที่หลัก" 1 แห่ง (ชื่อจาก SITE_NAME_TH/EN ใน .env) ระบบเดิมใช้ต่อได้ทันที

Revision ID: c3f9a2d84e17
Revises: b8e2c5f71a09
Create Date: 2026-10-28 08:00:00

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f9a2d84e17'
down_revision: Union[str, Sequence[str], None] = 'b8e2c5f71a09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name_th', sa.String(length=100), nullable=False),
        sa.Column('name_en', sa.String(length=100), nullable=False),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('opening_hours', sa.String(length=100), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_sites_code', 'sites', ['code'], unique=True)
    op.add_column('zones', sa.Column('site_id', sa.Integer(), nullable=True))
    op.create_index('ix_zones_site_id', 'zones', ['site_id'])
    op.add_column('cameras', sa.Column('site_id', sa.Integer(), nullable=True))
    op.create_index('ix_cameras_site_id', 'cameras', ['site_id'])
    op.add_column('users', sa.Column('site_ids', sa.JSON(), nullable=True))
    op.add_column('invitations', sa.Column('site_ids', sa.JSON(), nullable=True))

    # ย้ายข้อมูลเดิมเข้าสถานที่หลัก
    name_th = os.environ.get('SITE_NAME_TH', 'ลานจอดรถ')
    name_en = os.environ.get('SITE_NAME_EN', 'Parking')
    bind = op.get_bind()
    bind.execute(
        sa.text("INSERT INTO sites (code, name_th, name_en, sort_order, is_public) VALUES ('MAIN', :th, :en, 1, 1)"),
        {"th": name_th, "en": name_en},
    )
    site_id = bind.execute(sa.text("SELECT id FROM sites WHERE code = 'MAIN'")).scalar()
    bind.execute(sa.text("UPDATE zones SET site_id = :s WHERE site_id IS NULL"), {"s": site_id})
    bind.execute(sa.text("UPDATE cameras SET site_id = :s WHERE site_id IS NULL"), {"s": site_id})

    # รหัสโซน/รหัสช่อง: จากเดิมห้ามซ้ำทั้งระบบ -> ห้ามซ้ำภายในสถานที่/โซน (แต่ละแห่งใช้โซน A, ช่อง A-01 ของตัวเองได้)
    op.drop_index('ix_zones_code', table_name='zones')
    op.create_index('ix_zones_code', 'zones', ['code'], unique=False)
    op.create_index('ix_zones_site_code', 'zones', ['site_id', 'code'], unique=True)
    op.drop_index('ix_slots_code', table_name='slots')
    op.create_index('ix_slots_code', 'slots', ['code'], unique=False)
    op.create_index('ix_slots_zone_code', 'slots', ['zone_id', 'code'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_slots_zone_code', table_name='slots')
    op.drop_index('ix_slots_code', table_name='slots')
    op.create_index('ix_slots_code', 'slots', ['code'], unique=True)
    op.drop_index('ix_zones_site_code', table_name='zones')
    op.drop_index('ix_zones_code', table_name='zones')
    op.create_index('ix_zones_code', 'zones', ['code'], unique=True)
    with op.batch_alter_table('invitations') as batch_op:
        batch_op.drop_column('site_ids')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('site_ids')
    op.drop_index('ix_cameras_site_id', table_name='cameras')
    with op.batch_alter_table('cameras') as batch_op:
        batch_op.drop_column('site_id')
    op.drop_index('ix_zones_site_id', table_name='zones')
    with op.batch_alter_table('zones') as batch_op:
        batch_op.drop_column('site_id')
    op.drop_index('ix_sites_code', table_name='sites')
    op.drop_table('sites')
