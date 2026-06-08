from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_db
from app.models.entities import SampleEvaluation, TastingSession, TastingSessionConfig


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not _constant_time_equal(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Admin authentication required')


def require_researcher_or_admin(
    x_admin_key: str | None = Header(default=None),
    x_researcher_key: str | None = Header(default=None),
) -> None:
    if _constant_time_equal(x_admin_key, settings.admin_api_key) or _constant_time_equal(x_researcher_key, settings.researcher_api_key):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Researcher or admin authentication required')


def _constant_time_equal(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left, right)


def _hash_session_token(token: str | None) -> str | None:
    if not token:
        return None
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _check_session_token_expiry(session: TastingSession) -> None:
    """Raise HTTP 401 with detail='session_expired' if the token TTL has elapsed.

    The expiry timestamp is stored as an ISO 8601 string in
    session.config_json['session_token_expires_at']. Sessions created before this
    field was introduced have no recorded expiry and are treated as non-expiring
    to preserve backwards compatibility.
    """
    expires_at_iso: str | None = (session.config_json or {}).get('session_token_expires_at')
    if not expires_at_iso:
        return
    expires_at = datetime.fromisoformat(expires_at_iso)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='session_expired')


def _session_token_is_valid(session: TastingSession | None, provided_token: str | None) -> bool:
    if not session:
        return False
    hashed_provided = _hash_session_token(provided_token)
    if session.session_token_hash and hashed_provided:
        return _constant_time_equal(session.session_token_hash, hashed_provided)

    # Legacy fallback: sessions created before migration 0002 (2026-04-16) stored the
    # plain token in config_json['session_token'] instead of hashing it.
    # This path should never be reached for sessions created after that migration.
    configured_plain = (session.config_json or {}).get('session_token')
    return _constant_time_equal(provided_token, configured_plain)


def require_tasting_session_active(session: TastingSession, db: Session) -> None:
    """Raise HTTP 403 if the admin tasting session linked to this participant session is closed.

    Uses db.get() so the identity map prevents a redundant query when TastingSessionConfig
    was already loaded earlier in the same request.
    """
    if not session.admin_session_id:
        return
    config = db.get(TastingSessionConfig, session.admin_session_id)
    if config is not None and config.status != 'ACTIVE':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='La sesión de cata está cerrada')


def require_session_access_for_session(
    session_id: str,
    db: Session,
    x_session_token: str | None,
) -> TastingSession:
    session = db.scalar(select(TastingSession).where(TastingSession.id == session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Session not found')
    _check_session_token_expiry(session)
    if not _session_token_is_valid(session, x_session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Valid participant session token required')
    return session


def require_session_access_for_evaluation(
    evaluation_id: str,
    db: Session,
    x_session_token: str | None,
) -> SampleEvaluation:
    evaluation = db.scalar(
        select(SampleEvaluation)
        .options(selectinload(SampleEvaluation.session))
        .where(SampleEvaluation.id == evaluation_id)
    )
    if not evaluation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Evaluation not found')
    _check_session_token_expiry(evaluation.session)
    if not _session_token_is_valid(evaluation.session, x_session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Valid participant session token required')
    return evaluation


def check_evaluation_access(evaluation: SampleEvaluation, x_session_token: str | None) -> None:
    """Validate token access for an already-loaded evaluation.

    Use this when the caller already holds a fully-loaded SampleEvaluation (with .session
    populated) to avoid a second DB round-trip.
    """
    _check_session_token_expiry(evaluation.session)
    if not _session_token_is_valid(evaluation.session, x_session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Valid participant session token required')


def get_session_access(
    x_session_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple[Session, str | None]:
    return db, x_session_token
