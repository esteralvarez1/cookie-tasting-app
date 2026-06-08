from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    data: Any
    message: str


class ApiError(BaseModel):
    success: bool = False
    error: dict[str, Any]
