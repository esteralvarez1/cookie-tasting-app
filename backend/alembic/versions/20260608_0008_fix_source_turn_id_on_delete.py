"""fix evaluation_analyses.source_turn_id FK to ON DELETE SET NULL

Revision ID: 20260608_0008
Revises: 20260607_0007
Create Date: 2026-06-08 00:00:00

Problem:
  DELETE on tasting_session_configs with LLM-analysed sessions failed with
  ForeignKeyViolation on evaluation_analyses_source_turn_id_fkey.

  evaluation_analyses.source_turn_id references conversation_turns.id, but
  both tables are children of sample_evaluations. The SQLAlchemy ORM unit-of-
  work does not guarantee that evaluation_analyses rows are deleted before
  conversation_turns rows when both cascades fire in the same flush, because
  the source_turn_id FK is a lateral cross-reference between sibling tables.

Fix:
  Recreate the FK with ON DELETE SET NULL. When PostgreSQL deletes a
  conversation_turns row, it automatically nullifies source_turn_id on any
  referencing evaluation_analyses row. The analysis row is then deleted later
  in the same transaction via the ORM cascade from sample_evaluations.analyses.

  The column is already nullable=True, so SET NULL is semantically correct.
"""
from alembic import op

revision = '20260608_0008'
down_revision = '20260607_0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('evaluation_analyses') as batch_op:
        batch_op.drop_constraint(
            'evaluation_analyses_source_turn_id_fkey',
            type_='foreignkey',
        )
        batch_op.create_foreign_key(
            'evaluation_analyses_source_turn_id_fkey',
            'conversation_turns',
            ['source_turn_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('evaluation_analyses') as batch_op:
        batch_op.drop_constraint(
            'evaluation_analyses_source_turn_id_fkey',
            type_='foreignkey',
        )
        batch_op.create_foreign_key(
            'evaluation_analyses_source_turn_id_fkey',
            'conversation_turns',
            ['source_turn_id'],
            ['id'],
        )
