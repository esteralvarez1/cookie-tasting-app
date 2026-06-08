"""Tests for admin tasting session CRUD and the public access endpoint."""
from __future__ import annotations

from app.api.routes.evaluations import service
from tests.fakes import FakeAnalyzer

_RICH_MESSAGE = (
    'El color es dorado y la forma redonda, la textura es muy crujiente, '
    'sabe dulce con un toque de vainilla y huele muy bien, me gusta mucho'
)


class TestCreateTastingSession:
    def test_creates_session_with_correct_data(self, client, admin_headers):
        resp = client.post(
            '/api/v1/tasting-sessions',
            json={'title': 'Cata Galletas 2026', 'sample_codes': ['A', 'B', 'C']},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body['success'] is True
        data = body['data']
        assert data['tasting_session_id']
        assert data['public_token']
        assert data['status'] == 'ACTIVE'
        assert data['sample_codes'] == ['A', 'B', 'C']
        assert data['total_samples'] == 3

    def test_title_is_optional(self, client, admin_headers):
        resp = client.post(
            '/api/v1/tasting-sessions',
            json={'sample_codes': ['X']},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    def test_requires_at_least_one_sample_code(self, client, admin_headers):
        resp = client.post(
            '/api/v1/tasting-sessions',
            json={'sample_codes': []},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_rejects_duplicate_sample_codes(self, client, admin_headers):
        resp = client.post(
            '/api/v1/tasting-sessions',
            json={'sample_codes': ['A', 'A']},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_requires_admin_key(self, client):
        resp = client.post(
            '/api/v1/tasting-sessions',
            json={'sample_codes': ['A']},
        )
        assert resp.status_code == 401

    def test_rejects_wrong_admin_key(self, client):
        resp = client.post(
            '/api/v1/tasting-sessions',
            json={'sample_codes': ['A']},
            headers={'X-Admin-Key': 'wrong-key'},
        )
        assert resp.status_code == 401


class TestListTastingSessions:
    def test_lists_existing_sessions(self, client, admin_headers, tasting_config):
        resp = client.get('/api/v1/tasting-sessions', headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()['data']
        assert any(s['tasting_session_id'] == tasting_config['tasting_session_id'] for s in data)

    def test_requires_admin_key(self, client):
        resp = client.get('/api/v1/tasting-sessions')
        assert resp.status_code == 401


class TestCloseTastingSession:
    def test_closes_active_session(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        resp = client.post(f'/api/v1/tasting-sessions/{session_id}/close', headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()['data']['status'] == 'CLOSED'

    def test_cannot_close_already_closed_session(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        client.post(f'/api/v1/tasting-sessions/{session_id}/close', headers=admin_headers)
        resp = client.post(f'/api/v1/tasting-sessions/{session_id}/close', headers=admin_headers)
        assert resp.status_code == 409

    def test_returns_404_for_unknown_session(self, client, admin_headers):
        resp = client.post('/api/v1/tasting-sessions/nonexistent-id/close', headers=admin_headers)
        assert resp.status_code == 404


class TestPublicTastingSession:
    def test_returns_session_data_by_token(self, client, tasting_config):
        token = tasting_config['public_token']
        resp = client.get(f'/api/v1/tasting-sessions/public/{token}')
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['public_token'] == token
        assert data['status'] == 'ACTIVE'
        assert set(data['sample_codes']) == {'MUESTRA_A', 'MUESTRA_B'}

    def test_closed_session_returns_closed_status(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        client.post(f'/api/v1/tasting-sessions/{session_id}/close', headers=admin_headers)
        token = tasting_config['public_token']
        resp = client.get(f'/api/v1/tasting-sessions/public/{token}')
        assert resp.status_code == 200
        assert resp.json()['data']['status'] == 'CLOSED'

    def test_returns_404_for_unknown_token(self, client):
        resp = client.get('/api/v1/tasting-sessions/public/bad-token')
        assert resp.status_code == 404

    def test_does_not_require_auth(self, client, tasting_config):
        # Public endpoint must be accessible without any key
        token = tasting_config['public_token']
        resp = client.get(f'/api/v1/tasting-sessions/public/{token}')
        assert resp.status_code == 200


class TestDeleteTastingSession:
    def test_admin_can_delete_session(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        resp = client.delete(f'/api/v1/tasting-sessions/{session_id}', headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is True
        assert body['data']['tasting_session_id'] == session_id
        assert body['data']['deleted'] is True

    def test_requires_admin_key(self, client, tasting_config):
        session_id = tasting_config['tasting_session_id']
        resp = client.delete(f'/api/v1/tasting-sessions/{session_id}')
        assert resp.status_code == 401

    def test_wrong_key_is_rejected(self, client, tasting_config):
        session_id = tasting_config['tasting_session_id']
        resp = client.delete(
            f'/api/v1/tasting-sessions/{session_id}',
            headers={'X-Admin-Key': 'wrong-key'},
        )
        assert resp.status_code == 401

    def test_returns_404_for_nonexistent_session(self, client, admin_headers):
        resp = client.delete('/api/v1/tasting-sessions/nonexistent-id', headers=admin_headers)
        assert resp.status_code == 404

    def test_deleted_session_absent_from_list(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        client.delete(f'/api/v1/tasting-sessions/{session_id}', headers=admin_headers)
        resp = client.get('/api/v1/tasting-sessions', headers=admin_headers)
        ids = [s['tasting_session_id'] for s in resp.json()['data']]
        assert session_id not in ids

    def test_public_token_returns_404_after_delete(self, client, admin_headers, tasting_config):
        session_id = tasting_config['tasting_session_id']
        token = tasting_config['public_token']
        client.delete(f'/api/v1/tasting-sessions/{session_id}', headers=admin_headers)
        resp = client.get(f'/api/v1/tasting-sessions/public/{token}')
        assert resp.status_code == 404

    def test_participant_session_deleted_with_config(
        self, client, admin_headers, tasting_config, participant_session, session_headers
    ):
        config_id = tasting_config['tasting_session_id']
        p_session_id = participant_session['session_id']

        client.delete(f'/api/v1/tasting-sessions/{config_id}', headers=admin_headers)

        # Participant session should be gone; next-step returns 404
        resp = client.get(
            f'/api/v1/sessions/{p_session_id}/next-step',
            headers=session_headers,
        )
        assert resp.status_code == 404

    def test_evaluations_and_turns_deleted_with_config(
        self, client, admin_headers, tasting_config, participant_session, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        config_id = tasting_config['tasting_session_id']
        session_id = participant_session['session_id']

        # Create an evaluation and send a dialog turn
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        assert ev.status_code == 201
        eval_id = ev.json()['data']['evaluation_id']
        client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        )

        client.delete(f'/api/v1/tasting-sessions/{config_id}', headers=admin_headers)

        # Evaluation endpoint should return 404 after delete
        resp = client.get(f'/api/v1/evaluations/{eval_id}', headers=session_headers)
        assert resp.status_code == 404
