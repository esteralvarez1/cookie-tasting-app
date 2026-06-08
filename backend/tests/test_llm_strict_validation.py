"""Strict validation of LLM JSON responses in OpenAICompatibleAnalyzer.

Tests call _parse_analysis_response() directly so no HTTP layer or DB is needed.
The helper _wrap() wraps a modalities dict into the full fake LLM response JSON
that _extract_content() expects.
"""
from __future__ import annotations

import json

import pytest

from app.services.analyzer.models import AnalyzerUnavailableError
from app.services.analyzer.openai_compatible import OpenAICompatibleAnalyzer

_analyzer = OpenAICompatibleAnalyzer()

# ── Fixtures ─────────────────────────────────────────────────────────────────

_EMPTY_MOD = {'mention_text': '', 'descriptor_text': '', 'valuation_text': '', 'is_complete': False}
_FULL_MOD = {'mention_text': 'Tiene color dorado', 'descriptor_text': 'color dorado', 'valuation_text': 'me gusta', 'is_complete': True}

_ALL_VALID = {
    'ASPECTO': dict(_FULL_MOD),
    'OLOR': dict(_EMPTY_MOD),
    'TEXTURA': dict(_EMPTY_MOD),
    'SABOR': dict(_EMPTY_MOD),
}


def _wrap(modalities_value) -> dict:
    """Wrap a modalities value into a fake LLM response JSON understood by _extract_content."""
    return {
        'choices': [{
            'message': {
                'content': json.dumps({
                    'analysis_scope': 'INITIAL',
                    'is_vague': False,
                    'has_comparison': False,
                    'reasoning_summary': 'Test',
                    'modalities': modalities_value,
                })
            }
        }]
    }


def _parse(modalities_value) -> object:
    return _analyzer._parse_analysis_response(_wrap(modalities_value), 'INITIAL')


# ── Acceptance tests ──────────────────────────────────────────────────────────

class TestValidResponseAccepted:
    def test_valid_four_modalities_accepted(self):
        result = _parse(_ALL_VALID)
        assert result.modalities['ASPECTO'].is_complete is True
        assert result.modalities['OLOR'].is_complete is False

    def test_all_empty_modalities_accepted(self):
        mods = {k: dict(_EMPTY_MOD) for k in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}
        result = _parse(mods)
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert result.modalities[m].is_complete is False

    def test_returns_analysis_result_with_all_four_modalities(self):
        result = _parse(_ALL_VALID)
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert m in result.modalities


# ── Rejection tests — modalities container ────────────────────────────────────

class TestModalitiesContainerRejected:
    def test_modalities_as_list_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse([])

    def test_modalities_as_empty_list_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse([{'ASPECTO': _EMPTY_MOD}])

    def test_modalities_as_null_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(None)

    def test_modalities_as_string_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse('ASPECTO,OLOR,TEXTURA,SABOR')

    def test_modalities_missing_raises(self):
        # Build content manually without 'modalities' key
        content = json.dumps({'is_vague': False, 'has_comparison': False})
        resp = {'choices': [{'message': {'content': content}}]}
        with pytest.raises(AnalyzerUnavailableError):
            _analyzer._parse_analysis_response(resp, 'INITIAL')


# ── Rejection tests — wrong modality keys ─────────────────────────────────────

class TestWrongModalityKeys:
    def test_missing_sabor_raises(self):
        mods = {k: dict(_EMPTY_MOD) for k in ('ASPECTO', 'OLOR', 'TEXTURA')}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(mods)

    def test_missing_all_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse({})

    def test_extra_modality_raises(self):
        mods = {**{k: dict(_EMPTY_MOD) for k in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')},
                'POSTGUSTO': dict(_EMPTY_MOD)}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(mods)

    def test_wrong_name_apariencia_raises(self):
        mods = {**{k: dict(_EMPTY_MOD) for k in ('OLOR', 'TEXTURA', 'SABOR')},
                'APARIENCIA': dict(_EMPTY_MOD)}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(mods)

    def test_lowercase_names_raise(self):
        mods = {k.lower(): dict(_EMPTY_MOD) for k in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(mods)


# ── Rejection tests — modality internal structure ─────────────────────────────

class TestModalityInternalStructure:
    def _with_aspecto(self, aspecto_value) -> dict:
        mods = {k: dict(_EMPTY_MOD) for k in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}
        mods['ASPECTO'] = aspecto_value
        return mods

    def test_modality_as_list_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto([]))

    def test_modality_as_null_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto(None))

    def test_missing_mention_text_raises(self):
        bad = {k: v for k, v in _EMPTY_MOD.items() if k != 'mention_text'}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto(bad))

    def test_missing_descriptor_text_raises(self):
        bad = {k: v for k, v in _EMPTY_MOD.items() if k != 'descriptor_text'}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto(bad))

    def test_missing_valuation_text_raises(self):
        bad = {k: v for k, v in _EMPTY_MOD.items() if k != 'valuation_text'}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto(bad))

    def test_missing_is_complete_raises(self):
        bad = {k: v for k, v in _EMPTY_MOD.items() if k != 'is_complete'}
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto(bad))

    def test_is_complete_as_string_false_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'is_complete': 'false'}))

    def test_is_complete_as_string_true_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'is_complete': 'true'}))

    def test_is_complete_as_zero_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'is_complete': 0}))

    def test_is_complete_as_one_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'is_complete': 1}))

    def test_is_complete_as_null_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'is_complete': None}))

    def test_mention_text_as_null_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'mention_text': None}))

    def test_descriptor_text_as_integer_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'descriptor_text': 42}))

    def test_extra_field_in_modality_raises(self):
        with pytest.raises(AnalyzerUnavailableError):
            _parse(self._with_aspecto({**_EMPTY_MOD, 'confidence': 0.9}))


# ── Whitespace stripping preserved ────────────────────────────────────────────

class TestWhitespaceStripping:
    def test_text_fields_are_stripped(self):
        mods = {k: dict(_EMPTY_MOD) for k in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}
        mods['ASPECTO'] = {
            'mention_text': '  Tiene color dorado  ',
            'descriptor_text': '  color dorado  ',
            'valuation_text': '  me gusta  ',
            'is_complete': True,
        }
        result = _parse(mods)
        assert result.modalities['ASPECTO'].mention_text == 'Tiene color dorado'
        assert result.modalities['ASPECTO'].descriptor_text == 'color dorado'
        assert result.modalities['ASPECTO'].valuation_text == 'me gusta'
