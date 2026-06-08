"""Pytest configuration and shared fixtures.

Environment variables MUST be set before any app import so that pydantic-settings
picks them up when Settings() is first instantiated (which happens at the module
level of app.core.config).
"""
from __future__ import annotations

import os

# --- Override settings BEFORE the first app import -------------------------
# env vars take priority over the .env file in pydantic-settings, so these
# override the development values without touching the real .env.
os.environ.setdefault('APP_ENV', 'development')
os.environ.setdefault(
    'DATABASE_URL',
    'postgresql+psycopg://postgres:postgres@localhost:5434/cookie_tasting_test',
)
os.environ.setdefault('ADMIN_API_KEY', 'test-admin-key')
os.environ.setdefault('RESEARCHER_API_KEY', 'test-researcher-key')
os.environ.setdefault('LLM_PROVIDER', 'rules')       # avoid external LLM calls
os.environ.setdefault('RATE_LIMIT_SESSIONS_PER_MINUTE', '10000')
os.environ.setdefault('RATE_LIMIT_DIALOG_PER_MINUTE', '10000')
# ---------------------------------------------------------------------------

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app

# ---------------------------------------------------------------------------
# Test database engine — separate from the dev DB
# ---------------------------------------------------------------------------
_engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


def _override_get_db():
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope='session', autouse=True)
def _create_test_schema():
    """Create all tables once at the start of the test session, drop at end."""
    Base.metadata.create_all(_engine)
    yield
    Base.metadata.drop_all(_engine)


@pytest.fixture(autouse=True)
def _truncate_tables(_create_test_schema):
    """Truncate all tables before every test to guarantee isolation."""
    with _engine.begin() as conn:
        names = ', '.join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f'TRUNCATE {names} CASCADE'))
    yield


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

SAMPLE_CODES = ['MUESTRA_A', 'MUESTRA_B']


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def admin_headers() -> dict:
    return {'X-Admin-Key': settings.admin_api_key}


@pytest.fixture
def researcher_headers() -> dict:
    return {'X-Researcher-Key': settings.researcher_api_key}


@pytest.fixture
def tasting_config(client, admin_headers) -> dict:
    """Admin-created TastingSessionConfig with two samples."""
    resp = client.post(
        '/api/v1/tasting-sessions',
        json={'title': 'Test Cata', 'sample_codes': SAMPLE_CODES},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    return resp.json()['data']


@pytest.fixture
def participant_session(client, tasting_config) -> dict:
    """Participant session linked to the tasting config."""
    resp = client.post(
        '/api/v1/sessions',
        json={
            'participant_code': 'P001',
            'tasting_session_id': tasting_config['tasting_session_id'],
        },
    )
    assert resp.status_code == 201
    return resp.json()['data']


@pytest.fixture
def session_headers(participant_session) -> dict:
    return {'X-Session-Token': participant_session['session_token']}


@pytest.fixture
def evaluation(client, participant_session, session_headers) -> dict:
    """Active evaluation for MUESTRA_A (state: INITIAL_QUESTION)."""
    resp = client.post(
        '/api/v1/evaluations',
        json={
            'session_id': participant_session['session_id'],
            'sample_code': 'MUESTRA_A',
        },
        headers=session_headers,
    )
    assert resp.status_code == 201
    return resp.json()['data']
