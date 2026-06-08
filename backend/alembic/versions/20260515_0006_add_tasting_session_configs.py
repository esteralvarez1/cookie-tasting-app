"""add tasting_session_configs, admin_session_id FK, and final_comment

Revision ID: 20260515_0006
Revises: 20260512_0005
Create Date: 2026-05-15 00:00:00

Adds:
  - tasting_session_configs table: admin-created tasting session templates with public token
  - tasting_sessions.admin_session_id: nullable FK linking participant sessions to their config
  - sample_evaluations.final_comment: nullable per-sample comment saved after evaluation
"""
from alembic import op
import sqlalchemy as sa

revision = '20260515_0006'
down_revision = '20260512_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tasting_session_configs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('public_token', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('sample_codes_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('public_token'),
    )

    op.add_column(
        'tasting_sessions',
        sa.Column('admin_session_id', sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        'fk_tasting_sessions_admin_session_id',
        'tasting_sessions', 'tasting_session_configs',
        ['admin_session_id'], ['id'],
    )
    op.create_index(
        'ix_tasting_sessions_admin_session_id',
        'tasting_sessions', ['admin_session_id'],
        unique=False,
    )

    op.add_column(
        'sample_evaluations',
        sa.Column('final_comment', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('sample_evaluations', 'final_comment')
    op.drop_index('ix_tasting_sessions_admin_session_id', table_name='tasting_sessions')
    op.drop_constraint('fk_tasting_sessions_admin_session_id', 'tasting_sessions', type_='foreignkey')
    op.drop_column('tasting_sessions', 'admin_session_id')
    op.drop_table('tasting_session_configs')
