"""Fake analyzers for dialog tests that require controlled LLM output."""
from __future__ import annotations

from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.models import AnalysisResult, ModalityResult


def _empty_modalities() -> dict[str, ModalityResult]:
    return {m: ModalityResult() for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}


def _complete_modalities() -> dict[str, ModalityResult]:
    r = ModalityResult(
        mention_text='mencionado en el texto',
        descriptor_text='descriptor concreto',
        valuation_text='me gusta mucho',
        is_complete=True,
    )
    return {m: r for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')}


class FakeAnalyzer(BaseAnalyzer):
    """Deterministic analyzer for tests.

    Scenarios
    ---------
    VAGUE          - is_vague=True, no modality data
    COMPARISON     - has_comparison=True, no modality data
    ALL_COMPLETE   - all four modalities fully populated and is_complete=True
    ASPECTO_PARTIAL- ASPECTO has mention+descriptor but no valuation
    NORMAL         - no vagueness, no comparison, no modality complete
    """

    provider_name = 'fake'
    model_name = 'fake-v1'
    prompt_version = 'fake_v1'

    VAGUE = 'vague'
    COMPARISON = 'comparison'
    ALL_COMPLETE = 'all_complete'
    ASPECTO_PARTIAL = 'aspecto_partial'
    ASPECTO_COMPLETE = 'aspecto_complete'
    NORMAL = 'normal'
    SABOR_PARTIAL = 'sabor_partial'
    TEXTURA_PARTIAL = 'textura_partial'

    def __init__(self, scenario: str = NORMAL) -> None:
        self.scenario = scenario

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
        if self.scenario == self.VAGUE:
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=True,
                has_comparison=False,
                reasoning_summary='Respuesta vaga',
                modalities=_empty_modalities(),
            )
        if self.scenario == self.COMPARISON:
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=False,
                has_comparison=True,
                reasoning_summary='Comparación detectada',
                modalities=_empty_modalities(),
            )
        if self.scenario == self.ALL_COMPLETE:
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=False,
                has_comparison=False,
                reasoning_summary='Todas las modalidades completas',
                modalities=_complete_modalities(),
            )
        if self.scenario == self.ASPECTO_PARTIAL:
            mods = _empty_modalities()
            mods['ASPECTO'] = ModalityResult(
                mention_text='color dorado',
                descriptor_text='dorado',
                valuation_text='',
                is_complete=False,
            )
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=False,
                has_comparison=False,
                reasoning_summary='ASPECTO parcialmente cubierto',
                modalities=mods,
            )
        if self.scenario == self.ASPECTO_COMPLETE:
            # Only ASPECTO is complete; the other three are empty. Used to verify that a
            # covered modality is preserved across later MODALITY_QUESTION turns.
            mods = _empty_modalities()
            mods['ASPECTO'] = ModalityResult(
                mention_text='es dorada y redonda',
                descriptor_text='dorado, redonda',
                valuation_text='me gusta como se ve',
                is_complete=True,
            )
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=False,
                has_comparison=False,
                reasoning_summary='ASPECTO completo',
                modalities=mods,
            )
        if self.scenario == self.SABOR_PARTIAL:
            # Simulates LLM that extracted mention+descriptor for SABOR but missed the valuation.
            # The deterministic fallback should fill valuation_text from accumulated_text.
            mods = _empty_modalities()
            mods['SABOR'] = ModalityResult(
                mention_text='retrogusto largo con sabor a azucar tostada y jengibre artificial',
                descriptor_text='azucar tostada, jengibre artificial',
                valuation_text='',
                is_complete=False,
            )
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=False,
                has_comparison=False,
                reasoning_summary='SABOR parcialmente cubierto, valoración no detectada',
                modalities=mods,
            )
        if self.scenario == self.TEXTURA_PARTIAL:
            mods = _empty_modalities()
            mods['TEXTURA'] = ModalityResult(
                mention_text='Textura seca y boronosa',
                descriptor_text='seca, boronosa',
                valuation_text='',
                is_complete=False,
            )
            return AnalysisResult(
                analysis_scope=analysis_scope,
                is_vague=False,
                has_comparison=False,
                reasoning_summary='TEXTURA parcialmente cubierta, valoración no detectada',
                modalities=mods,
            )
        # NORMAL
        return AnalysisResult(
            analysis_scope=analysis_scope,
            is_vague=False,
            has_comparison=False,
            reasoning_summary='Respuesta normal sin modalidades completas',
            modalities=_empty_modalities(),
        )
