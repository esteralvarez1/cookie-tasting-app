from __future__ import annotations

import logging

from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.models import AnalysisResult, AnalyzerUnavailableError

logger = logging.getLogger(__name__)


class FallbackAnalyzer(BaseAnalyzer):
    """Wraps a primary analyzer with automatic fallback to a secondary analyzer.

    If the primary raises AnalyzerUnavailableError the fallback is used
    transparently so the participant can always continue the tasting session.

    provider_name/model_name/prompt_version reflect the primary analyzer so
    that DB records show the intended provider.  When the fallback is used, the
    warning log captures the actual execution path.
    """

    def __init__(self, primary: BaseAnalyzer, fallback: BaseAnalyzer) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = primary.provider_name
        self.model_name = primary.model_name
        self.prompt_version = primary.prompt_version

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
        _kwargs: dict = dict(
            analysis_scope=analysis_scope,
            current_state=current_state,
            current_modality=current_modality,
            user_last_message=user_last_message,
            accumulated_text=accumulated_text,
            covered_modalities=covered_modalities,
            vague_retry_count=vague_retry_count,
            comparison_retry_count=comparison_retry_count,
            previous_bot_question=previous_bot_question,
            current_sample_code=current_sample_code,
            session_sample_codes=session_sample_codes,
            other_sample_codes=other_sample_codes,
        )
        try:
            return await self._primary.analyze(**_kwargs)
        except AnalyzerUnavailableError:
            logger.warning(
                'Primary LLM analyzer (%s / %s) failed; falling back to RuleBasedAnalyzer.',
                self._primary.provider_name,
                self._primary.model_name,
                exc_info=True,
            )
            return await self._fallback.analyze(**_kwargs)
