"""add trigger to enforce max evaluations per session

Revision ID: 20260512_0005
Revises: 20260421_0004
Create Date: 2026-05-12 00:00:00

Adds a BEFORE INSERT trigger on sample_evaluations that raises an error if
inserting a new row would exceed the total_samples limit declared in the
parent tasting_session. Application-level validation already exists in
create_evaluation; this trigger is an additional DB-level safety net.

PostgreSQL 16 required (same version as docker-compose.yml).
"""
from alembic import op

revision = '20260512_0005'
down_revision = '20260421_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION check_max_evaluations_per_session()
        RETURNS TRIGGER AS $$
        DECLARE
            v_total        INT;
            v_current_count INT;
        BEGIN
            SELECT total_samples
              INTO v_total
              FROM tasting_sessions
             WHERE id = NEW.session_id;

            SELECT COUNT(*)
              INTO v_current_count
              FROM sample_evaluations
             WHERE session_id = NEW.session_id;

            IF v_current_count >= v_total THEN
                RAISE EXCEPTION
                    'Session % already has % evaluation(s); total_samples limit is %',
                    NEW.session_id, v_current_count, v_total
                    USING ERRCODE = 'check_violation';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_check_max_evaluations ON sample_evaluations;
        CREATE TRIGGER trg_check_max_evaluations
        BEFORE INSERT ON sample_evaluations
        FOR EACH ROW EXECUTE FUNCTION check_max_evaluations_per_session();
    """)


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_check_max_evaluations ON sample_evaluations;')
    op.execute('DROP FUNCTION IF EXISTS check_max_evaluations_per_session();')
