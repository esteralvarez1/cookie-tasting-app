from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TastingSessionConfigCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    sample_codes: list[str] = Field(min_length=1)
    final_redirect_url: str | None = Field(default=None)

    @field_validator('title')
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator('sample_codes')
    @classmethod
    def normalize_sample_codes(cls, value: list[str]) -> list[str]:
        normalized = [code.strip() for code in value if code.strip()]
        if not normalized:
            raise ValueError('Debe indicarse al menos un código de muestra.')
        if any(len(code) > 64 for code in normalized):
            raise ValueError('Cada código de muestra debe tener como máximo 64 caracteres.')
        if len(set(normalized)) != len(normalized):
            raise ValueError('Los códigos de muestra no pueden estar duplicados.')
        return normalized

    @field_validator('final_redirect_url')
    @classmethod
    def validate_final_redirect_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.startswith(('http://', 'https://')):
            raise ValueError('El enlace final debe ser una URL válida (http:// o https://).')
        return value
