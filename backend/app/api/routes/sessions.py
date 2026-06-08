from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.security import _hash_session_token, require_session_access_for_session, require_tasting_session_active
from app.models.entities import FinalSurveyResponse, Participant, SampleEvaluation, TastingSession, TastingSessionConfig
from app.models.enums import EvaluationStatus, SessionStatus
from app.schemas.sessions import SessionCreateRequest, SurveyRequest

router = APIRouter(prefix='/sessions', tags=['sessions'])

_SESSION_RATE_LIMIT = f'{settings.rate_limit_sessions_per_minute}/minute'


@router.post('', status_code=status.HTTP_201_CREATED)
@limiter.limit(_SESSION_RATE_LIMIT)
def create_session(request: Request, payload: SessionCreateRequest, db: Session = Depends(get_db)) -> dict:
    config = db.scalar(select(TastingSessionConfig).where(TastingSessionConfig.id == payload.tasting_session_id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tasting session not found')
    if config.status != 'ACTIVE':
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Tasting session is not active')

    participant = db.scalar(select(Participant).where(Participant.participant_code == payload.participant_code))
    if not participant:
        participant = Participant(participant_code=payload.participant_code)
        db.add(participant)
        db.flush()

    # Recover existing session for the same participant + tasting config
    existing_session = db.scalar(
        select(TastingSession)
        .options(selectinload(TastingSession.evaluations).selectinload(SampleEvaluation.sample))
        .where(
            TastingSession.participant_id == participant.id,
            TastingSession.admin_session_id == config.id,
        )
    )
    if existing_session:
        # Issue a fresh token so the participant can always resume (even if the old token expired)
        new_token = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=settings.session_token_ttl_hours)
        existing_session.session_token_hash = _hash_session_token(new_token)
        existing_session.config_json = {
            **(existing_session.config_json or {}),
            'session_token_expires_at': expires_at.isoformat(),
        }
        db.commit()
        completed_codes = [
            ev.sample.sample_code for ev in existing_session.evaluations
            if ev.status == EvaluationStatus.COMPLETED.value
        ]
        pending_codes = [c for c in config.sample_codes_json if c not in completed_codes]
        return {
            'success': True,
            'data': {
                'session_id': existing_session.id,
                'participant_code': participant.participant_code,
                'tasting_session_id': config.id,
                'status': existing_session.status,
                'session_token': new_token,
                'session_token_expires_at': expires_at.isoformat(),
                'completed_sample_codes': completed_codes,
                'pending_sample_codes': pending_codes,
            },
            'message': 'Sesión recuperada correctamente',
        }

    session_token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.session_token_ttl_hours)
    total_samples = len(config.sample_codes_json)

    session = TastingSession(
        participant_id=participant.id,
        admin_session_id=config.id,
        status=SessionStatus.CREATED.value,
        total_samples=total_samples,
        current_sample_index=0,
        started_at=now,
        session_token_hash=_hash_session_token(session_token),
        config_json={'session_token_expires_at': expires_at.isoformat()},
    )
    db.add(session)
    db.commit()
    return {
        'success': True,
        'data': {
            'session_id': session.id,
            'participant_code': participant.participant_code,
            'tasting_session_id': config.id,
            'status': session.status,
            'session_token': session_token,
            'session_token_expires_at': expires_at.isoformat(),
            'completed_sample_codes': [],
            'pending_sample_codes': list(config.sample_codes_json),
        },
        'message': 'Sesión creada correctamente',
    }


@router.get('/{session_id}/next-step')
def next_step(session_id: str, x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    require_session_access_for_session(session_id, db, x_session_token)
    session = db.scalar(
        select(TastingSession)
        .options(
            selectinload(TastingSession.evaluations).selectinload(SampleEvaluation.sample),
            selectinload(TastingSession.final_survey),
            selectinload(TastingSession.admin_session),
        )
        .where(TastingSession.id == session_id)
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    completed_evals = [e for e in session.evaluations if e.status == EvaluationStatus.COMPLETED.value]
    completed_codes = [e.sample.sample_code for e in completed_evals]
    completed = len(completed_evals)
    config_codes: list = session.admin_session.sample_codes_json if session.admin_session else []
    pending_codes = [c for c in config_codes if c not in completed_codes]

    pending_comment_eval = None
    if completed < session.total_samples:
        step = 'NEXT_SAMPLE'
    elif session.status == SessionStatus.COMPLETED.value:
        # Session explicitly marked COMPLETED: all comments saved (or legacy survey submitted).
        step = 'SESSION_COMPLETED'
    else:
        # All evaluations COMPLETED but session still IN_PROGRESS.
        # Check whether any evaluation is still waiting for its per-sample comment.
        pending_comment_eval = next(
            (e for e in completed_evals if e.final_comment is None),
            None,
        )
        step = 'SAMPLE_COMMENT' if pending_comment_eval is not None else 'SESSION_COMPLETED'

    result: dict = {
        'session_id': session.id,
        'next_step': step,
        'next_sample_index': completed + 1,
        'completed_sample_codes': completed_codes,
        'pending_sample_codes': pending_codes,
    }
    if pending_comment_eval is not None:
        result['pending_comment_evaluation_id'] = pending_comment_eval.id
        result['pending_comment_sample_code'] = pending_comment_eval.sample.sample_code

    return {
        'success': True,
        'data': result,
        'message': 'Siguiente paso calculado correctamente',
    }


@router.post('/{session_id}/survey', status_code=status.HTTP_201_CREATED)
def save_survey(
    session_id: str,
    payload: SurveyRequest,
    x_session_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    # LEGACY — not called by the current frontend.
    # The per-session global survey was removed from the participant flow.
    # Each sample now ends with a per-sample comment (POST /evaluations/{id}/final-comment).
    # After the last sample comment the frontend moves directly to the final screen.
    # This endpoint is kept for backward compatibility with older clients only.
    require_session_access_for_session(session_id, db, x_session_token)
    session = db.scalar(
        select(TastingSession)
        .options(
            selectinload(TastingSession.final_survey),
            selectinload(TastingSession.evaluations),
        )
        .where(TastingSession.id == session_id)
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    require_tasting_session_active(session, db)
    completed = sum(1 for e in session.evaluations if e.status == EvaluationStatus.COMPLETED.value)
    if completed < session.total_samples:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Cannot submit final survey before all samples are completed',
        )
    survey_dict = payload.payload.model_dump()
    if session.final_survey:
        session.final_survey.payload_json = survey_dict
        session.final_survey.completed_at = datetime.now(timezone.utc)
    else:
        survey = FinalSurveyResponse(session_id=session.id, payload_json=survey_dict)
        db.add(survey)
    session.status = SessionStatus.COMPLETED.value
    session.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {
        'success': True,
        'data': {'session_id': session.id, 'survey_saved': True, 'status': session.status},
        'message': 'Encuesta final registrada correctamente',
    }
