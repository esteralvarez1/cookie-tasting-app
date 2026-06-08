"""initial schema

Revision ID: 20260406_0001
Revises:
Create Date: 2026-04-06 20:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '20260406_0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'participants',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('participant_code', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('participant_code'),
    )

    op.create_table(
        'samples',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('sample_code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sample_code'),
    )

    op.create_table(
        'tasting_sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('participant_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('total_samples', sa.Integer(), nullable=False),
        sa.Column('current_sample_index', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('config_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['participant_id'], ['participants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tasting_sessions_participant_id'), 'tasting_sessions', ['participant_id'], unique=False)

    op.create_table(
        'final_survey_responses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['tasting_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id'),
    )
    op.create_index(op.f('ix_final_survey_responses_session_id'), 'final_survey_responses', ['session_id'], unique=True)

    op.create_table(
        'sample_evaluations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('sample_id', sa.String(length=36), nullable=False),
        sa.Column('presentation_order', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('current_state', sa.String(length=50), nullable=False),
        sa.Column('current_modality', sa.String(length=20), nullable=True),
        sa.Column('current_modality_attempt', sa.Integer(), nullable=False),
        sa.Column('vague_retry_count', sa.Integer(), nullable=False),
        sa.Column('comparison_retry_count', sa.Integer(), nullable=False),
        sa.Column('next_question', sa.Text(), nullable=True),
        sa.Column('accumulated_text', sa.Text(), nullable=False),
        sa.Column('initial_response_text', sa.Text(), nullable=True),
        sa.Column('exhausted_modalities_json', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['sample_id'], ['samples.id']),
        sa.ForeignKeyConstraint(['session_id'], ['tasting_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'presentation_order', name='uq_session_order'),
        sa.UniqueConstraint('session_id', 'sample_id', name='uq_session_sample'),
    )
    op.create_index(op.f('ix_sample_evaluations_sample_id'), 'sample_evaluations', ['sample_id'], unique=False)
    op.create_index(op.f('ix_sample_evaluations_session_id'), 'sample_evaluations', ['session_id'], unique=False)

    op.create_table(
        'conversation_turns',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('evaluation_id', sa.String(length=36), nullable=False),
        sa.Column('turn_index', sa.Integer(), nullable=False),
        sa.Column('speaker', sa.String(length=10), nullable=False),
        sa.Column('message_type', sa.String(length=30), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['evaluation_id'], ['sample_evaluations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('evaluation_id', 'turn_index', name='uq_eval_turn'),
    )
    op.create_index(op.f('ix_conversation_turns_evaluation_id'), 'conversation_turns', ['evaluation_id'], unique=False)

    op.create_table(
        'evaluation_analyses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('evaluation_id', sa.String(length=36), nullable=False),
        sa.Column('source_turn_id', sa.String(length=36), nullable=True),
        sa.Column('analysis_scope', sa.String(length=20), nullable=False),
        sa.Column('accumulated_text_snapshot', sa.Text(), nullable=False),
        sa.Column('is_vague', sa.Boolean(), nullable=False),
        sa.Column('has_comparison', sa.Boolean(), nullable=False),
        sa.Column('suggested_next_action', sa.String(length=50), nullable=True),
        sa.Column('effective_next_action', sa.String(length=50), nullable=True),
        sa.Column('reasoning_summary', sa.Text(), nullable=True),
        sa.Column('llm_provider', sa.String(length=50), nullable=False),
        sa.Column('llm_model', sa.String(length=100), nullable=False),
        sa.Column('prompt_version', sa.String(length=50), nullable=False),
        sa.Column('raw_response_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['evaluation_id'], ['sample_evaluations.id']),
        sa.ForeignKeyConstraint(['source_turn_id'], ['conversation_turns.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_evaluation_analyses_evaluation_id'), 'evaluation_analyses', ['evaluation_id'], unique=False)

    op.create_table(
        'modality_analyses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('analysis_id', sa.String(length=36), nullable=False),
        sa.Column('modality', sa.String(length=20), nullable=False),
        sa.Column('mentioned_flag', sa.Boolean(), nullable=False),
        sa.Column('mention_text', sa.Text(), nullable=False),
        sa.Column('descriptor_text', sa.Text(), nullable=False),
        sa.Column('valuation_text', sa.Text(), nullable=False),
        sa.Column('is_complete', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['evaluation_analyses.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('analysis_id', 'modality', name='uq_analysis_modality'),
    )
    op.create_index(op.f('ix_modality_analyses_analysis_id'), 'modality_analyses', ['analysis_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_modality_analyses_analysis_id'), table_name='modality_analyses')
    op.drop_table('modality_analyses')
    op.drop_index(op.f('ix_evaluation_analyses_evaluation_id'), table_name='evaluation_analyses')
    op.drop_table('evaluation_analyses')
    op.drop_index(op.f('ix_conversation_turns_evaluation_id'), table_name='conversation_turns')
    op.drop_table('conversation_turns')
    op.drop_index(op.f('ix_sample_evaluations_session_id'), table_name='sample_evaluations')
    op.drop_index(op.f('ix_sample_evaluations_sample_id'), table_name='sample_evaluations')
    op.drop_table('sample_evaluations')
    op.drop_index(op.f('ix_final_survey_responses_session_id'), table_name='final_survey_responses')
    op.drop_table('final_survey_responses')
    op.drop_index(op.f('ix_tasting_sessions_participant_id'), table_name='tasting_sessions')
    op.drop_table('tasting_sessions')
    op.drop_table('samples')
    op.drop_table('participants')
