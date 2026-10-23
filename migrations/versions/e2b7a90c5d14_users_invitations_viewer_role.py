"""users: full_name/email + invitations table + บทบาท viewer

Revision ID: e2b7a90c5d14
Revises: c4d8f2a61e93
Create Date: 2026-10-23 16:30:00

หมายเหตุ: role เก็บเป็นข้อความ (native_enum=False, ไม่มี CHECK constraint) จึงเพิ่มค่า VIEWER
ได้โดยไม่ต้องแก้คอลัมน์เดิม
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7a90c5d14'
down_revision: Union[str, Sequence[str], None] = 'c4d8f2a61e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('full_name', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('email', sa.String(length=255), nullable=True))
    op.create_table(
        'invitations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('purpose', sa.Enum('INVITE', 'RESET', name='invitationpurpose', native_enum=False, length=10), nullable=False),
        sa.Column('role', sa.Enum('ADMIN', 'OPERATOR', 'VIEWER', name='userrole', native_enum=False, length=20), nullable=False),
        sa.Column('full_name', sa.String(length=100), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('target_user_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_user_id', sa.Integer(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['accepted_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_invitations_token_hash', 'invitations', ['token_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_invitations_token_hash', table_name='invitations')
    op.drop_table('invitations')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('email')
        batch_op.drop_column('full_name')
