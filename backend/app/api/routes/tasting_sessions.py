from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.core.security import require_admin
from app.models.entities import EvaluationAnalysis, SampleEvaluation, TastingSession, TastingSessionConfig
from app.schemas.tasting_sessions import TastingSessionConfigCreateRequest

router = APIRouter(prefix='/tasting-sessions', tags=['tasting-sessions'])

_PUBLIC_TOKEN_RATE_LIMIT = f'{settings.rate_limit_sessions_per_minute}/minute'



def _serialize_config(config: TastingSessionConfig) -> dict:
    return {
        'tasting_session_id': config.id,
        'public_token': config.public_token,
        'title': config.title,
        'status': config.status,
        'sample_codes': config.sample_codes_json,
        'total_samples': len(config.sample_codes_json),
        'final_redirect_url': config.final_redirect_url,
    }


@router.post('', status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_tasting_session(payload: TastingSessionConfigCreateRequest, db: Session = Depends(get_db)) -> dict:
    config = TastingSessionConfig(
        title=payload.title,
        sample_codes_json=payload.sample_codes,
        final_redirect_url=payload.final_redirect_url,
        status='ACTIVE',
    )
    db.add(config)
    db.commit()
    return {
        'success': True,
        'data': _serialize_config(config),
        'message': 'Sesión de cata creada correctamente',
    }


@router.get('', dependencies=[Depends(require_admin)])
def list_tasting_sessions(db: Session = Depends(get_db)) -> dict:
    configs = db.scalars(
        select(TastingSessionConfig).order_by(TastingSessionConfig.created_at.desc())
    ).all()
    return {
        'success': True,
        'data': [_serialize_config(c) for c in configs],
        'message': 'Sesiones de cata listadas correctamente',
    }


@router.post('/{session_config_id}/close', dependencies=[Depends(require_admin)])
def close_tasting_session(session_config_id: str, db: Session = Depends(get_db)) -> dict:
    config = db.scalar(select(TastingSessionConfig).where(TastingSessionConfig.id == session_config_id))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tasting session not found')
    if config.status == 'CLOSED':
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La sesión ya está cerrada')
    config.status = 'CLOSED'
    db.commit()
    return {
        'success': True,
        'data': _serialize_config(config),
        'message': 'Sesión de cata cerrada correctamente',
    }


@router.delete('/{session_config_id}', dependencies=[Depends(require_admin)], status_code=status.HTTP_200_OK)
def delete_tasting_session(session_config_id: str, db: Session = Depends(get_db)) -> dict:
    config = db.scalar(
        select(TastingSessionConfig)
        .options(
            selectinload(TastingSessionConfig.participant_sessions).selectinload(TastingSession.final_survey),
            selectinload(TastingSessionConfig.participant_sessions)
            .selectinload(TastingSession.evaluations)
            .selectinload(SampleEvaluation.turns),
            selectinload(TastingSessionConfig.participant_sessions)
            .selectinload(TastingSession.evaluations)
            .selectinload(SampleEvaluation.analyses)
            .selectinload(EvaluationAnalysis.modalities),
        )
        .where(TastingSessionConfig.id == session_config_id)
    )
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tasting session not found')
    try:
        db.delete(config)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='No se pudo eliminar la sesión de cata. Inténtalo de nuevo.',
        ) from exc
    return {
        'success': True,
        'data': {'tasting_session_id': session_config_id, 'deleted': True},
        'message': 'Sesión de cata eliminada correctamente',
    }


@router.get('/public/{token}')
@limiter.limit(_PUBLIC_TOKEN_RATE_LIMIT)
def get_public_tasting_session(request: Request, token: str, db: Session = Depends(get_db)) -> dict:
    config = db.scalar(select(TastingSessionConfig).where(TastingSessionConfig.public_token == token))
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Tasting session not found')
    return {
        'success': True,
        'data': _serialize_config(config),
        'message': 'Sesión de cata recuperada correctamente',
    }
