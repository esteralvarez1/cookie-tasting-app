"""Tests for comparison detection — cases A through F.

A. Generic comparison with previous sample → has_comparison = True
B. Comparison using sample code from session → has_comparison = True
C. No comparison — pure sensory description → has_comparison = False
D. Mixed message: comparative clause + independent sensory description
   → has_comparison = True, TEXTURA can complete, SABOR must not
E. Purely comparative turn → has_comparison = True, ASPECTO must not complete
F. Historical comparison stored in accumulated_text does NOT trigger reformulation
   when the current turn has no comparison
"""
from __future__ import annotations

import pytest

from app.api.routes.evaluations import service
from app.services.modality_metadata import has_comparison
from tests.fakes import FakeAnalyzer

# ---------------------------------------------------------------------------
# Unit tests: has_comparison() pure function
# ---------------------------------------------------------------------------

class TestHasComparisonFunction:
    def test_generic_la_anterior(self):
        assert has_comparison('Es más crujiente que la anterior.') is True

    def test_generic_la_otra(self):
        assert has_comparison('Me gusta más esta que la otra.') is True

    def test_generic_la_primera(self):
        assert has_comparison('La primera estaba mejor.') is True

    def test_generic_mejor_que(self):
        assert has_comparison('Tiene mejor textura que la de antes.') is True

    def test_generic_me_gusta_mas(self):
        assert has_comparison('Esta me gusta más.') is True

    def test_generic_la_peor(self):
        assert has_comparison('Esta es la peor de todas.') is True

    def test_sample_code_in_other_codes(self):
        assert has_comparison('Me gusta más que G102.', other_sample_codes=['G102', 'G103']) is True

    def test_sample_code_not_in_other_codes(self):
        # Code present but not in session codes → no comparison
        assert has_comparison('Pruebo G101.', other_sample_codes=['G102', 'G103']) is False

    def test_no_comparison_pure_sensory(self):
        assert has_comparison('Es muy crujiente y tiene sabor dulce.') is False

    def test_no_comparison_intensifier_only(self):
        assert has_comparison('Muy crujiente.') is False

    def test_no_comparison_valuation_only(self):
        assert has_comparison('Empalaga demasiado.') is False

    def test_no_comparison_internal_modality_relation(self):
        # "igual que" connecting two internal attributes of the same sample is NOT a comparison.
        # The deterministic guard handles this explicitly via _IGUAL_QUE_INTERNAL.
        assert has_comparison('Tiene buen sabor y también buena textura.') is False
        assert has_comparison('Tanto el sabor como la textura son buenos.') is False
        assert has_comparison('su sabor es bueno igual que su textura') is False
        assert has_comparison('el olor es agradable igual que la textura') is False
        assert has_comparison('el color es cafe y su sabor es bueno igual que su textura') is False

    def test_no_comparison_negated_statement(self):
        # Explicit denial of a comparison must never trigger has_comparison.
        assert has_comparison('no la he comparado con otra') is False
        assert has_comparison('no estoy comparando') is False
        assert has_comparison('no me refiero a otra galleta') is False
        assert has_comparison('no estoy hablando de otra') is False
        assert has_comparison('no es una comparacion') is False

    def test_comparison_igual_que_external_reference(self):
        # "igual que" followed by an external sample reference IS a comparison.
        assert has_comparison('esta es igual que la anterior') is True
        assert has_comparison('esta es igual que la muestra 2') is True
        assert has_comparison('tiene el mismo sabor igual que la primera') is True

    def test_comparison_comparada_con_not_negated(self):
        # "comparada con" without negation prefix IS a comparison.
        assert has_comparison('comparada con la anterior, esta es más seca') is True
        assert has_comparison('en comparacion con la otra, esta tiene menos olor') is True

    def test_backward_compat_no_codes_arg(self):
        # Calling without other_sample_codes must still work (backward compat)
        assert has_comparison('Mejor que la otra.') is True
        assert has_comparison('Es crujiente y dulce.') is False


# ---------------------------------------------------------------------------
# Integration tests via HTTP API
# ---------------------------------------------------------------------------

