"""Regression tests for LLM context minimisation (LLM_CONTEXT_MODE=minimal).

Tests A, B, C, F — pure Python unit tests, no DB access by the test logic itself.
Tests D, E      — integration tests via FakeAnalyzer + HTTP client (require Docker
                  PostgreSQL on port 5434, same as the rest of the test suite).

Run all:
    cd backend && python -m pytest tests/test_llm_context.py -v

Run only unit tests (still needs DB fixture — use -k to filter):
    python -m pytest tests/test_llm_context.py -v -k "unit"

To revert to legacy context temporarily:
    Set LLM_CONTEXT_MODE=legacy in .env (or export LLM_CONTEXT_MODE=legacy before running).
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.analyzer.openai_compatible import OpenAICompatibleAnalyzer
from app.services.dialogue import _apply_comparison_guard
from app.services.messages import OPEN_REPROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_analyzer(monkeypatch, mode: str = 'minimal') -> OpenAICompatibleAnalyzer:
    monkeypatch.setattr(settings, 'llm_context_mode', mode)
    return OpenAICompatibleAnalyzer()


def _call_format(analyzer: OpenAICompatibleAnalyzer, **overrides) -> str:
    defaults = dict(
        analysis_scope='INTERMEDIATE',
        current_state='MODALITY_QUESTION',
        current_modality='TEXTURA',
        user_last_message='Es crujiente y me gusta bastante',
        accumulated_text='Es crujiente y me gusta bastante',
        covered_modalities=['ASPECTO'],
        vague_retry_count=0,
        comparison_retry_count=1,
        previous_bot_question='¿Te ha gustado la textura?',
        current_sample_code='G101',
        session_sample_codes=['G101', 'G102', 'G103'],
        other_sample_codes=['G102', 'G103'],
    )
    defaults.update(overrides)
    return analyzer._format_user_message(**defaults)  # type: ignore[arg-type]


def _empty_modalities() -> dict[str, ModalityResult]:
    return {m: ModalityResult() for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}


# ---------------------------------------------------------------------------
# A — payload minimal contiene exactamente los cuatro campos permitidos
# ---------------------------------------------------------------------------

class TestPayloadMinimal:
    """A — verify that minimal mode sends only the four allowed context fields."""

    def test_minimal_contains_current_state(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'current_state:' in msg

    def test_minimal_contains_current_modality(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'current_modality:' in msg

    def test_minimal_contains_other_sample_codes(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'other_sample_codes:' in msg

    def test_minimal_contains_pregunta_previa(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'pregunta_previa_del_bot:' in msg

    def test_minimal_excludes_covered_modalities(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'covered_modalities:' not in msg

    def test_minimal_excludes_vague_retry_count(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'vague_retry_count:' not in msg

    def test_minimal_excludes_comparison_retry_count(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'comparison_retry_count:' not in msg

    def test_minimal_excludes_analysis_scope_from_context(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'analysis_scope:' not in msg

    def test_minimal_excludes_current_sample_code(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'current_sample_code:' not in msg

    def test_minimal_excludes_session_sample_codes(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'))
        assert 'session_sample_codes:' not in msg

    def test_legacy_contains_all_fields(self, monkeypatch):
        """Sanity: legacy mode still sends the full context."""
        msg = _call_format(_make_analyzer(monkeypatch, 'legacy'))
        for field in ('analysis_scope:', 'covered_modalities:', 'vague_retry_count:',
                      'comparison_retry_count:', 'current_sample_code:', 'session_sample_codes:'):
            assert field in msg, f'Expected {field!r} in legacy context'


# ---------------------------------------------------------------------------
# B — pregunta_previa_del_bot contiene solo la última pregunta del bot
# ---------------------------------------------------------------------------

class TestPreguntaPrevia:
    """B — pregunta_previa_del_bot is exactly the last bot question, nothing more."""

    def test_pregunta_previa_appears_exactly_once(self, monkeypatch):
        question = '¿Te ha gustado la textura?'
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'), previous_bot_question=question)
        assert msg.count('pregunta_previa_del_bot:') == 1

    def test_pregunta_previa_contains_the_question_text(self, monkeypatch):
        question = '¿Te ha gustado la textura?'
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'), previous_bot_question=question)
        assert question in msg

    def test_no_pregunta_previa_when_none(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'), previous_bot_question=None)
        assert 'pregunta_previa_del_bot:' not in msg

    def test_empty_pregunta_previa_is_omitted(self, monkeypatch):
        msg = _call_format(_make_analyzer(monkeypatch, 'minimal'), previous_bot_question='')
        assert 'pregunta_previa_del_bot:' not in msg

    def test_user_messages_not_in_context_section(self, monkeypatch):
        question = '¿Te ha gustado la textura?'
        accumulated = 'Es crujiente y seca. ¿Te ha gustado la textura?'  # bot text also in acc
        msg = _call_format(
            _make_analyzer(monkeypatch, 'minimal'),
            previous_bot_question=question,
            accumulated_text=accumulated,
        )
        # The CONTEXTO section must contain the question only once (via pregunta_previa_del_bot)
        context_section = msg.split('CONTEXTO DE LA CONVERSACIÓN:')[-1]
        assert context_section.count(question) == 1


# ---------------------------------------------------------------------------
# C — comparación detectada por guard de Python aunque LLM devuelva False
# ---------------------------------------------------------------------------

class TestComparisonGuard:
    """C — Python guard forces has_comparison=True when LLM missed it."""

    def test_guard_fires_on_other_sample_code_in_message(self):
        analysis = AnalysisResult(
            analysis_scope='INTERMEDIATE',
            is_vague=False,
            has_comparison=False,
            reasoning_summary='',
            modalities=_empty_modalities(),
        )
        result = _apply_comparison_guard(analysis, 'G103 estaba mejor', ['G102', 'G103'])
        assert result.has_comparison is True

    def test_guard_fires_on_generic_comparison_marker(self):
        analysis = AnalysisResult(
            analysis_scope='INTERMEDIATE',
            is_vague=False,
            has_comparison=False,
            reasoning_summary='',
            modalities=_empty_modalities(),
        )
        result = _apply_comparison_guard(analysis, 'me gusta más que la anterior', [])
        assert result.has_comparison is True

    def test_guard_does_not_overwrite_true(self):
        analysis = AnalysisResult(
            analysis_scope='INTERMEDIATE',
            is_vague=False,
            has_comparison=True,
            reasoning_summary='',
            modalities=_empty_modalities(),
        )
        result = _apply_comparison_guard(analysis, 'es crujiente', [])
        assert result.has_comparison is True

    def test_guard_does_not_fire_on_intensifier(self):
        analysis = AnalysisResult(
            analysis_scope='INTERMEDIATE',
            is_vague=False,
            has_comparison=False,
            reasoning_summary='',
            modalities=_empty_modalities(),
        )
        result = _apply_comparison_guard(analysis, 'es muy crujiente', ['G102', 'G103'])
        assert result.has_comparison is False


# ---------------------------------------------------------------------------
# D — respuesta sensorial normal: descriptor y valoración pasan sin corrupción
# ---------------------------------------------------------------------------

class TestNormalSensoryResponse:
    """D — pipeline preserves sensory data from a normal response turn."""

    def test_complete_modalities_trigger_sample_close(self, client, evaluation, session_headers, monkeypatch):
        from app.api.routes.evaluations import service
        from tests.fakes import FakeAnalyzer
        from app.services.messages import SAMPLE_COMPLETED_MESSAGE

        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'Es crujiente y me gusta bastante, dorada y bonita, huele bien, sabor dulce'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['bot_message'] == SAMPLE_COMPLETED_MESSAGE

    def test_analysis_returns_modality_data_unchanged(self, client, evaluation, session_headers, monkeypatch):
        from app.api.routes.evaluations import service
        from tests.fakes import FakeAnalyzer

        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'Es crujiente y me gusta bastante'},
            headers=session_headers,
        )
        assert resp.status_code == 200
        modalities = resp.json()['data']['analysis']['modalities']
        # All four modalities should be is_complete=True (FakeAnalyzer.ALL_COMPLETE)
        for mod in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert modalities[mod]['is_complete'] is True, f'{mod} should be complete'


# ---------------------------------------------------------------------------
# E — respuesta corta en estado MODALITY_QUESTION no se marca como vaga
# ---------------------------------------------------------------------------

class TestShortContextualResponse:
    """E — is_vague is suppressed when current_state=MODALITY_QUESTION."""

    def test_vague_result_suppressed_in_modality_question_state(
        self, client, evaluation, session_headers, monkeypatch
    ):
        from app.api.routes.evaluations import service
        from tests.fakes import FakeAnalyzer

        # First turn: NORMAL → FlowDecisionEngine will ask about first pending modality
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        resp1 = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'Está dorada y crujiente, huele bien, sabor dulce'},
            headers=session_headers,
        )
        assert resp1.status_code == 200
        assert resp1.json()['data']['current_state'] == 'MODALITY_QUESTION'

        # Second turn: FakeAnalyzer returns VAGUE, but state is now MODALITY_QUESTION
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.VAGUE))
        resp2 = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'Sí, me gusta'},
            headers=session_headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()['data']
        # is_vague must be False — suppressed by step 7c in dialogue.py
        assert data2['analysis']['is_vague'] is False
        # Bot must NOT have sent the open reprompt message
        assert data2['bot_message'] != OPEN_REPROMPT


# ---------------------------------------------------------------------------
# F — other_sample_codes excluye la muestra actual
# ---------------------------------------------------------------------------

class TestOtherSampleCodes:
    """F — other_sample_codes must not include current_sample_code."""

    def test_current_sample_not_in_other_codes_line(self, monkeypatch):
        msg = _call_format(
            _make_analyzer(monkeypatch, 'minimal'),
            current_sample_code='G101',
            session_sample_codes=['G101', 'G102', 'G103'],
            other_sample_codes=['G102', 'G103'],  # G101 already excluded by dialogue.py
        )
        for line in msg.splitlines():
            if 'other_sample_codes:' in line:
                assert 'G101' not in line, 'current_sample_code must not appear in other_sample_codes'

    def test_empty_other_codes_when_single_sample(self, monkeypatch):
        msg = _call_format(
            _make_analyzer(monkeypatch, 'minimal'),
            current_sample_code='G101',
            session_sample_codes=['G101'],
            other_sample_codes=[],
        )
        assert 'other_sample_codes:' not in msg

    def test_prompt_version_reflects_mode(self, monkeypatch):
        from app.services.analyzer.openai_compatible import PROMPT_VERSION_MINIMAL, PROMPT_VERSION_LEGACY

        analyzer_min = _make_analyzer(monkeypatch, 'minimal')
        assert analyzer_min.prompt_version == PROMPT_VERSION_MINIMAL

        analyzer_leg = _make_analyzer(monkeypatch, 'legacy')
        assert analyzer_leg.prompt_version == PROMPT_VERSION_LEGACY
