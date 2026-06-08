"""drop mentioned_flag from modality_analyses

Revision ID: 20260421_0004
Revises: 20260417_0003
Create Date: 2026-04-21 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '20260421_0004'
down_revision = '20260417_0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('modality_analyses') as batch_op:
        batch_op.drop_column('mentioned_flag')


def downgrade() -> None:
    with op.batch_alter_table('modality_analyses') as batch_op:
        batch_op.add_column(sa.Column('mentioned_flag', sa.Boolean(), nullable=False, server_default=sa.false()))
