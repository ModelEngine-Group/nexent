"""Type definitions for A2UI protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class A2UIResponsePart:
    """A parsed part of an A2UI response - either text or structured A2UI messages."""
    kind: Literal["text", "a2ui"]
    text: str = ""
    messages: list[dict[str, Any]] | None = None
    protocol_version: str = "0.9"


@dataclass(frozen=True)
class A2UIValidationResult:
    """Result of validating an A2UI response."""
    valid: bool
    error: str | None = None


@dataclass
class A2UIExample:
    """An example A2UI response for few-shot prompting."""
    title: str
    description: str
    messages: list[dict[str, Any]]


@dataclass
class A2UIConfig:
    """Configuration for A2UI feature."""
    enabled: bool = True
    protocol_version: str = "0.9"
    stream_validation_enabled: bool = True