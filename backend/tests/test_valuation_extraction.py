"""Tests for the deterministic valuation extraction layer.

Covers:
A. SABOR with implicit negative valuation — fallback must fill valuation_text.
B. TEXTURA with functional defect as valuation — fallback must fill valuation_text.
C. Brief answer to a directed modality question — must not trigger vague reprompt.
D. Neutral descriptor only — fallback must NOT invent a valuation.
"""
from __future__ import annotations

import pytest

from app.api.routes.evaluations import service
from app.services.modality_metadata import find_valuation_in_text
from tests.fakes import FakeAnalyzer


# ---------------------------------------------------------------------------
# Unit tests: find_valuation_in_text (pure function, no DB needed)
# ---------------------------------------------------------------------------

class TestFindValuationInText:
    def test_sabor_empalaga_is_found(self):
        # Either sentence is a valid valuation: "jengibre artificial" or "Empalaga...demasiada"
        text = 'Retrogusto largo con sabor a azúcar tostada y jengibre artificial. Empalaga y tiene demasiada azúcar.'
        result = find_valuation_in_text(text, 'SABOR')
        assert result
        valuation_signals = ('empalaga', 'demasiada', 'artificial')
        assert any(s in result.lower() for s in valuation_signals)

    def test_sabor_demasiada_azucar_is_found(self):
        result = find_valuation_in_text('Sabe muy bien. Empalaga y presiento demasiada azucar.', 'SABOR')
        assert result
        assert 'empalaga' in result.lower() or 'demasiada' in result.lower()

    def test_textura_genera_migas_is_found(self):
        result = find_valuation_in_text('Textura seca y boronosa, genera muchas migas.', 'TEXTURA')
        assert result
        assert 'migas' in result.lower()

    def test_textura_boronosa_is_found(self):
        result = find_valuation_in_text('La textura es boronosa.', 'TEXTURA')
        assert result
        assert 'boronosa' in result.lower()

    def test_sabor_neutro_no_valuation(self):
        # "dulce" is a descriptor, not a valuation — must return ''
        result = find_valuation_in_text('El sabor es dulce.', 'SABOR')
        assert result == ''

    def test_aspecto_bonita(self):
        result = find_valuation_in_text('La galleta es bonita y redonda.', 'ASPECTO')
        assert result
        assert 'bonita' in result.lower()

    def test_olor_agradable(self):
        result = find_valuation_in_text('Tiene un olor agradable.', 'OLOR')
        assert result
        assert 'agradable' in result.lower()

    def test_no_cross_modality_contamination(self):
        # TEXTURA must not match SABOR valuation pattern "empalaga"
        result = find_valuation_in_text('Empalaga demasiado.', 'TEXTURA')
        assert result == ''

    def test_sabor_jengibre_artificial(self):
        result = find_valuation_in_text('Sabe a jengibre artificial y azúcar quemada.', 'SABOR')
        assert result
        assert 'artificial' in result.lower()

    def test_empty_text_returns_empty(self):
        assert find_valuation_in_text('', 'SABOR') == ''
        assert find_valuation_in_text('', 'TEXTURA') == ''


# ---------------------------------------------------------------------------
# Integration tests via HTTP API (require DB fixture from conftest)
# ---------------------------------------------------------------------------

class TestValuationFallbackViaApi:
    """Tests that the deterministic fallback is applied during the dialog endpoint."""

    def test_sabor_valuation_filled_by_fallback(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """FakeAnalyzer returns SABOR with mention+descriptor but no valuation.
        The backend fallback must fill valuation_text from the accumulated text.
        """
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.SABOR_PARTIAL))
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
            json={'user_message': 'Retrogusto largo con sabor a azúcar tostada y jengibre artificial. Empalaga y tiene demasiada azúcar.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        sabor = resp.json()['data']['analysis']['modalities']['SABOR']
        assert sabor['mention_text']
        assert sabor['descriptor_text']
        assert sabor['valuation_text'], 'El fallback debió rellenar valuation_text para SABOR'
        assert sabor['is_complete'] is True

    def test_textura_valuation_filled_by_fallback(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """FakeAnalyzer returns TEXTURA with mention+descriptor but no valuation.
        The fallback must detect 'genera muchas migas' as valuation.
        """
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.TEXTURA_PARTIAL))
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
            json={'user_message': 'Textura seca y boronosa, genera muchas migas.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        textura = resp.json()['data']['analysis']['modalities']['TEXTURA']
        assert textura['mention_text']
        assert textura['descriptor_text']
        assert textura['valuation_text'], 'El fallback debió rellenar valuation_text para TEXTURA'
        assert textura['is_complete'] is True

    def test_neutral_descriptor_does_not_get_valuation(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """When text contains only a neutral descriptor, fallback must NOT fill valuation_text.
        Case D from spec: "El sabor es dulce." must leave valuation_text empty.
        """
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.SABOR_PARTIAL))
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
            json={'user_message': 'El sabor es dulce.'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        sabor = resp.json()['data']['analysis']['modalities']['SABOR']
        # The FakeAnalyzer already provides mention+descriptor (hardcoded about azucar tostada).
        # But accumulated_text only contains "El sabor es dulce." — no valuation pattern matches.
        assert sabor['valuation_text'] == '', 'No debe inventar valoración cuando no hay expresión valorativa'
        assert sabor['is_complete'] is False


class TestVaguenessNotFiredForModalityQuestion:
    """Case C: a short answer to a directed question must not trigger the vague reprompt."""

    def test_si_after_valuation_question_does_not_trigger_reprompt(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """After the bot asks '¿te gusta?', answering 'sí' must not produce an OPEN_REPROMPT.

        We drive ASPECTO_PARTIAL so the bot will ask for valuation.
        Then we answer 'sí' and check that the bot does NOT respond with OPEN_REPROMPT text.
        """
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ASPECTO_PARTIAL))
        session_id = participant_session['session_id']

        ev = client.post(
            '/api/v1/evaluations',
            json={'session_id': session_id, 'sample_code': 'MUESTRA_A'},
            headers=session_headers,
        )
        assert ev.status_code == 201
        eval_id = ev.json()['data']['evaluation_id']

        # Warm-up turn (INITIAL): low coverage → vague → open reprompt.
        client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'El color dorado es muy bonito y la forma es redonda.'},
            headers=session_headers,
        )
        # Next turn (intermediate) — ASPECTO_PARTIAL drives the bot to ask for valuation
        first_resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'El color dorado es muy bonito y la forma es redonda.'},
            headers=session_headers,
        )
        assert first_resp.status_code == 200
        first_data = first_resp.json()['data']
        assert first_data['current_state'] == 'MODALITY_QUESTION'
        bot_question = first_data['bot_message']
        assert 'te parece' in bot_question.lower() or 'te gusta' in bot_question.lower()

        # Second turn — short directed answer "sí"
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ASPECTO_PARTIAL))
        second_resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'sí'},
            headers=session_headers,
        )
        assert second_resp.status_code == 200
        second_data = second_resp.json()['data']

        open_reprompt_text = '¿Puedes contarme un poco más sobre esta galleta y dar más detalles?'
        assert second_data['bot_message'] != open_reprompt_text, (
            'Una respuesta dirigida "sí" no debe activar el repregunta abierto por vaguedad'
        )
        # is_vague must be False for directed modality questions
        assert second_data['analysis']['is_vague'] is False
