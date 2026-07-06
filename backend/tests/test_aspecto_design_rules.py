"""Refuerzo de ASPECTO: 'diseño', 'apariencia', 'forma', 'pinta', etc.

El analizador por reglas (y por tanto el fallback cuando el LLM falla) debe reconocer
expresiones visuales de diseño/apariencia como ASPECTO y no como OLOR/TEXTURA/SABOR.

Pruebas unitarias puras: se llama directamente a analyze() en un escenario de un solo
turno (accumulated_text == mensaje).
"""
from __future__ import annotations

import asyncio

from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.fallback import FallbackAnalyzer
from app.services.analyzer.models import AnalysisResult, AnalyzerUnavailableError
from app.services.analyzer.rules import RuleBasedAnalyzer

_analyzer = RuleBasedAnalyzer()


def _analyze(text: str) -> AnalysisResult:
    return asyncio.run(_analyzer.analyze(
        analysis_scope='INITIAL',
        current_state='INITIAL_QUESTION',
        current_modality=None,
        user_last_message=text,
        accumulated_text=text,
        covered_modalities=[],
        vague_retry_count=0,
        comparison_retry_count=0,
    ))


def _mod(result: AnalysisResult, modality: str):
    return result.modalities[modality]


class TestDesignIsAspecto:
    """'El diseño me parece original' completa ASPECTO y nada más."""

    TEXT = 'El diseño me parece original.'

    def test_aspecto_is_complete(self):
        assert _mod(_analyze(self.TEXT), 'ASPECTO').is_complete is True

    def test_aspecto_descriptor_present(self):
        assert _mod(_analyze(self.TEXT), 'ASPECTO').descriptor_text.strip() != ''

    def test_olor_not_complete(self):
        assert _mod(_analyze(self.TEXT), 'OLOR').is_complete is False

    def test_textura_not_complete(self):
        assert _mod(_analyze(self.TEXT), 'TEXTURA').is_complete is False

    def test_sabor_not_complete(self):
        assert _mod(_analyze(self.TEXT), 'SABOR').is_complete is False


class TestOtherVisualExpressions:
    """Otras expresiones visuales de forma/apariencia se completan como ASPECTO."""

    def test_forma_bonita_is_aspecto(self):
        r = _analyze('La forma es bonita.')
        assert _mod(r, 'ASPECTO').is_complete is True
        assert _mod(r, 'OLOR').is_complete is False
        assert _mod(r, 'TEXTURA').is_complete is False
        assert _mod(r, 'SABOR').is_complete is False

    def test_pinta_casera_is_aspecto(self):
        r = _analyze('Tiene una pinta casera.')
        assert _mod(r, 'ASPECTO').is_complete is True
        assert _mod(r, 'OLOR').is_complete is False
        assert _mod(r, 'TEXTURA').is_complete is False
        assert _mod(r, 'SABOR').is_complete is False


class _FailingAnalyzer(BaseAnalyzer):
    """Primario que siempre falla, para forzar el fallback a reglas."""

    provider_name = 'openai-compatible'
    model_name = 'local-salamandra-2b-instruct'
    prompt_version = 'test'

    async def analyze(self, *args, **kwargs) -> AnalysisResult:  # type: ignore[override]
        raise AnalyzerUnavailableError('simulated LLM failure')


class TestRulesFallbackStillWorks:
    """Si el LLM (Salamandra) falla, el fallback por reglas clasifica ASPECTO."""

    def test_fallback_classifies_design_as_aspecto(self):
        fallback = FallbackAnalyzer(_FailingAnalyzer(), RuleBasedAnalyzer())
        result = asyncio.run(fallback.analyze(
            analysis_scope='INITIAL',
            current_state='INITIAL_QUESTION',
            current_modality=None,
            user_last_message='El diseño me parece original.',
            accumulated_text='El diseño me parece original.',
            covered_modalities=[],
            vague_retry_count=0,
            comparison_retry_count=0,
        ))
        assert result.modalities['ASPECTO'].is_complete is True
        assert result.modalities['SABOR'].is_complete is False
