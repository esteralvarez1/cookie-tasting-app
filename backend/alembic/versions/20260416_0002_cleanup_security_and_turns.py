"""cleanup token storage and remove suggested_next_action

Revision ID: 20260416_0002
Revises: 20260406_0001
Create Date: 2026-04-16 16:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '20260416_0002'
down_revision = '20260406_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tasting_sessions') as batch_op:
        batch_op.add_column(sa.Column('session_token_hash', sa.String(length=128), nullable=True))

    with op.batch_alter_table('sample_evaluations') as batch_op:
        batch_op.add_column(sa.Column('next_turn_index', sa.Integer(), nullable=False, server_default='1'))

    with op.batch_alter_table('evaluation_analyses') as batch_op:
        batch_op.drop_column('suggested_next_action')


def downgrade() -> None:
    with op.batch_alter_table('evaluation_analyses') as batch_op:
        batch_op.add_column(sa.Column('suggested_next_action', sa.String(length=50), nullable=True))

    with op.batch_alter_table('sample_evaluations') as batch_op:
        batch_op.drop_column('next_turn_index')

    with op.batch_alter_table('tasting_sessions') as batch_op:
        batch_op.drop_column('session_token_hash')
