from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import AnalysisScope


class ModalityResult(BaseModel):
    mention_text: str = ''
    descriptor_text: str = ''
    valuation_text: str = ''
    is_complete: bool = False


class AnalysisResult(BaseModel):
    analysis_scope: str = AnalysisScope.INTERMEDIATE.value
    is_vague: bool = False
    has_comparison: bool = False
    reasoning_summary: str = ''
    modalities: dict[str, ModalityResult] = Field(default_factory=dict)


class AnalyzerUnavailableError(RuntimeError):
    pass
