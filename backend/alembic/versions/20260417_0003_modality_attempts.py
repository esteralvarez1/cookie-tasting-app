"""add modality attempts json to sample evaluations

Revision ID: 20260417_0003
Revises: 20260416_0002
Create Date: 2026-04-17 14:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '20260417_0003'
down_revision = '20260416_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sample_evaluations') as batch_op:
        batch_op.add_column(sa.Column('modality_attempts_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sample_evaluations') as batch_op:
        batch_op.drop_column('modality_attempts_json')
