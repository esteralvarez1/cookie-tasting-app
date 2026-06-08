from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.security import check_evaluation_access, require_admin, require_session_access_for_evaluation, require_session_access_for_session, require_tasting_session_active
from app.models.entities import EvaluationAnalysis, ModalityAnalysis, Sample, SampleEvaluation, TastingSession, TastingSessionConfig
from app.models.enums import EvaluationStatus, ModalityType, SessionStatus
from app.schemas.evaluations import DialogueRequest, EvaluationCreateRequest, FinalizeRequest, SampleCommentRequest
from app.services.dialogue import DialogueService

router = APIRouter(prefix='/evaluations', tags=['evaluations'])
service = DialogueService()

_DIALOG_RATE_LIMIT = f'{settings.rate_limit_dialog_per_minute}/minute'


def _modalities_payload(rows: list[ModalityAnalysis]) -> dict[str, dict[str, object]]:
    indexed = {row.modality: row for row in rows}
    payload: dict[str, dict[str, object]] = {}
    for modality in ModalityType:
        row = indexed.get(modality.value)
        payload[modality.value] = {
            'mention_text': row.mention_text if row else '',
            'descriptor_text': row.descriptor_text if row else '',
            'valuation_text': row.valuation_text if row else '',
            'is_complete': row.is_complete if row else False,
        }
    return payload


def _serialize_evaluation(evaluation: SampleEvaluation) -> dict[str, object]:
    return {
        'evaluation_id': evaluation.id,
        'session_id': evaluation.session_id,
        'sample_code': evaluation.sample.sample_code,
        'presentation_order': evaluation.presentation_order,
        'status': evaluation.status,
        'current_state': evaluation.current_state,
        'current_modality': evaluation.current_modality,
        'next_question': evaluation.next_question,
    }


def _get_evaluation(db: Session, evaluation_id: str) -> SampleEvaluation:
    evaluation = db.scalar(
        select(SampleEvaluation)
        .options(
            selectinload(SampleEvaluation.sample),
            selectinload(SampleEvaluation.session).selectinload(TastingSession.participant),
            selectinload(SampleEvaluation.session).selectinload(TastingSession.final_survey),
            selectinload(SampleEvaluation.session).selectinload(TastingSession.admin_session),
            selectinload(SampleEvaluation.turns),
            selectinload(SampleEvaluation.analyses).selectinload(EvaluationAnalysis.modalities),
        )
        .where(SampleEvaluation.id == evaluation_id)
    )
    if not evaluation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Evaluation not found')
    return evaluation


@router.post('', status_code=status.HTTP_201_CREATED)
def create_evaluation(payload: EvaluationCreateRequest, x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    session = require_session_access_for_session(payload.session_id, db, x_session_token)
    if session.status == SessionStatus.COMPLETED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Cannot create evaluations in a completed session')
    require_tasting_session_active(session, db)

    # Validate that the requested sample_code belongs to this tasting session config.
    # Must run before any DB writes to avoid creating orphan Sample records.
    if session.admin_session_id:
        config = db.scalar(select(TastingSessionConfig).where(TastingSessionConfig.id == session.admin_session_id))
        if config and payload.sample_code not in config.sample_codes_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='El código de muestra no pertenece a esta sesión de cata',
            )

    sample = db.scalar(select(Sample).where(Sample.sample_code == payload.sample_code))
    if not sample:
        sample = Sample(sample_code=payload.sample_code)
        db.add(sample)
        db.flush()

    # Check if an evaluation for this sample already exists in this session (resume or conflict)
    existing_sample = db.scalar(
        select(SampleEvaluation).where(
            SampleEvaluation.session_id == session.id,
            SampleEvaluation.sample_id == sample.id,
        )
    )
    if existing_sample:
        if existing_sample.status == EvaluationStatus.COMPLETED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='There is already a completed evaluation for that sample in this session')
        # IN_PROGRESS: return existing evaluation so the participant can resume
        resumed = _get_evaluation(db, existing_sample.id)
        return {
            'success': True,
            'data': {
                **_serialize_evaluation(resumed),
                'bot_message': resumed.next_question or '',
                'turns': service.conversation_service.serialize_turns(resumed),
            },
            'message': 'Evaluación en curso recuperada correctamente',
        }

    # Compute presentation_order transactionally from the current count of evaluations in the
    # session. This prevents frontend desync (stale localStorage, duplicate tabs, page refresh)
    # from assigning an incorrect order to experimentally significant data.
    existing_count = db.scalar(
        select(func.count()).select_from(SampleEvaluation).where(SampleEvaluation.session_id == session.id)
    )
    presentation_order = (existing_count or 0) + 1
    if presentation_order > session.total_samples:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Session already has the maximum number of evaluations')

    evaluation = SampleEvaluation(
        session_id=session.id,
        sample_id=sample.id,
        presentation_order=presentation_order,
        status=EvaluationStatus.IN_PROGRESS.value,
        current_state='INITIAL_QUESTION',
        current_modality=None,
        current_modality_attempt=0,
        vague_retry_count=0,
        comparison_retry_count=0,
        next_turn_index=1,
        next_question='',
        accumulated_text='',
        exhausted_modalities_json=[],
        modality_attempts_json={},
        started_at=service.utcnow(),
    )
    db.add(evaluation)
    db.flush()
    initial_question = service.create_initial_question(db, evaluation)
    session.status = SessionStatus.IN_PROGRESS.value
    session.current_sample_index = presentation_order
    db.commit()
    evaluation = _get_evaluation(db, evaluation.id)
    return {
        'success': True,
        'data': {
            **_serialize_evaluation(evaluation),
            'bot_message': initial_question,
            'turns': service.conversation_service.serialize_turns(evaluation),
        },
        'message': 'Evaluación creada correctamente',
    }


