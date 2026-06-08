"""Tests for evaluation creation and state."""
from __future__ import annotations

from app.api.routes.evaluations import service
from tests.fakes import FakeAnalyzer


class TestCreateEvaluation:
    def test_creates_evaluation_for_valid_sample(self, client, participant_session, session_headers):
        resp = client.post(
            '/api/v1/evaluations',
            json={
                'session_id': participant_session['session_id'],
                'sample_code': 'MUESTRA_A',
            },
            headers=session_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body['success'] is True
        data = body['data']
        assert data['evaluation_id']
        assert data['sample_code'] == 'MUESTRA_A'
        assert data['status'] == 'IN_PROGRESS'
        assert data['current_state'] == 'INITIAL_QUESTION'
        assert data['bot_message']
        # Initial bot turn must already exist
        assert len(data['turns']) >= 1
        assert data['turns'][0]['speaker'] == 'BOT'

    def test_rejects_sample_not_in_config(self, client, participant_session, session_headers):
        resp = client.post(
            '/api/v1/evaluations',
            json={
                'session_id': participant_session['session_id'],
                'sample_code': 'MUESTRA_FANTASMA',
            },
            headers=session_headers,
        )
        assert resp.status_code == 400

    def test_presentation_order_increments_per_sample(
        self, client, participant_session, session_headers
    ):
        r1 = client.post(
            '/api/v1/evaluations',
            json={'session_id': participant_session['session_id'], 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        r2 = client.post(
            '/api/v1/evaluations',
            json={'session_id': participant_session['session_id'], 'sample_code': 'MUESTRA_B'},
            headers=session_headers,
        )
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()['data']['presentation_order'] == 1
        assert r2.json()['data']['presentation_order'] == 2

    def test_resuming_in_progress_evaluation_returns_existing(
        self, client, participant_session, session_headers
    ):
        payload = {
            'session_id': participant_session['session_id'],
            'sample_code': 'MUESTRA_A',
        }
        first = client.post('/api/v1/evaluations', json=payload, headers=session_headers)
        second = client.post('/api/v1/evaluations', json=payload, headers=session_headers)
        assert first.status_code == 201
        assert second.status_code == 201
        # Both should return the same evaluation_id
        assert first.json()['data']['evaluation_id'] == second.json()['data']['evaluation_id']

    def test_requires_valid_session_token(self, client, participant_session):
        resp = client.post(
            '/api/v1/evaluations',
            json={'session_id': participant_session['session_id'], 'sample_code': 'MUESTRA_A'},
            headers={'X-Session-Token': 'bad-token'},
        )
        assert resp.status_code == 401

    def test_returns_404_for_unknown_session(self, client, session_headers):
        resp = client.post(
            '/api/v1/evaluations',
            json={'session_id': 'nonexistent-session', 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        assert resp.status_code == 404


class TestGetEvaluation:
    def test_returns_evaluation_state(self, client, evaluation, session_headers):
        eval_id = evaluation['evaluation_id']
        resp = client.get(f'/api/v1/evaluations/{eval_id}', headers=session_headers)
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['evaluation_id'] == eval_id
        assert data['status'] == 'IN_PROGRESS'

    def test_requires_valid_session_token(self, client, evaluation):
        eval_id = evaluation['evaluation_id']
        resp = client.get(
            f'/api/v1/evaluations/{eval_id}',
            headers={'X-Session-Token': 'bad-token'},
        )
        assert resp.status_code == 401


class TestGetConversation:
    def test_returns_turns(self, client, evaluation, session_headers):
        eval_id = evaluation['evaluation_id']
        resp = client.get(f'/api/v1/evaluations/{eval_id}/conversation', headers=session_headers)
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['evaluation_id'] == eval_id
        assert isinstance(data['turns'], list)
        assert len(data['turns']) >= 1


class TestSaveFinalComment:
    def test_saves_comment(self, client, evaluation, session_headers):
        eval_id = evaluation['evaluation_id']
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/final-comment',
            json={'comment': 'Me gustó mucho esta galleta.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['data']['comment_saved'] is True


class TestFinalizeIdempotency:
    def test_finalize_sets_status_completed(self, client, evaluation, admin_headers):
        eval_id = evaluation['evaluation_id']
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/finalize',
            json={'reason': 'TEST'},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['data']['status'] == 'COMPLETED'

    def test_finalize_twice_returns_409(self, client, evaluation, admin_headers):
        eval_id = evaluation['evaluation_id']
        first = client.post(
            f'/api/v1/evaluations/{eval_id}/finalize',
            json={'reason': 'TEST'},
            headers=admin_headers,
        )
        assert first.status_code == 200

        second = client.post(
            f'/api/v1/evaluations/{eval_id}/finalize',
            json={'reason': 'TEST'},
            headers=admin_headers,
        )
        assert second.status_code == 409

    def test_finalize_twice_does_not_duplicate_final_message_turn(
        self, client, evaluation, admin_headers, session_headers
    ):
        eval_id = evaluation['evaluation_id']
        client.post(
            f'/api/v1/evaluations/{eval_id}/finalize',
            json={'reason': 'TEST'},
            headers=admin_headers,
        )
        turns_before = client.get(
            f'/api/v1/evaluations/{eval_id}/conversation',
            headers=session_headers,
        ).json()['data']['turns']
        final_count_before = sum(1 for t in turns_before if t['message_type'] == 'FINAL_MESSAGE')

        client.post(
            f'/api/v1/evaluations/{eval_id}/finalize',
            json={'reason': 'TEST'},
            headers=admin_headers,
        )
        turns_after = client.get(
            f'/api/v1/evaluations/{eval_id}/conversation',
            headers=session_headers,
        ).json()['data']['turns']
        final_count_after = sum(1 for t in turns_after if t['message_type'] == 'FINAL_MESSAGE')

        assert final_count_after == final_count_before
