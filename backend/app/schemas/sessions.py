from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreateRequest(BaseModel):
    participant_code: str = Field(min_length=1, max_length=64)
    tasting_session_id: str = Field(min_length=1, max_length=64)

    @field_validator('participant_code')
    @classmethod
    def normalize_participant_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('participant_code cannot be blank')
        return normalized


class SurveyPayload(BaseModel):
    model_config = ConfigDict(extra='ignore')

    comentario_final: str = Field(default='', max_length=2000)


class SurveyRequest(BaseModel):
    payload: SurveyPayload