@router.post('/{evaluation_id}/dialog')
@limiter.limit(_DIALOG_RATE_LIMIT)
async def send_dialogue(
    request: Request,
    evaluation_id: str,
    payload: DialogueRequest,
    x_session_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    # TRANSACTIONAL BOUNDARY: process_user_turn performs multiple db.flush() calls
    # as part of a single logical transaction. commit/rollback must happen here.
    # Any exception after flush but before commit is safe: SQLAlchemy rolls back
    # automatically when the session is closed, but we make it explicit for clarity.
    evaluation = _get_evaluation(db, evaluation_id)
    check_evaluation_access(evaluation, x_session_token)
    require_tasting_session_active(evaluation.session, db)
    try:
        outcome = await service.process_user_turn(db, evaluation, payload.user_message)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception:
        db.rollback()
        raise

    refreshed_evaluation = _get_evaluation(db, evaluation_id)
    analysis_payload = None
    if outcome.analysis:
        modalities_payload: dict[str, dict[str, object]] = {}
        for modality in ModalityType:
            r = outcome.analysis.modalities.get(modality.value)
            modalities_payload[modality.value] = {
                'mention_text': r.mention_text if r else '',
                'descriptor_text': r.descriptor_text if r else '',
                'valuation_text': r.valuation_text if r else '',
                'is_complete': r.is_complete if r else False,
            }
        analysis_payload = {
            'analysis_scope': outcome.analysis.analysis_scope,
            'is_vague': outcome.analysis.is_vague,
            'has_comparison': outcome.analysis.has_comparison,
            'reasoning_summary': outcome.analysis.reasoning_summary,
            'next_action': outcome.effective_next_action,
            'modalities': modalities_payload,
        }
    return {
        'success': True,
        'data': {
            **_serialize_evaluation(refreshed_evaluation),
            'bot_message': outcome.bot_message,
            'analysis': analysis_payload,
            'next_step': outcome.next_step,
            'turns': service.conversation_service.serialize_turns(refreshed_evaluation),
        },
        'message': 'Turno procesado correctamente',
    }


@router.get('/{evaluation_id}')
def get_evaluation(evaluation_id: str, x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    evaluation = _get_evaluation(db, evaluation_id)
    check_evaluation_access(evaluation, x_session_token)
    return {
        'success': True,
        'data': _serialize_evaluation(evaluation),
        'message': 'Estado de evaluación recuperado correctamente',
    }


@router.get('/{evaluation_id}/conversation')
def get_conversation(evaluation_id: str, x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    evaluation = _get_evaluation(db, evaluation_id)
    check_evaluation_access(evaluation, x_session_token)
    return {
        'success': True,
        'data': {'evaluation_id': evaluation.id, 'turns': service.conversation_service.serialize_turns(evaluation)},
        'message': 'Histórico recuperado correctamente',
    }


@router.get('/{evaluation_id}/analysis')
def get_analysis(evaluation_id: str, x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    evaluation = _get_evaluation(db, evaluation_id)
    check_evaluation_access(evaluation, x_session_token)
    latest = max(evaluation.analyses, key=lambda item: item.created_at, default=None)
    if not latest:
        return {'success': True, 'data': {'evaluation_id': evaluation.id, 'analysis': None}, 'message': 'No hay análisis todavía'}
    modalities = _modalities_payload(latest.modalities)
    return {
        'success': True,
        'data': {
            'evaluation_id': evaluation.id,
            'is_vague': latest.is_vague,
            'has_comparison': latest.has_comparison,
            'next_action': latest.effective_next_action,
            'modalities': modalities,
        },
        'message': 'Análisis recuperado correctamente',
    }


@router.post('/{evaluation_id}/finalize', dependencies=[Depends(require_admin)])
async def finalize_evaluation(evaluation_id: str, payload: FinalizeRequest, db: Session = Depends(get_db)) -> dict:
    evaluation = _get_evaluation(db, evaluation_id)
    if evaluation.status == EvaluationStatus.COMPLETED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Evaluation is already completed')
    await service.finalize_evaluation(db, evaluation)
    db.commit()
    next_step = service.compute_next_step(db, evaluation.session_id)
    return {
        'success': True,
        'data': {'evaluation_id': evaluation.id, 'status': evaluation.status, 'next_step': next_step, 'reason': payload.reason},
        'message': 'Evaluación finalizada correctamente',
    }


@router.post('/{evaluation_id}/final-comment', status_code=status.HTTP_200_OK)
def save_final_comment(evaluation_id: str, payload: SampleCommentRequest, x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    evaluation = require_session_access_for_evaluation(evaluation_id, db, x_session_token)
    require_tasting_session_active(evaluation.session, db)
    evaluation.final_comment = payload.comment
    db.flush()
    # Reload the session with all evaluations so sync_session_status can see the
    # final_comment we just flushed. This is what transitions the session to COMPLETED
    # once every per-sample comment has been resolved.
    session_with_evals = db.scalar(
        select(TastingSession)
        .options(selectinload(TastingSession.evaluations))
        .where(TastingSession.id == evaluation.session_id)
    )
    if session_with_evals:
        service.session_progress.sync_session_status(session_with_evals, datetime.now(timezone.utc))
    db.commit()
    return {
        'success': True,
        'data': {'evaluation_id': evaluation.id, 'comment_saved': True},
        'message': 'Comentario guardado correctamente',
    }
