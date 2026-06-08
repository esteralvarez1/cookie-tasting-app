"""Tests for participant session creation and lifecycle."""
from __future__ import annotations

from app.api.routes.evaluations import service
from tests.fakes import FakeAnalyzer

_RICH_MESSAGE = (
    'El color es dorado y la forma redonda, la textura es muy crujiente, '
    'sabe dulce con un toque de vainilla y huele muy bien, me gusta mucho'
)


def _complete_evaluation(client, session_id: str, sample_code: str, session_headers: dict) -> None:
    ev = client.post(
        '/api/v1/evaluations',
        json={'session_id': session_id, 'sample_code': sample_code},
        headers=session_headers,
    )
    assert ev.status_code in (200, 201)
    eval_id = ev.json()['data']['evaluation_id']
    resp = client.post(
        f'/api/v1/evaluations/{eval_id}/dialog',
        json={'user_message': _RICH_MESSAGE},
        headers=session_headers,
    )
    assert resp.status_code == 200


class TestCreateParticipantSession:
    def test_creates_session_and_returns_token(self, client, tasting_config):
        resp = client.post(
            '/api/v1/sessions',
            json={
                'participant_code': 'P001',
                'tasting_session_id': tasting_config['tasting_session_id'],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body['success'] is True
        data = body['data']
        assert data['session_id']
        assert data['session_token']
        assert data['participant_code'] == 'P001'
        assert data['tasting_session_id'] == tasting_config['tasting_session_id']
        assert data['status'] == 'CREATED'
        assert set(data['pending_sample_codes']) == {'MUESTRA_A', 'MUESTRA_B'}
        assert data['completed_sample_codes'] == []

    def test_returns_404_for_unknown_tasting_session(self, client):
        resp = client.post(
            '/api/v1/sessions',
            json={'participant_code': 'P001', 'tasting_session_id': 'nonexistent'},
        )
        assert resp.status_code == 404

    def test_rejects_session_creation_when_tasting_config_closed(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        client.post(f'/api/v1/tasting-sessions/{session_id}/close', headers=admin_headers)

        resp = client.post(
            '/api/v1/sessions',
            json={'participant_code': 'P_NEW', 'tasting_session_id': session_id},
        )
        assert resp.status_code == 409

    def test_resuming_existing_session_issues_new_token(self, client, tasting_config):
        payload = {
            'participant_code': 'P001',
            'tasting_session_id': tasting_config['tasting_session_id'],
        }
        first = client.post('/api/v1/sessions', json=payload)
        assert first.status_code == 201
        first_token = first.json()['data']['session_token']

        second = client.post('/api/v1/sessions', json=payload)
        # Same participant resuming same tasting config → new token but same session
        assert second.status_code == 201
        second_data = second.json()['data']
        assert second_data['session_token'] != first_token
        assert second_data['session_id'] == first.json()['data']['session_id']

    def test_different_participants_get_different_sessions(self, client, tasting_config):
        config_id = tasting_config['tasting_session_id']
        r1 = client.post('/api/v1/sessions', json={'participant_code': 'P001', 'tasting_session_id': config_id})
        r2 = client.post('/api/v1/sessions', json={'participant_code': 'P002', 'tasting_session_id': config_id})
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()['data']['session_id'] != r2.json()['data']['session_id']


class TestNextStep:
    def test_returns_next_sample_when_evaluations_not_started(self, client, participant_session, session_headers):
        session_id = participant_session['session_id']
        resp = client.get(f'/api/v1/sessions/{session_id}/next-step', headers=session_headers)
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['next_step'] == 'NEXT_SAMPLE'
        assert set(data['pending_sample_codes']) == {'MUESTRA_A', 'MUESTRA_B'}

    def test_requires_valid_session_token(self, client, participant_session):
        session_id = participant_session['session_id']
        resp = client.get(
            f'/api/v1/sessions/{session_id}/next-step',
            headers={'X-Session-Token': 'bad-token'},
        )
        assert resp.status_code == 401


class TestFinalSurvey:
    def test_survey_rejected_when_samples_pending(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Survey is rejected with 409 when not all samples are completed."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        session_id = participant_session['session_id']

        # Complete only MUESTRA_A (session has 2 samples: MUESTRA_A and MUESTRA_B)
        _complete_evaluation(client, session_id, 'MUESTRA_A', session_headers)

        resp = client.post(
            f'/api/v1/sessions/{session_id}/survey',
            json={'payload': {'q1': 'answer'}},
            headers=session_headers,
        )
        assert resp.status_code == 409

        # Verify the session is NOT marked as completed
        next_step = client.get(f'/api/v1/sessions/{session_id}/next-step', headers=session_headers)
        assert next_step.json()['data']['next_step'] != 'SESSION_COMPLETED'

    def test_survey_accepted_when_all_samples_completed(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Survey is accepted after completing all samples."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        session_id = participant_session['session_id']

        _complete_evaluation(client, session_id, 'MUESTRA_A', session_headers)
        _complete_evaluation(client, session_id, 'MUESTRA_B', session_headers)

        resp = client.post(
            f'/api/v1/sessions/{session_id}/survey',
            json={'payload': {'q1': 'answer'}},
            headers=session_headers,
        )
        assert resp.status_code == 201
        assert resp.json()['data']['status'] == 'COMPLETED'

    def test_survey_rejected_with_no_completed_evaluations(
        self, client, participant_session, session_headers
    ):
        """Survey is rejected when no evaluations have been done at all."""
        session_id = participant_session['session_id']
        resp = client.post(
            f'/api/v1/sessions/{session_id}/survey',
            json={'payload': {}},
            headers=session_headers,
        )
        assert resp.status_code == 409


class TestClosedSessionBlocksParticipant:
    def test_closed_config_blocks_evaluation_creation(
        self, client, admin_headers, tasting_config, participant_session, session_headers
    ):
        # Close the tasting config after participant already has a token
        config_id = tasting_config['tasting_session_id']
        client.post(f'/api/v1/tasting-sessions/{config_id}/close', headers=admin_headers)

        resp = client.post(
            '/api/v1/evaluations',
            json={
                'session_id': participant_session['session_id'],
                'sample_code': 'MUESTRA_A',
            },
            headers=session_headers,
        )
        assert resp.status_code == 403
