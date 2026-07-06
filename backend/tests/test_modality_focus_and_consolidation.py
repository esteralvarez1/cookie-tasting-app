"""Tests for per-modality LLM focus + backend consolidation.

Covers:
  * INITIAL keeps the global four-modality analysis (no focus block in the prompt).
  * MODALITY_QUESTION adds a per-modality focus block to the DYNAMIC user prompt,
    while the SYSTEM_PROMPT stays untouched.
  * Backend consolidation: in MODALITY_QUESTION only the current modality may change;
    a covered modality is never blanked nor reopened by the LLM.
  * FINAL is built from persisted/consolidated data — no new global LLM pass.
  * The structured export still contains previously covered modalities.
  * The /dialog response keeps the same structure.

Unit tests (prompt + pure consolidation helpers) need no DB logic, but the
autouse schema fixture still requires the test PostgreSQL like the rest of the suite.
"""
from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import csv
import io

import pytest

from app.core.config import settings
from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.analyzer.openai_compatible import (
    MODALITY_FOCUS_INSTRUCTIONS,
    SYSTEM_PROMPT,
    OpenAICompatibleAnalyzer,
)
from app.services.dialogue import (
    _best_persisted_modality_result,
    _build_consolidated_final_analysis,
    _consolidate_modalities_for_modality_question,
    _merge_keep_best,
)
from tests.fakes import FakeAnalyzer

_FOCUS_MARKER = 'INSTRUCCIÓN INTERNA DE FOCO'


# ---------------------------------------------------------------------------
# Prompt: focus block only for MODALITY_QUESTION, SYSTEM_PROMPT unchanged
# ---------------------------------------------------------------------------

def _make_analyzer(monkeypatch, mode: str = 'minimal') -> OpenAICompatibleAnalyzer:
    monkeypatch.setattr(settings, 'llm_context_mode', mode)
    return OpenAICompatibleAnalyzer()


def _fmt(analyzer: OpenAICompatibleAnalyzer, **overrides) -> str:
    defaults = dict(
        analysis_scope='INTERMEDIATE',
        current_state='MODALITY_QUESTION',
        current_modality='OLOR',
        user_last_message='no huele a nada',
        accumulated_text='no huele a nada',
        covered_modalities=['ASPECTO'],
        vague_retry_count=0,
        comparison_retry_count=0,
        previous_bot_question='¿Cómo describirías el olor de la galleta?',
        current_sample_code='G101',
        session_sample_codes=['G101', 'G102'],
        other_sample_codes=['G102'],
    )
    defaults.update(overrides)
    return analyzer._format_user_message(**defaults)  # type: ignore[arg-type]


class TestModalityFocusPrompt:
    def test_system_prompt_does_not_contain_focus_block(self):
        # The SYSTEM_PROMPT must stay exactly as it was: no focus instructions in it.
        assert _FOCUS_MARKER not in SYSTEM_PROMPT
        for instruction in MODALITY_FOCUS_INSTRUCTIONS.values():
            assert instruction not in SYSTEM_PROMPT

    def test_initial_turn_has_no_focus_block(self, monkeypatch):
        msg = _fmt(
            _make_analyzer(monkeypatch),
            analysis_scope='INITIAL',
            current_state='INITIAL_QUESTION',
            current_modality=None,
        )
        assert _FOCUS_MARKER not in msg

    def test_modality_question_olor_injects_olor_focus(self, monkeypatch):
        msg = _fmt(_make_analyzer(monkeypatch), current_state='MODALITY_QUESTION', current_modality='OLOR')
        assert _FOCUS_MARKER in msg
        assert 'no huele a nada' in msg  # part of the OLOR instruction
        assert MODALITY_FOCUS_INSTRUCTIONS['OLOR'] in msg

    def test_modality_question_sabor_injects_sabor_focus(self, monkeypatch):
        msg = _fmt(_make_analyzer(monkeypatch), current_state='MODALITY_QUESTION', current_modality='SABOR')
        assert MODALITY_FOCUS_INSTRUCTIONS['SABOR'] in msg
        assert 'sin sabor' in msg

    def test_focus_block_injected_in_legacy_mode_too(self, monkeypatch):
        msg = _fmt(
            _make_analyzer(monkeypatch, 'legacy'),
            current_state='MODALITY_QUESTION',
            current_modality='TEXTURA',
        )
        assert _FOCUS_MARKER in msg
        assert MODALITY_FOCUS_INSTRUCTIONS['TEXTURA'] in msg


