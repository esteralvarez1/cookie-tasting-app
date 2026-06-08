from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class EvaluationCreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    sample_code: str = Field(min_length=1, max_length=64)

    @field_validator('sample_code')
    @classmethod
    def normalize_sample_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('sample_code cannot be blank')
        return normalized


class DialogueRequest(BaseModel):
    user_message: str = Field(min_length=1, max_length=2000)

    @field_validator('user_message')
    @classmethod
    def normalize_user_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('user_message cannot be blank')
        return normalized


class FinalizeRequest(BaseModel):
    reason: str = Field(default='MANUAL', max_length=64)

    @field_validator('reason')
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        return normalized or 'MANUAL'


class SampleCommentRequest(BaseModel):
    comment: str = Field(default='', max_length=2000)

    @field_validator('comment')
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()
