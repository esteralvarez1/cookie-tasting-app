"""Tests that protected endpoints enforce authentication correctly."""
from __future__ import annotations

import pytest


PROTECTED_ADMIN_ENDPOINTS = [
    ('POST', '/api/v1/tasting-sessions', {'sample_codes': ['A']}),
    ('GET',  '/api/v1/tasting-sessions', None),
]

PROTECTED_RESEARCHER_ENDPOINTS = [
    ('GET', '/api/v1/export/conversations?session_id=test-filter', None),
    ('GET', '/api/v1/export/user-responses?session_id=test-filter', None),
    ('GET', '/api/v1/export/structured?session_id=test-filter', None),
]

PUBLIC_ENDPOINTS_WITHOUT_AUTH = [
    ('GET', '/api/v1/health', None),
]


def _request(client, method: str, path: str, body, **kwargs):
    """Call client.<method>(path) passing json only when body is not None."""
    fn = getattr(client, method.lower())
    if body is not None:
        return fn(path, json=body, **kwargs)
    return fn(path, **kwargs)


class TestAdminEndpoints:
    @pytest.mark.parametrize('method,path,body', PROTECTED_ADMIN_ENDPOINTS)
    def test_no_key_returns_401(self, client, method, path, body):
        resp = _request(client, method, path, body)
        assert resp.status_code == 401

    @pytest.mark.parametrize('method,path,body', PROTECTED_ADMIN_ENDPOINTS)
    def test_wrong_key_returns_401(self, client, method, path, body):
        resp = _request(client, method, path, body, headers={'X-Admin-Key': 'wrong'})
        assert resp.status_code == 401

    @pytest.mark.parametrize('method,path,body', PROTECTED_ADMIN_ENDPOINTS)
    def test_correct_key_is_accepted(self, client, admin_headers, method, path, body):
        resp = _request(client, method, path, body, headers=admin_headers)
        assert resp.status_code in (200, 201)


class TestResearcherEndpoints:
    @pytest.mark.parametrize('method,path,body', PROTECTED_RESEARCHER_ENDPOINTS)
    def test_no_key_returns_401(self, client, method, path, body):
        resp = _request(client, method, path, body)
        assert resp.status_code == 401

    @pytest.mark.parametrize('method,path,body', PROTECTED_RESEARCHER_ENDPOINTS)
    def test_wrong_key_returns_401(self, client, method, path, body):
        resp = _request(client, method, path, body, headers={'X-Researcher-Key': 'wrong'})
        assert resp.status_code == 401

    @pytest.mark.parametrize('method,path,body', PROTECTED_RESEARCHER_ENDPOINTS)
    def test_researcher_key_accepted(self, client, researcher_headers, method, path, body):
        resp = _request(client, method, path, body, headers=researcher_headers)
        assert resp.status_code == 200

    @pytest.mark.parametrize('method,path,body', PROTECTED_RESEARCHER_ENDPOINTS)
    def test_admin_key_also_accepted(self, client, admin_headers, method, path, body):
        resp = _request(client, method, path, body, headers=admin_headers)
        assert resp.status_code == 200


class TestPublicEndpoints:
    @pytest.mark.parametrize('method,path,body', PUBLIC_ENDPOINTS_WITHOUT_AUTH)
    def test_accessible_without_key(self, client, method, path, body):
        resp = _request(client, method, path, body)
        assert resp.status_code == 200


class TestParticipantTokenEnforcement:
    def test_evaluation_endpoints_require_session_token(self, client, evaluation, session_headers):
        eval_id = evaluation['evaluation_id']
        for path in [
            f'/api/v1/evaluations/{eval_id}',
            f'/api/v1/evaluations/{eval_id}/conversation',
            f'/api/v1/evaluations/{eval_id}/analysis',
        ]:
            resp = client.get(path)
            assert resp.status_code == 401, f'Expected 401 for {path}'

    def test_dialog_endpoint_requires_session_token(self, client, evaluation):
        eval_id = evaluation['evaluation_id']
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Hola'},
        )
        assert resp.status_code == 401

    def test_session_token_cannot_access_other_sessions_evaluation(
        self, client, tasting_config, participant_session, session_headers
    ):
        """A token issued to participant P001 must not access P002's evaluation."""
        config_id = tasting_config['tasting_session_id']
        # Create a second participant session
        sess2 = client.post(
            '/api/v1/sessions',
            json={'participant_code': 'P002', 'tasting_session_id': config_id},
        ).json()['data']
        headers2 = {'X-Session-Token': sess2['session_token']}
        ev2 = client.post(
            '/api/v1/evaluations',
            json={'session_id': sess2['session_id'], 'sample_code': 'MUESTRA_A'},
            headers=headers2,
        ).json()['data']

        # Use P001's token to try to access P002's evaluation
        resp = client.get(
            f"/api/v1/evaluations/{ev2['evaluation_id']}",
            headers=session_headers,
        )
        assert resp.status_code == 401
