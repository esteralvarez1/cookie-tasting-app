from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TastingSessionConfig(Base):
    """Admin-created tasting session template. Participants link to this via public_token."""
    __tablename__ = 'tasting_session_configs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    public_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='ACTIVE')
    sample_codes_json: Mapped[list] = mapped_column(JSON, nullable=False)
    final_redirect_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    participant_sessions: Mapped[list['TastingSession']] = relationship(back_populates='admin_session', cascade='all, delete-orphan')


class Participant(Base):
    __tablename__ = 'participants'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    participant_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    sessions: Mapped[list['TastingSession']] = relationship(back_populates='participant')


class TastingSession(Base):
    __tablename__ = 'tasting_sessions'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    participant_id: Mapped[str] = mapped_column(ForeignKey('participants.id'), nullable=False, index=True)
    admin_session_id: Mapped[str | None] = mapped_column(ForeignKey('tasting_session_configs.id'), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    total_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    current_sample_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # config_json stores session-level metadata. Current keys:
    #   session_token_expires_at (str, ISO 8601): token expiry timestamp set at session creation.
    #   session_token (str, legacy): plain token stored before migration 0002 introduced hashing.
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    participant: Mapped['Participant'] = relationship(back_populates='sessions')
    admin_session: Mapped['TastingSessionConfig | None'] = relationship(back_populates='participant_sessions')
    evaluations: Mapped[list['SampleEvaluation']] = relationship(back_populates='session', cascade='all, delete-orphan')
    final_survey: Mapped['FinalSurveyResponse | None'] = relationship(back_populates='session', uselist=False, cascade='all, delete-orphan')


class Sample(Base):
    __tablename__ = 'samples'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sample_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    evaluations: Mapped[list['SampleEvaluation']] = relationship(back_populates='sample')


class SampleEvaluation(Base):
    __tablename__ = 'sample_evaluations'
    __table_args__ = (
        UniqueConstraint('session_id', 'sample_id', name='uq_session_sample'),
        UniqueConstraint('session_id', 'presentation_order', name='uq_session_order'),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey('tasting_sessions.id'), nullable=False, index=True)
    sample_id: Mapped[str] = mapped_column(ForeignKey('samples.id'), nullable=False, index=True)
    presentation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    current_state: Mapped[str] = mapped_column(String(50), nullable=False)
    current_modality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    current_modality_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vague_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comparison_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    accumulated_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    initial_response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    exhausted_modalities_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    modality_attempts_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    session: Mapped['TastingSession'] = relationship(back_populates='evaluations')
    sample: Mapped['Sample'] = relationship(back_populates='evaluations')
    turns: Mapped[list['ConversationTurn']] = relationship(back_populates='evaluation', cascade='all, delete-orphan')
    analyses: Mapped[list['EvaluationAnalysis']] = relationship(back_populates='evaluation', cascade='all, delete-orphan')


class ConversationTurn(Base):
    __tablename__ = 'conversation_turns'
    __table_args__ = (UniqueConstraint('evaluation_id', 'turn_index', name='uq_eval_turn'),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('sample_evaluations.id'), nullable=False, index=True)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(10), nullable=False)
    message_type: Mapped[str] = mapped_column(String(30), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    evaluation: Mapped['SampleEvaluation'] = relationship(back_populates='turns')


class EvaluationAnalysis(Base):
    __tablename__ = 'evaluation_analyses'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('sample_evaluations.id'), nullable=False, index=True)
    source_turn_id: Mapped[str | None] = mapped_column(ForeignKey('conversation_turns.id', ondelete='SET NULL'), nullable=True)
    analysis_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    accumulated_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    is_vague: Mapped[bool] = mapped_column(Boolean, nullable=False)
    has_comparison: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effective_next_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    evaluation: Mapped['SampleEvaluation'] = relationship(back_populates='analyses')
    modalities: Mapped[list['ModalityAnalysis']] = relationship(back_populates='analysis', cascade='all, delete-orphan')


class ModalityAnalysis(Base):
    __tablename__ = 'modality_analyses'
    __table_args__ = (UniqueConstraint('analysis_id', 'modality', name='uq_analysis_modality'),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(ForeignKey('evaluation_analyses.id'), nullable=False, index=True)
    modality: Mapped[str] = mapped_column(String(20), nullable=False)
    mention_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    descriptor_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    valuation_text: Mapped[str] = mapped_column(Text, nullable=False, default='')
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    analysis: Mapped['EvaluationAnalysis'] = relationship(back_populates='modalities')


class FinalSurveyResponse(Base):
    __tablename__ = 'final_survey_responses'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey('tasting_sessions.id'), nullable=False, unique=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    session: Mapped['TastingSession'] = relationship(back_populates='final_survey')
