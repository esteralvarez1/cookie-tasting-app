"""End-to-end 'real case' from the reference Excel: preserve evidence, fill only the
missing field, and never let a valuation of one modality come from another modality.

Reference interaction:
  Initial open answer mentions ASPECTO ("apagada, no muy dorada") and SABOR
  ("sabor rico pero muy suave"). Then the bot asks the ASPECTO valuation and the
  user replies "no me encanta".

Expected:
  ASPECTO.mention/descriptor preserved, ASPECTO.valuation = "no me encanta".
  SABOR.valuation must NOT be the ASPECTO sentence ("Aparentemente tiene un aspecto...").
"""
from __future__ import annotations

import pytest

from app.api.routes.evaluations import service
from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.models import AnalysisResult, ModalityResult
from app.services.modality_metadata import find_valuation_in_text

_MODALITIES = ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')

_INITIAL_TEXT = (
    'Aparentemente tiene un aspecto un poco apagada, es decir, no esta muy dorada '
    'lo que hace pensar que puede que sea insipida. '
    'Cuando la he probado tiene un sabor rico pero pienso que es muy suave.'
)
_ASPECT_SENTENCE = 'Aparentemente tiene un aspecto un poco apagada, es decir, no esta muy dorada lo que hace pensar que puede que sea insipida.'
_SABOR_SENTENCE = 'Cuando la he probado tiene un sabor rico pero pienso que es muy suave.'


# ---------------------------------------------------------------------------
# Unit: a valuation must never be pulled from another modality's sentence
# ---------------------------------------------------------------------------

class TestNoCrossModalValuationSource:
    def test_sabor_valuation_not_taken_from_aspect_sentence(self):
        result = find_valuation_in_text(_INITIAL_TEXT, 'SABOR')
        assert not result.startswith('Aparentemente tiene un aspecto')
        # It should pick the genuine SABOR sentence instead.
        assert 'sabor rico' in result.lower()

    def test_aspect_only_sentence_gives_no_sabor_valuation(self):
        only_aspect = 'Aparentemente tiene un aspecto un poco apagada, no esta muy dorada, puede que sea insipida.'
        assert find_valuation_in_text(only_aspect, 'SABOR') == ''


# ---------------------------------------------------------------------------
# Integration: the full /dialog pipeline on the real two-turn case
# ---------------------------------------------------------------------------

class _RealCaseAnalyzer(BaseAnalyzer):
    """On the INITIAL turn returns ASPECTO (mention+descriptor, no valuation) and
    SABOR (mention+descriptor, no valuation). On later turns returns nothing, so the
    backend consolidation/valuation-only logic is what must do the right thing."""

    provider_name = 'fake'
    model_name = 'fake-v1'
    prompt_version = 'fake_v1'

    async def analyze(self, *, analysis_scope, current_state, current_modality, **kwargs):  # type: ignore[override]
        mods = {m: ModalityResult() for m in _MODALITIES}
        if current_state == 'INITIAL_QUESTION':
            mods['ASPECTO'] = ModalityResult(
                mention_text=_ASPECT_SENTENCE, descriptor_text='apagada, no muy dorada',
                valuation_text='', is_complete=False,
            )
            # SABOR has mention+descriptor but no valuation, so the deterministic fallback
            # must fill it from the genuine SABOR sentence (exercising the dominance guard).
            mods['SABOR'] = ModalityResult(
                mention_text=_SABOR_SENTENCE, descriptor_text='rico, suave',
                valuation_text='', is_complete=False,
            )
            # OLOR/TEXTURA completed here only so the INITIAL answer covers >= 3 modalities
            # and is not flagged vague; the focus of the test is ASPECTO + SABOR.
            mods['OLOR'] = ModalityResult(
                mention_text='huele a mantequilla', descriptor_text='mantequilla',
                valuation_text='me gusta', is_complete=True,
            )
            mods['TEXTURA'] = ModalityResult(
                mention_text='es crujiente', descriptor_text='crujiente',
                valuation_text='agradable', is_complete=True,
            )
        return AnalysisResult(
            analysis_scope=analysis_scope, is_vague=False, has_comparison=False,
            reasoning_summary='', modalities=mods,
        )


class TestRealCaseViaApi:
    def test_aspecto_preserved_and_sabor_not_contaminated(
        self, client, evaluation, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', _RealCaseAnalyzer())
        eval_id = evaluation['evaluation_id']

        # Turn 1 — open initial answer.
        first = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': _INITIAL_TEXT},
            headers=session_headers,
        ).json()['data']
        # The bot must now ask the ASPECTO valuation (descriptor present, valuation missing).
        assert first['current_state'] == 'MODALITY_QUESTION'
        assert first['current_modality'] == 'ASPECTO'
        assert 'te gusta' in first['bot_message'].lower()

        # Turn 2 — short valuation-only answer.
        second = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'no me encanta'},
            headers=session_headers,
        ).json()['data']
        mods = second['analysis']['modalities']

        # ASPECTO: mention + descriptor preserved, valuation filled, complete.
        assert mods['ASPECTO']['mention_text'] == _ASPECT_SENTENCE
        assert mods['ASPECTO']['descriptor_text'] == 'apagada, no muy dorada'
        assert mods['ASPECTO']['valuation_text'] == 'no me encanta'
        assert mods['ASPECTO']['is_complete'] is True

        # SABOR: must not be contaminated by the ASPECTO sentence.
        assert not mods['SABOR']['valuation_text'].startswith('Aparentemente tiene un aspecto')
        assert not mods['SABOR']['mention_text'].startswith('Aparentemente tiene un aspecto')
        # SABOR keeps its own evidence from turn 1.
        assert mods['SABOR']['descriptor_text'] == 'rico, suave'
