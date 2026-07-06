from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.core.security import require_researcher_or_admin
from app.models.entities import Participant, SampleEvaluation, TastingSession, TastingSessionConfig, EvaluationAnalysis
from app.models.enums import EvaluationStatus, SpeakerType
from app.services.exporters import (
    export_conversations_csv,
    export_structured_csv,
    export_structured_rows,
    export_structured_xlsx,
    export_user_responses_csv,
    structured_row_to_api_dict,
)

router = APIRouter(prefix='/export', tags=['export'])


def _attachment_headers(filename: str) -> dict[str, str]:
    return {'Content-Disposition': f'attachment; filename="{filename}"'}


def _slugify_filename_part(value: str) -> str:
    """Normalize a free-text value into a safe, hyphenated filename fragment.

    Lowercases, strips accents, turns whitespace into hyphens, drops any
    character that is not [a-z0-9-], collapses repeated hyphens and trims
    leading/trailing hyphens. Returns 'sesion' when nothing usable remains.

    Examples:
        'Test Cata'       -> 'test-cata'
        'Cata Junio 2026' -> 'cata-junio-2026'
        'Sesión María'    -> 'sesion-maria'
        ''                -> 'sesion'
    """
    normalized = unicodedata.normalize('NFKD', value or '')
    without_accents = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    lowered = without_accents.lower()
    # Whitespace becomes a hyphen; everything not [a-z0-9-] is dropped.
    hyphenated = re.sub(r'\s+', '-', lowered)
    cleaned = re.sub(r'[^a-z0-9-]', '', hyphenated)
    collapsed = re.sub(r'-+', '-', cleaned).strip('-')
    return collapsed or 'sesion'


def _iso_export_date() -> str:
    """Current date in ISO format, e.g. '2026-06-13'."""
    return datetime.now().strftime('%Y-%m-%d')


def _build_export_filename(export_type: str, session_title: str | None, extension: str) -> str:
    """Compose '<export_type>_<session_slug>_<YYYY-MM-DD>.<extension>'.

    The three parts are joined with underscores; the session name uses a
    hyphenated slug, so e.g. 'clasificacion-estructurada_test-cata_2026-06-13.csv'.
    """
    session_slug = _slugify_filename_part(session_title or '')
    return f'{export_type}_{session_slug}_{_iso_export_date()}.{extension}'


def _resolve_session_title(
    db: Session,
    session_id: str | None,
    participant_code: str | None,
    tasting_session_config_id: str | None,
) -> str | None:
    """Best-effort resolution of the tasting session title for the filename.

    Resolves from the most specific unambiguous filter available. A bare
    participant_code may span several tasting sessions, so it is left as None
    and the filename falls back to 'sesion'.
    """
    if tasting_session_config_id:
        config = db.get(TastingSessionConfig, tasting_session_config_id)
        return config.title if config else None
    if session_id:
        session = db.get(TastingSession, session_id)
        if session and session.admin_session_id:
            config = db.get(TastingSessionConfig, session.admin_session_id)
            return config.title if config else None
    return None


def _require_export_filter(session_id: str | None, participant_code: str | None, tasting_session_config_id: str | None) -> None:
    if not any([session_id, participant_code, tasting_session_config_id]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='At least one filter is required for export',
        )


def _query_evaluations(
    db: Session,
    session_id: str | None,
    participant_code: str | None,
    tasting_session_config_id: str | None = None,
):
    stmt = select(SampleEvaluation).options(
        selectinload(SampleEvaluation.sample),
        selectinload(SampleEvaluation.turns),
        selectinload(SampleEvaluation.analyses).selectinload(EvaluationAnalysis.modalities),
        selectinload(SampleEvaluation.session).selectinload(TastingSession.participant),
        selectinload(SampleEvaluation.session).selectinload(TastingSession.final_survey),
    )
    if session_id:
        stmt = stmt.where(SampleEvaluation.session_id == session_id)
    if tasting_session_config_id:
        # Use has() (EXISTS subquery) to avoid a double join when participant_code is also set.
        stmt = stmt.where(SampleEvaluation.session.has(TastingSession.admin_session_id == tasting_session_config_id))
    if participant_code:
        stmt = stmt.join(SampleEvaluation.session).join(TastingSession.participant).where(Participant.participant_code == participant_code)
    return db.scalars(stmt.order_by(SampleEvaluation.presentation_order)).unique().all()


