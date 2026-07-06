"""is_vague is decided by the backend from modality coverage, never by the LLM.

Rule: vague means the INITIAL open answer does not cover enough COMPLETE modalities.
  - MODALITY_QUESTION turns        → is_vague = False
  - non-initial (intermediate) turns → is_vague = False
  - INITIAL turn                   → is_vague = True when <= 2 modalities complete
Comparison detection is deterministic and has priority over vagueness in the flow.
"""
from __future__ import annotations

import pytest

from app.api.routes.evaluations import service
from app.models.enums import AnalysisScope, EvaluationState
from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.dialogue import _compute_is_vague_from_coverage
from app.services.messages import COMPARISON_REFORMULATION, OPEN_REPROMPT
from tests.fakes import FakeAnalyzer

_ORDER = ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')


def _analysis_with_n_complete(n: int) -> AnalysisResult:
    mods: dict[str, ModalityResult] = {}
    for i, modality in enumerate(_ORDER):
        if i < n:
            mods[modality] = ModalityResult(
                mention_text='m', descriptor_text='d', valuation_text='v', is_complete=True,
            )
        else:
            mods[modality] = ModalityResult()
    return AnalysisResult(analysis_scope=AnalysisScope.INITIAL.value, modalities=mods)


_INITIAL = AnalysisScope.INITIAL.value
_INTERMEDIATE = AnalysisScope.INTERMEDIATE.value
_INITIAL_STATE = EvaluationState.INITIAL_QUESTION.value
_MODALITY_STATE = EvaluationState.MODALITY_QUESTION.value


class TestComputeIsVagueFromCoverage:
    @pytest.mark.parametrize('n_complete, expected', [
        (0, True),   # initial, 0 complete
        (1, True),   # case 1
        (2, True),   # case 2
        (3, False),  # case 3
        (4, False),  # case 4
    ])
    def test_initial_turn_depends_on_coverage(self, n_complete, expected):
        analysis = _analysis_with_n_complete(n_complete)
        assert _compute_is_vague_from_coverage(_INITIAL, _INITIAL_STATE, analysis) is expected

    def test_modality_question_is_always_false(self):
        # Case 5: even with 0 complete modalities, a directed modality turn is never vague.
        analysis = _analysis_with_n_complete(0)
        assert _compute_is_vague_from_coverage(_INITIAL, _MODALITY_STATE, analysis) is False
        assert _compute_is_vague_from_coverage(_INTERMEDIATE, _MODALITY_STATE, analysis) is False

    def test_non_initial_turn_is_always_false(self):
        # Intermediate (non-initial) turns are never vague, regardless of coverage.
        analysis = _analysis_with_n_complete(0)
        assert _compute_is_vague_from_coverage(_INTERMEDIATE, _INITIAL_STATE, analysis) is False


class TestIsVagueViaApi:
    def test_initial_low_coverage_triggers_open_reprompt(self, client, evaluation, session_headers, monkeypatch):
        # FakeAnalyzer.NORMAL → 0 complete modalities on the INITIAL turn → is_vague True.
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'No sé, simplemente está ahí, una galleta cualquiera'},
            headers=session_headers,
        )
        data = resp.json()['data']
        assert data['analysis']['is_vague'] is True
        assert data['bot_message'] == OPEN_REPROMPT

    def test_initial_high_coverage_is_not_vague(self, client, evaluation, session_headers, monkeypatch):
        # ALL_COMPLETE → 4 complete modalities → is_vague False (and the sample closes).
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'Dorada y bonita, huele a mantequilla y me gusta, crujiente y agradable, sabor dulce rico'},
            headers=session_headers,
        )
        assert resp.json()['data']['analysis']['is_vague'] is False

    def test_comparison_has_priority_over_vagueness(self, client, evaluation, session_headers, monkeypatch):
        # Case 6: an INITIAL answer that is both comparative and low-coverage must trigger
        # the reformulation request (comparison wins), and has_comparison must be detected.
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.COMPARISON))
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': 'Es mejor que la anterior'},
            headers=session_headers,
        )
        data = resp.json()['data']
        assert data['analysis']['has_comparison'] is True
        assert data['bot_message'] == COMPARISON_REFORMULATION
        assert data['bot_message'] != OPEN_REPROMPT
