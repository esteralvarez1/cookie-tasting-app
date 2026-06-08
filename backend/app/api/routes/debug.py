from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import require_admin
from app.services.analyzer.factory import get_analyzer
from app.services.analyzer.models import AnalyzerUnavailableError
from app.services.analyzer.openai_compatible import OpenAICompatibleAnalyzer

router = APIRouter(prefix='/debug', tags=['debug'])

_PROBE_TEXT = (
    'La galleta es redonda y dorada. Huele a vainilla. '
    'La textura es crujiente y me gusta. Sabe dulce y está buena.'
)

_OPENAI_COMPATIBLE_PROVIDERS = {'groq', 'openai', 'openai-compatible', 'ollama'}


@router.get('/llm', dependencies=[Depends(require_admin)])
def debug_llm() -> dict:
    analyzer = get_analyzer()
    return {
        'success': True,
        'data': {
            'provider': analyzer.provider_name,
            'model': analyzer.model_name,
            'prompt_version': analyzer.prompt_version,
            'fallback_enabled': settings.llm_fallback_to_rules,
        },
        'message': 'Configuración LLM efectiva',
    }


@router.post('/llm/probe', dependencies=[Depends(require_admin)])
async def debug_llm_probe() -> dict:
    fallback_enabled = settings.llm_fallback_to_rules
    configured = (
        settings.llm_provider.lower() in _OPENAI_COMPATIBLE_PROVIDERS
        and bool(settings.llm_api_key)
    )

    # No LLM configured at all — rules-only mode.
    if not configured:
        return {
            'success': True,
            'data': {
                'provider': 'rules',
                'model': 'local-rules',
                'fallback_enabled': fallback_enabled,
                'llm_status': 'not_configured',
                'used_fallback': False,
                'effective_analyzer': 'rules',
                'latency_ms': None,
                'analysis': None,
            },
            'message': 'No hay LLM configurado. El analizador activo es rules.',
        }

    # LLM is configured — probe the primary directly, bypassing FallbackAnalyzer,
    # so that a silent fallback cannot produce a false positive.
    primary = OpenAICompatibleAnalyzer()
    t0 = time.perf_counter()
    try:
        result = await primary.analyze(
            analysis_scope='INITIAL',
            current_state='INITIAL_QUESTION',
            current_modality=None,
            user_last_message=_PROBE_TEXT,
            accumulated_text=_PROBE_TEXT,
            covered_modalities=[],
            vague_retry_count=0,
            comparison_retry_count=0,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000)
        return {
            'success': True,
            'data': {
                'provider': primary.provider_name,
                'model': primary.model_name,
                'fallback_enabled': fallback_enabled,
                'llm_status': 'ok',
                'used_fallback': False,
                'effective_analyzer': 'llm',
                'latency_ms': latency_ms,
                'analysis': result.model_dump(),
            },
            'message': 'LLM responde correctamente',
        }
    except AnalyzerUnavailableError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000)
        # In production, if the LLM fails and fallback is on, the app would silently
        # switch to rules. We surface that here so it is never invisible.
        return {
            'success': False,
            'data': {
                'provider': primary.provider_name,
                'model': primary.model_name,
                'fallback_enabled': fallback_enabled,
                'llm_status': 'error',
                'used_fallback': fallback_enabled,
                'effective_analyzer': 'rules' if fallback_enabled else 'none',
                'latency_ms': latency_ms,
                'analysis': None,
                'error': str(exc),
            },
            'message': (
                'El LLM no está disponible. La aplicación usaría reglas locales como fallback.'
                if fallback_enabled
                else 'El LLM no está disponible y no hay fallback activado.'
            ),
        }
