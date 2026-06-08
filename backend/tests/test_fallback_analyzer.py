"""Tests for FallbackAnalyzer — automatic fallback when the LLM fails.

Unit tests call analyze() directly via asyncio.run() (no pytest-asyncio required).
Integration tests use the HTTP client with monkeypatch to replace service.analyzer.
"""
from __future__ import annotations

import asyncio

from app.api.routes.evaluations import service
from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.fallback import FallbackAnalyzer
from app.services.analyzer.models import AnalysisResult, AnalyzerUnavailableError, ModalityResult
from app.services.analyzer.rules import RuleBasedAnalyzer
from tests.fakes import FakeAnalyzer

# ── Shared helpers ────────────────────────────────────────────────────────────

_ANALYZE_KWARGS: dict = dict(
    analysis_scope='INITIAL',
    current_state='INITIAL_QUESTION',
    current_modality=None,
    user_last_message='La galleta es crujiente y tiene un buen sabor dulce.',
    accumulated_text='La galleta es crujiente y tiene un buen sabor dulce.',
    covered_modalities=[],
    vague_retry_count=0,
    comparison_retry_count=0,
)

_RICH_MESSAGE = (
    'La galleta tiene color dorado, textura muy crujiente, '
    'sabe dulce y huele bien, me gusta mucho'
)


class _FailingAnalyzer(BaseAnalyzer):
    """Test double that always raises AnalyzerUnavailableError."""

    provider_name = 'failing-llm'
    model_name = 'failing-model'
    prompt_version = 'failing-v1'

    async def analyze(
        self,
        analysis_scope: str,
        current_state: str,
        current_modality: str | None,
        user_last_message: str,
        accumulated_text: str,
        covered_modalities: list[str],
        vague_retry_count: int,
        comparison_retry_count: int,
        previous_bot_question: str | None = None,
        current_sample_code: str | None = None,
        session_sample_codes: list[str] | None = None,
        other_sample_codes: list[str] | None = None,
    ) -> AnalysisResult:
        raise AnalyzerUnavailableError('Simulated LLM failure')


# ── Unit tests ────────────────────────────────────────────────────────────────

class TestFallbackAnalyzerUnit:
    """Direct calls to FallbackAnalyzer.analyze() — no DB or HTTP layer."""

    def test_primary_success_returns_primary_result(self):
        """When primary succeeds, the primary result is returned unchanged."""
        primary = FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE)
        analyzer = FallbackAnalyzer(primary, RuleBasedAnalyzer())

        result = asyncio.run(analyzer.analyze(**_ANALYZE_KWARGS))

        assert result.reasoning_summary == 'Todas las modalidades completas'
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert result.modalities[m].is_complete is True

    def test_primary_failure_returns_fallback_result(self):
        """When primary raises AnalyzerUnavailableError, RuleBasedAnalyzer result is returned."""
        analyzer = FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer())

        result = asyncio.run(analyzer.analyze(**_ANALYZE_KWARGS))

        assert isinstance(result, AnalysisResult)
        assert 'ASPECTO' in result.modalities

    def test_primary_failure_does_not_propagate_exception(self):
        """FallbackAnalyzer must swallow AnalyzerUnavailableError from the primary."""
        analyzer = FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer())

        # Must not raise — if it did, asyncio.run() would propagate it
        asyncio.run(analyzer.analyze(**_ANALYZE_KWARGS))

    def test_metadata_reflects_primary_analyzer(self):
        """provider_name / model_name / prompt_version should come from the primary."""
        primary = _FailingAnalyzer()
        analyzer = FallbackAnalyzer(primary, RuleBasedAnalyzer())

        assert analyzer.provider_name == primary.provider_name
        assert analyzer.model_name == primary.model_name
        assert analyzer.prompt_version == primary.prompt_version

    def test_fallback_result_has_correct_structure(self):
        """The AnalysisResult returned by fallback must have all four modalities."""
        analyzer = FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer())

        result = asyncio.run(analyzer.analyze(**_ANALYZE_KWARGS))

        for modality in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert modality in result.modalities
            mr = result.modalities[modality]
            assert isinstance(mr, ModalityResult)


# ── Integration tests ─────────────────────────────────────────────────────────

class TestFallbackDialogIntegration:
    """End-to-end tests via HTTP TestClient with a monkeypatched service.analyzer."""

    def _send_dialog(self, client, eval_id: str, headers: dict, message: str = _RICH_MESSAGE) -> dict:
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': message},
            headers=headers,
        )
        assert resp.status_code == 200
        return resp.json()['data']

    def test_endpoint_returns_200_when_primary_fails(self, client, evaluation, session_headers, monkeypatch):
        """Dialog endpoint must return 200 even when the primary analyzer always fails."""
        monkeypatch.setattr(service, 'analyzer', FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer()))

        data = self._send_dialog(client, evaluation['evaluation_id'], session_headers)

        assert data['bot_message']

    def test_analysis_block_is_present_with_fallback(self, client, evaluation, session_headers, monkeypatch):
        """When fallback is used, the analysis block must be populated (not None)."""
        monkeypatch.setattr(service, 'analyzer', FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer()))

        data = self._send_dialog(client, evaluation['evaluation_id'], session_headers)

        assert data['analysis'] is not None
        assert 'modalities' in data['analysis']
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert m in data['analysis']['modalities']

    def test_response_structure_unchanged_with_fallback(self, client, evaluation, session_headers, monkeypatch):
        """The API response structure must be identical whether LLM or fallback ran."""
        monkeypatch.setattr(service, 'analyzer', FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer()))

        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body['success'] is True
        data = body['data']
        assert 'bot_message' in data
        assert 'analysis' in data
        assert 'turns' in data
        assert 'status' in data

    def test_evaluation_stays_in_progress_when_primary_fails(self, client, evaluation, session_headers, monkeypatch):
        """Evaluation status must remain IN_PROGRESS — never errored — when fallback runs."""
        monkeypatch.setattr(service, 'analyzer', FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer()))

        data = self._send_dialog(client, evaluation['evaluation_id'], session_headers)

        assert data['status'] == 'IN_PROGRESS'

    def test_primary_succeeds_flow_unaffected(self, client, evaluation, session_headers, monkeypatch):
        """When primary succeeds, the flow is identical to a plain FakeAnalyzer."""
        working_primary = FakeAnalyzer(FakeAnalyzer.NORMAL)
        monkeypatch.setattr(service, 'analyzer', FallbackAnalyzer(working_primary, RuleBasedAnalyzer()))

        data = self._send_dialog(client, evaluation['evaluation_id'], session_headers)

        assert data['bot_message']
        assert data['analysis'] is not None
