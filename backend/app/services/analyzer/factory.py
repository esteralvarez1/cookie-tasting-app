from __future__ import annotations

from app.core.config import settings
from app.services.analyzer.base import BaseAnalyzer
from app.services.analyzer.fallback import FallbackAnalyzer
from app.services.analyzer.openai_compatible import OpenAICompatibleAnalyzer
from app.services.analyzer.rules import RuleBasedAnalyzer


_OPENAI_COMPATIBLE_PROVIDERS = {'groq', 'openai', 'openai-compatible', 'ollama'}


def get_analyzer() -> BaseAnalyzer:
    if settings.llm_provider.lower() in _OPENAI_COMPATIBLE_PROVIDERS and settings.llm_api_key:
        primary = OpenAICompatibleAnalyzer()
        if settings.llm_fallback_to_rules:
            return FallbackAnalyzer(primary, RuleBasedAnalyzer())
        return primary
    return RuleBasedAnalyzer()
