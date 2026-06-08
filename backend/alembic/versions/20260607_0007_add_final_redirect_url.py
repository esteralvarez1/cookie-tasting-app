"""add final_redirect_url to tasting_session_configs

Revision ID: 20260607_0007
Revises: 20260515_0006
Create Date: 2026-06-07 00:00:00

Adds:
  - tasting_session_configs.final_redirect_url: optional URL shown to the
    participant after they complete the final survey, so they can be redirected
    to an external link configured by the administrator.
"""
from alembic import op

revision = '20260607_0007'
down_revision = '20260515_0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tasting_session_configs
        ADD COLUMN IF NOT EXISTS final_redirect_url VARCHAR(2000)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE tasting_session_configs
        DROP COLUMN IF EXISTS final_redirect_url
    """)
