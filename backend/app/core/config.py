from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

# Values that are never acceptable as API keys outside development.
_INSECURE_KEY_VALUES: frozenset[str] = frozenset({
    'change-me', 'change-me-researcher', 'secret', 'password',
    'changeme', 'admin', 'test', '',
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / '.env', BACKEND_DIR / '.env'),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    app_env: str = 'development'
    log_level: str = 'INFO'
    database_url: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/cookie_tasting'

    llm_provider: str = 'rules'
    llm_base_url: str = 'https://api.groq.com/openai/v1'
    llm_api_key: str | None = None
    llm_model: str = 'llama-3.1-8b-instant'
    llm_timeout_seconds: int = 20
    llm_connect_timeout_seconds: int = 10
    llm_max_retries: int = 2
    # When False, skips response_format:{type:"json_object"} in the request payload.
    # Recommended False for Ollama: its grammar-constrained JSON is 2-4x slower than
    # relying on the system prompt alone, which already enforces strict JSON output.
    llm_response_format_json: bool = True
    # Maximum characters of accumulated_text forwarded to the LLM per turn.
    # Full history is always persisted in the database; this limits only the LLM context window.
    llm_context_max_chars: int = 3000
    # Context mode sent to the LLM in each turn.
    # 'minimal': only current_state, current_modality, other_sample_codes, pregunta_previa_del_bot.
    # 'legacy' : full context (analysis_scope, covered_modalities, retry counters, sample codes).
    # Set LLM_CONTEXT_MODE=legacy in .env to revert temporarily if minimal causes regressions.
    llm_context_mode: str = 'minimal'
    # When True and the primary LLM analyzer fails (timeout, connection error, bad JSON),
    # the backend automatically falls back to RuleBasedAnalyzer so participants can
    # continue the tasting without interruption.  Set to False to disable the fallback
    # and let AnalyzerUnavailableError propagate to the caller.
    # Acepta tanto LLM_FALLBACK_TO_RULES (nombre histórico) como LLM_FALLBACK_ENABLED
    # (usado en la configuración del despliegue Salamandra local). Ambos son equivalentes.
    llm_fallback_to_rules: bool = Field(
        default=True,
        validation_alias=AliasChoices('LLM_FALLBACK_TO_RULES', 'LLM_FALLBACK_ENABLED'),
    )

    # Límite de tokens de salida enviado al proveedor en cada petición.
    # Obligatorio para Ollama/CPU: sin max_tokens la generación es demasiado lenta.
    llm_max_tokens: int = 320
    # Perfil de prompt del sistema: 'default' (Groq/OpenAI) o 'salamandra_compact' (Ollama).
    llm_prompt_profile: str = 'default'
    # Reparación estructural del JSON devuelto por el modelo antes de fallar.
    llm_json_repair_enabled: bool = True

    admin_api_key: str = 'change-me'
    researcher_api_key: str = 'change-me-researcher'
    backend_cors_origins: list[str] | str = ['http://localhost:5173']

    # Session token TTL in hours. After this period the backend rejects the token with 401.
    session_token_ttl_hours: int = 24

    max_vague_retries: int = 1
    max_comparison_retries: int = 2
    max_modality_attempts: int = 2

    # Rate limiting (requests per minute per IP). Applies to the most sensitive endpoints.
    # In-memory only — does not survive restarts; use Redis backend for multi-process deployments.
    rate_limit_sessions_per_minute: int = 10
    rate_limit_dialog_per_minute: int = 30

    @field_validator('backend_cors_origins', mode='before')
    @classmethod
    def parse_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @model_validator(mode='after')
    def reject_insecure_keys_outside_dev(self) -> 'Settings':
        """Fail at startup when default/insecure API keys are used outside development.

        Set APP_ENV=development to bypass this check in local environments.
        """
        if self.app_env == 'development':
            return self
        if self.admin_api_key.lower() in _INSECURE_KEY_VALUES:
            raise ValueError(
                'ADMIN_API_KEY must be changed from its default value in non-development environments. '
                'Set APP_ENV=development to bypass this check locally.'
            )
        if self.researcher_api_key.lower() in _INSECURE_KEY_VALUES:
            raise ValueError(
                'RESEARCHER_API_KEY must be changed from its default value in non-development environments. '
                'Set APP_ENV=development to bypass this check locally.'
            )
        return self

    @property
    def cors_origins(self) -> list[str]:
        if isinstance(self.backend_cors_origins, str):
            return [self.backend_cors_origins]
        return self.backend_cors_origins


settings = Settings()