class TestComparisonDetectedViaApi:
    """Case A: generic comparative phrase triggers comparison reformulation."""

    def test_generic_comparison_triggers_reformulation(
        self, client, participant_session, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.COMPARISON))
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        assert ev.status_code == 201
        eval_id = ev.json()['data']['evaluation_id']

        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Es más crujiente que la anterior.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['analysis']['has_comparison'] is True
        comparison_msg = 'Por favor, describe esta galleta sin compararla con otra.'
        assert data['bot_message'] == comparison_msg

    def test_no_comparison_pure_sensory_continues_normally(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Case C: pure sensory description must not trigger comparison reformulation."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        assert ev.status_code == 201
        eval_id = ev.json()['data']['evaluation_id']

        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Es muy crujiente y tiene sabor dulce.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['analysis']['has_comparison'] is False
        comparison_msg = 'Por favor, describe esta galleta sin compararla con otra.'
        assert data['bot_message'] != comparison_msg


class TestDeterministicComparisonGuard:
    """The backend guard must force has_comparison=True even when FakeAnalyzer returns False."""

    def test_guard_forces_has_comparison_for_la_anterior(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Case A (guard path): FakeAnalyzer.NORMAL returns has_comparison=False,
        but the deterministic guard detects 'la anterior' and forces True."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        eval_id = ev.json()['data']['evaluation_id']

        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Es más crujiente que la anterior.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        data = resp.json()['data']
        # Guard must have forced has_comparison = True
        assert data['analysis']['has_comparison'] is True

    def test_guard_forces_has_comparison_for_peor(
        self, client, participant_session, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        eval_id = ev.json()['data']['evaluation_id']

        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Esta es la peor de las tres.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['data']['analysis']['has_comparison'] is True

    def test_guard_does_not_fire_for_neutral_message(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Case C: guard must not set has_comparison for a message without any marker."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        eval_id = ev.json()['data']['evaluation_id']

        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Es muy crujiente y dulce.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['data']['analysis']['has_comparison'] is False


class TestPurelyComparativeDoesNotCompleteModalities:
    """Case E: a purely comparative message must not complete modalities."""

    def test_purely_comparative_modalities_are_empty(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Even if FakeAnalyzer returns ALL_COMPLETE, a short comparative turn
        should have its modalities reset by the backend guard."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.COMPARISON))
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        eval_id = ev.json()['data']['evaluation_id']

        # FakeAnalyzer.COMPARISON returns has_comparison=True, empty modalities
        # The guard should see it's purely comparative (short) and not complete anything
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Tiene mejor aspecto que la otra.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['analysis']['has_comparison'] is True
        # ASPECTO must not be complete
        assert data['analysis']['modalities']['ASPECTO']['is_complete'] is False


class TestHistoricalComparisonDoesNotRefire:
    """Case F: a comparison stored in accumulated_text from a previous turn must
    NOT trigger reformulation if the current turn is clean."""

    def test_current_clean_turn_after_historical_comparison(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """
        Turn 1: comparative (COMPARISON scenario) → bot asks reformulation
        Turn 2: clean description (NORMAL scenario) → bot must NOT ask reformulation again
        """
        session_id = participant_session['session_id']
        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        assert ev.status_code == 201
        eval_id = ev.json()['data']['evaluation_id']

        # Turn 1: comparison
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.COMPARISON))
        resp1 = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Era menos dulce que la anterior.'},
            headers=session_headers,
        )
        assert resp1.status_code == 200
        comparison_msg = 'Por favor, describe esta galleta sin compararla con otra.'
        assert resp1.json()['data']['bot_message'] == comparison_msg

        # Turn 2: clean description — comparison_retry_count is now at 1 but the message is clean
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        resp2 = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Ahora me centro en esta: tiene sabor dulce y me gusta.'},
            headers=session_headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()['data']
        assert data2['analysis']['has_comparison'] is False
        assert data2['bot_message'] != comparison_msg, (
            'La segunda respuesta (sin comparación) no debe disparar reformulación de comparación'
        )
