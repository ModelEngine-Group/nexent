"""Stable context input DTO and normalized SDK context item."""

from __future__ import annotations

import json
from copy import deepcopy
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContextItemType(str, Enum):
    """Context candidate types supported by the SDK rendering boundary."""

    SYSTEM_PROMPT = "system_prompt"
    TOOL = "tool"
    SKILL = "skill"
    MEMORY = "memory"
    KNOWLEDGE_BASE = "knowledge_base"
    MANAGED_AGENT = "managed_agent"
    EXTERNAL_AGENT = "external_agent"
    HISTORY = "history"


class ContextItemInput(BaseModel):
    """Serializable DTO accepted at the backend-to-SDK boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    type: ContextItemType
    content: Any
    source: tuple[str, ...] = ()
    priority: int = 10
    required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "metadata")
    @classmethod
    def _require_serializable(cls, value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("context input payload must be JSON serializable") from exc
        return value

    @field_validator("metadata")
    @classmethod
    def _reject_source_object_fallback(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "_source_component" in value:
            raise ValueError("_source_component fallback is not permitted")
        return value

    @model_validator(mode="after")
    def _validate_type_payload(self) -> "ContextItemInput":
        if not isinstance(self.content, dict):
            raise ValueError(f"{self.type.value} content must be an object")
        required_fields = {
            ContextItemType.TOOL: ("name",),
            ContextItemType.SKILL: ("name",),
            ContextItemType.MEMORY: (),
            ContextItemType.MANAGED_AGENT: ("name",),
            ContextItemType.EXTERNAL_AGENT: ("agent_id", "name"),
        }.get(self.type)
        if required_fields is not None:
            missing = [field for field in required_fields if not self.content.get(field)]
            if missing:
                raise ValueError(f"{self.type.value} content missing fields: {', '.join(missing)}")
            if self.type == ContextItemType.MEMORY and not any(
                self.content.get(field) for field in ("memory", "content")
            ):
                raise ValueError("memory content requires memory or content")
        elif self.type in {
            ContextItemType.SYSTEM_PROMPT,
            ContextItemType.KNOWLEDGE_BASE,
            ContextItemType.HISTORY,
        }:
            if self.type == ContextItemType.SYSTEM_PROMPT and "template" in self.content:
                if self.content["template"] not in {"skills_usage", "agent_fallback"}:
                    raise ValueError(f"unknown system template: {self.content['template']}")
            elif not isinstance(self.content.get("text"), str):
                raise ValueError(f"{self.type.value} content requires text")
        if self.type == ContextItemType.HISTORY and self.content.get("role") not in {"user", "assistant"}:
            raise ValueError("history content requires user or assistant role")
        return self


class ContextItem(BaseModel):
    """Normalized immutable candidate consumed by SDK context services."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    type: ContextItemType
    content: Any
    source: tuple[str, ...] = ()
    priority: int = 10
    required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_estimate: int = Field(default=0, ge=0)

    @classmethod
    def from_input(cls, value: ContextItemInput) -> "ContextItem":
        """Normalize a public DTO without retaining a source-object fallback."""
        estimated = max(1, int(len(json.dumps(value.content, ensure_ascii=False)) / 1.5))
        return cls(**deepcopy(value.model_dump()), token_estimate=estimated)


def normalize_context_inputs(values: list[ContextItemInput]) -> list[ContextItem]:
    """Validate run-local identity and normalize inputs into SDK items."""
    items: list[ContextItem] = []
    seen: set[str] = set()
    for value in values:
        item = ContextItem.from_input(value)
        if item.id in seen:
            raise ValueError(f"duplicate context item id: {item.id}")
        if item.required and _is_empty_content(item.content):
            raise ValueError(f"required context item is empty: {item.id}")
        seen.add(item.id)
        items.append(item)
    return items


def _is_empty_content(content: Any) -> bool:
    if content is None or content == "":
        return True
    if isinstance(content, dict) and "text" in content:
        return content.get("text") == ""
    return False