@router.get('/conversations', dependencies=[Depends(require_researcher_or_admin)])
def export_conversations(format: str = Query('csv'), session_id: str | None = None, participant_code: str | None = None, tasting_session_config_id: str | None = None, db: Session = Depends(get_db)):
    _require_export_filter(session_id, participant_code, tasting_session_config_id)
    evaluations = _query_evaluations(db, session_id, participant_code, tasting_session_config_id)
    session_title = _resolve_session_title(db, session_id, participant_code, tasting_session_config_id)
    if format == 'json':
        payload = []
        for evaluation in evaluations:
            for turn in sorted(evaluation.turns, key=lambda item: item.turn_index):
                payload.append({
                    'participant_code': evaluation.session.participant.participant_code,
                    'session_id': evaluation.session_id,
                    'evaluation_id': evaluation.id,
                    'sample_code': evaluation.sample.sample_code,
                    'presentation_order': evaluation.presentation_order,
                    'turn_index': turn.turn_index,
                    'speaker': turn.speaker,
                    'message_type': turn.message_type,
                    'message_text': turn.message_text,
                    'created_at': turn.created_at.isoformat(),
                })
        return JSONResponse(
            content={'success': True, 'data': payload, 'message': 'Exportación de conversación generada'},
            headers=_attachment_headers(_build_export_filename('conversacion-completa', session_title, 'json')),
        )
    csv_text = export_conversations_csv(evaluations)
    return PlainTextResponse(
        csv_text,
        media_type='text/csv',
        headers=_attachment_headers(_build_export_filename('conversacion-completa', session_title, 'csv')),
    )


@router.get('/user-responses', dependencies=[Depends(require_researcher_or_admin)])
def export_user_responses(format: str = Query('csv'), session_id: str | None = None, participant_code: str | None = None, tasting_session_config_id: str | None = None, db: Session = Depends(get_db)):
    _require_export_filter(session_id, participant_code, tasting_session_config_id)
    evaluations = _query_evaluations(db, session_id, participant_code, tasting_session_config_id)
    session_title = _resolve_session_title(db, session_id, participant_code, tasting_session_config_id)
    if format == 'json':
        payload = []
        for evaluation in evaluations:
            for turn in sorted(evaluation.turns, key=lambda item: item.turn_index):
                if turn.speaker != SpeakerType.USER.value:
                    continue
                payload.append({
                    'participant_code': evaluation.session.participant.participant_code,
                    'session_id': evaluation.session_id,
                    'evaluation_id': evaluation.id,
                    'sample_code': evaluation.sample.sample_code,
                    'presentation_order': evaluation.presentation_order,
                    'turn_index': turn.turn_index,
                    'message_text': turn.message_text,
                    'created_at': turn.created_at.isoformat(),
                })
        return JSONResponse(
            content={'success': True, 'data': payload, 'message': 'Exportación de respuestas del usuario generada'},
            headers=_attachment_headers(_build_export_filename('respuestas-usuario', session_title, 'json')),
        )
    csv_text = export_user_responses_csv(evaluations)
    return PlainTextResponse(
        csv_text,
        media_type='text/csv',
        headers=_attachment_headers(_build_export_filename('respuestas-usuario', session_title, 'csv')),
    )


@router.get('/structured', dependencies=[Depends(require_researcher_or_admin)])
def export_structured(format: str = Query('csv'), session_id: str | None = None, participant_code: str | None = None, tasting_session_config_id: str | None = None, db: Session = Depends(get_db)):
    _require_export_filter(session_id, participant_code, tasting_session_config_id)
    evaluations = [item for item in _query_evaluations(db, session_id, participant_code, tasting_session_config_id) if item.status == EvaluationStatus.COMPLETED.value]
    session_title = _resolve_session_title(db, session_id, participant_code, tasting_session_config_id)
    if format == 'json':
        payload = [structured_row_to_api_dict(row) for row in export_structured_rows(evaluations)]
        return JSONResponse(
            content={'success': True, 'data': payload, 'message': 'Exportación estructurada generada'},
            headers=_attachment_headers(_build_export_filename('clasificacion-estructurada', session_title, 'json')),
        )
    if format == 'xlsx':
        workbook_bytes = export_structured_xlsx(evaluations)
        return Response(
            content=workbook_bytes,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers=_attachment_headers(_build_export_filename('clasificacion-estructurada', session_title, 'xlsx')),
        )
    csv_text = export_structured_csv(evaluations)
    return PlainTextResponse(
        csv_text,
        media_type='text/csv',
        headers=_attachment_headers(_build_export_filename('clasificacion-estructurada', session_title, 'csv')),
    )