# ---------------------------------------------------------------------------
# Pure consolidation helpers
# ---------------------------------------------------------------------------

def _row(modality, mention, descriptor, valuation, complete):
    return SimpleNamespace(
        modality=modality,
        mention_text=mention,
        descriptor_text=descriptor,
        valuation_text=valuation,
        is_complete=complete,
    )


def _persisted_analysis(rows, created):
    return SimpleNamespace(modalities=rows, created_at=created)


def _evaluation(analyses):
    return SimpleNamespace(analyses=analyses)


_T0 = datetime(2026, 6, 13, 10, 0, 0, tzinfo=timezone.utc)


class TestConsolidationHelpers:
    def test_best_persisted_keeps_complete_over_later_empty(self):
        ev = _evaluation([
            _persisted_analysis([_row('ASPECTO', 'es dorada', 'dorado', 'me gusta', True)], _T0),
            _persisted_analysis([_row('ASPECTO', '', '', '', False)], _T0 + timedelta(minutes=1)),
        ])
        result = _best_persisted_modality_result(ev, 'ASPECTO')
        assert result.is_complete is True
        assert result.descriptor_text == 'dorado'

    def test_best_persisted_empty_when_no_analyses(self):
        assert _best_persisted_modality_result(_evaluation([]), 'OLOR').mention_text == ''

    def test_merge_keep_best_complete_wins_even_as_secondary(self):
        complete = ModalityResult(mention_text='m', descriptor_text='d', valuation_text='v', is_complete=True)
        empty = ModalityResult()
        assert _merge_keep_best(empty, complete).is_complete is True
        assert _merge_keep_best(complete, empty).is_complete is True

    def test_consolidation_only_updates_current_modality(self):
        ev = _evaluation([
            _persisted_analysis([
                _row('ASPECTO', 'es dorada', 'dorado', 'me gusta', True),
                _row('OLOR', '', '', '', False),
                _row('TEXTURA', '', '', '', False),
                _row('SABOR', '', '', '', False),
            ], _T0),
        ])
        # LLM tried to blank ASPECTO and invent SABOR while the bot asked OLOR.
        llm = AnalysisResult(
            analysis_scope='INTERMEDIATE', is_vague=False, has_comparison=False, reasoning_summary='',
            modalities={
                'ASPECTO': ModalityResult(),  # blanked
                'OLOR': ModalityResult(mention_text='no huele', descriptor_text='sin olor', valuation_text='me da igual', is_complete=True),
                'TEXTURA': ModalityResult(),
                'SABOR': ModalityResult(mention_text='dulce', descriptor_text='dulce', valuation_text='rico', is_complete=True),
            },
        )
        out = _consolidate_modalities_for_modality_question(ev, llm, 'OLOR')
        # ASPECTO preserved from persisted (not blanked)
        assert out.modalities['ASPECTO'].is_complete is True
        assert out.modalities['ASPECTO'].descriptor_text == 'dorado'
        # OLOR updated from the LLM
        assert out.modalities['OLOR'].descriptor_text == 'sin olor'
        # SABOR invented by the LLM is ignored (restored from persisted = empty)
        assert out.modalities['SABOR'].mention_text == ''

    def test_build_final_consolidates_from_persisted_without_llm(self):
        ev = _evaluation([
            _persisted_analysis([_row('ASPECTO', 'es dorada', 'dorado', 'me gusta', True)], _T0),
        ])
        final = _build_consolidated_final_analysis(ev, final_analysis=None)
        assert final.analysis_scope == 'FINAL'
        assert final.modalities['ASPECTO'].is_complete is True
        assert final.modalities['ASPECTO'].descriptor_text == 'dorado'
        assert final.modalities['OLOR'].is_complete is False


# ---------------------------------------------------------------------------
# Integration via the /dialog endpoint
# ---------------------------------------------------------------------------

