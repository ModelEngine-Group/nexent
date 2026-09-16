"""Strict public commands and secret-safe interaction projections."""

import hashlib
import json
import re
from typing import Literal

from nexent.core.human_interaction.clarification import ClarificationAnswer
from pydantic import BaseModel, ConfigDict, Field


class InteractionError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    digest: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=100)
    decision: Literal["answer", "approve", "reject", "steer"]
    text: str | None = Field(default=None, max_length=8000)
    answers: list[ClarificationAnswer] | None = Field(default=None, min_length=1, max_length=5)


class SteeringCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field(min_length=1, max_length=8000)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


_SECRET = re.compile(r"password|passwd|secret|token|credential|authorization|api.?key|cookie", re.I)


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED_SECRET]" if _SECRET.search(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
