from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.analyzer.models import AnalysisResult


class BaseAnalyzer(ABC):
    provider_name: str = 'rules'
    model_name: str = 'local-rules'
    prompt_version: str = 'rules_v1'

    @abstractmethod
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
        raise NotImplementedError