_RICH_MESSAGE = (
    'El color es dorado y la forma redonda, la textura es muy crujiente, '
    'sabe dulce con un toque de vainilla y huele muy bien, me gusta mucho'
)


class _ScopeRecordingAnalyzer(FakeAnalyzer):
    """FakeAnalyzer that records every analysis_scope it is asked for."""

    def __init__(self, scenario: str) -> None:
        super().__init__(scenario)
        self.scopes: list[str] = []

    async def analyze(self, *, analysis_scope, **kwargs):  # type: ignore[override]
        self.scopes.append(analysis_scope)
        return await super().analyze(analysis_scope=analysis_scope, **kwargs)


class TestConsolidationViaApi:
    def _import_service(self):
        from app.api.routes.evaluations import service
        return service

    def test_initial_analyzes_four_modalities(self, client, evaluation, session_headers, monkeypatch):
        service = self._import_service()
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        )
        assert resp.status_code == 200
        modalities = resp.json()['data']['analysis']['modalities']
        for mod in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert mod in modalities

    def test_covered_modality_preserved_and_not_reopened(self, client, evaluation, session_headers, monkeypatch):
        service = self._import_service()
        eval_id = evaluation['evaluation_id']
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ASPECTO_COMPLETE))

        # Turn 1 (INITIAL): only 1 modality complete → vague → open reprompt.
        client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        )
        # Turn 2 (intermediate): not vague → ASPECTO covered, bot asks OLOR.
        first = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        ).json()['data']
        assert first['current_state'] == 'MODALITY_QUESTION'
        assert first['current_modality'] == 'OLOR'
        assert first['analysis']['modalities']['ASPECTO']['is_complete'] is True

        # Turn 2 (MODALITY_QUESTION=OLOR): LLM returns ALL EMPTY.
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        second = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'no estoy seguro'},
            headers=session_headers,
        ).json()['data']
        # ASPECTO must NOT be blanked by the empty LLM response.
        assert second['analysis']['modalities']['ASPECTO']['is_complete'] is True
        assert second['analysis']['modalities']['ASPECTO']['descriptor_text']
        # ASPECTO must NOT be reopened: the bot keeps asking OLOR, not ASPECTO.
        assert second['current_modality'] == 'OLOR'

    def test_response_structure_unchanged(self, client, evaluation, session_headers, monkeypatch):
        service = self._import_service()
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        data = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        ).json()['data']
        for key in ('evaluation_id', 'current_state', 'current_modality', 'bot_message', 'analysis', 'next_step', 'turns'):
            assert key in data
        analysis = data['analysis']
        for key in ('is_vague', 'has_comparison', 'next_action', 'modalities'):
            assert key in analysis

    def test_final_does_not_call_llm_with_final_scope(self, client, evaluation, session_headers, monkeypatch):
        service = self._import_service()
        spy = _ScopeRecordingAnalyzer(FakeAnalyzer.ALL_COMPLETE)
        monkeypatch.setattr(service, 'analyzer', spy)
        resp = client.post(
            f'/api/v1/evaluations/{evaluation["evaluation_id"]}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        )
        assert resp.status_code == 200
        assert resp.json()['data']['status'] == 'COMPLETED'
        # finalize_evaluation must NOT ask the analyzer for a global FINAL analysis.
        assert 'FINAL' not in spy.scopes

    def test_final_consolidated_keeps_covered_modality_in_export(
        self, client, evaluation, participant_session, session_headers, admin_headers, researcher_headers, monkeypatch
    ):
        service = self._import_service()
        eval_id = evaluation['evaluation_id']
        session_id = participant_session['session_id']

        # ASPECTO complete, then force-finalize (admin) → FINAL consolidated from persisted data.
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ASPECTO_COMPLETE))
        client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': _RICH_MESSAGE},
            headers=session_headers,
        )
        fin = client.post(
            f'/api/v1/evaluations/{eval_id}/finalize',
            json={'reason': 'TEST'},
            headers=admin_headers,
        )
        assert fin.status_code == 200

        resp = client.get(f'/api/v1/export/structured?session_id={session_id}', headers=researcher_headers)
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        # The covered ASPECTO modality must survive into the FINAL/export, not be blank.
        assert rows[0]['ASPECTO:DESCRIPTOR']
