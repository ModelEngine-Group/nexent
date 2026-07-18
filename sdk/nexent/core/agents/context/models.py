"""Stable context input DTO and normalized SDK context item."""

from __future__ import annotations

import json
from copy import deepcopy
from enum import Enum, IntEnum
from hashlib import sha256
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


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


class ContextSection(IntEnum):
    """Stable prompt regions; values define the KV-cache-friendly order."""

    STABLE_SYSTEM = 0
    DYNAMIC_EVIDENCE = 1
    HISTORY = 2


_TYPE_FALLBACK_RELEVANCE: dict[ContextItemType, float] = {
    ContextItemType.MEMORY: 0.70,
    ContextItemType.KNOWLEDGE_BASE: 0.65,
    ContextItemType.HISTORY: 0.60,
    ContextItemType.SKILL: 0.50,
    ContextItemType.MANAGED_AGENT: 0.45,
    ContextItemType.EXTERNAL_AGENT: 0.45,
    ContextItemType.TOOL: 0.40,
    ContextItemType.SYSTEM_PROMPT: 0.35,
}


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

    _representation_cache: dict[tuple[str, str], "ContextItem | None"] = PrivateAttr(default_factory=dict)
    _representation_lock: Lock = PrivateAttr(default_factory=Lock)
    _representation_cache_hits: int = PrivateAttr(default=0)
    _representation_cache_misses: int = PrivateAttr(default=0)

    @classmethod
    def from_input(cls, value: ContextItemInput) -> "ContextItem":
        """Normalize a public DTO without retaining a source-object fallback."""
        estimated = max(1, int(len(json.dumps(value.content, ensure_ascii=False)) / 1.5))
        return cls(**deepcopy(value.model_dump()), token_estimate=estimated)

    @property
    def content_fingerprint(self) -> str:
        """Stable identity for cached representations of this immutable item."""

        encoded = json.dumps(self.content, ensure_ascii=False, sort_keys=True, default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def layout_key(self) -> tuple[int, int, str]:
        """Return the class-defined stable prompt position for this item."""

        if self.type == ContextItemType.HISTORY:
            section = ContextSection.HISTORY
        elif self.type in {ContextItemType.MEMORY, ContextItemType.KNOWLEDGE_BASE}:
            section = ContextSection.DYNAMIC_EVIDENCE
        else:
            section = ContextSection.STABLE_SYSTEM
        return int(section), -self.priority, self.id

    def score(self) -> float:
        """Return the deterministic no-embedding relevance fallback."""

        if self.required:
            raise ValueError(f"required context item must not be scored: {self.id}")
        return _TYPE_FALLBACK_RELEVANCE[self.type]

    @property
    def supported_representations(self) -> tuple[str, ...]:
        """Representations explicitly supported by this item class."""

        if self.required or self.type not in {
            ContextItemType.MEMORY,
            ContextItemType.KNOWLEDGE_BASE,
            ContextItemType.HISTORY,
        }:
            return ("raw",)
        return ("raw", "compact", "drop")

    def represent(
        self,
        representation: str = "raw",
        *,
        config_fingerprint: str = "",
        max_tokens: int | None = None,
    ) -> "ContextItem | None":
        """Lazily compute and cache a class-defined representation."""

        if representation not in self.supported_representations:
            raise ValueError(
                f"unsupported representation for {self.type.value}: {representation}"
            )
        cache_key = (
            representation,
            f"{self.content_fingerprint}:{config_fingerprint}:{max_tokens}",
        )
        with self._representation_lock:
            if cache_key in self._representation_cache:
                self._representation_cache_hits += 1
            else:
                self._representation_cache_misses += 1
                self._representation_cache[cache_key] = self._build_representation(
                    representation,
                    max_tokens=max_tokens,
                )
            return self._representation_cache[cache_key]

    @property
    def representation_cache_stats(self) -> tuple[int, int]:
        """Return (hits, misses) for loop-level evidence aggregation."""

        return self._representation_cache_hits, self._representation_cache_misses

    def _build_representation(
        self,
        representation: str,
        *,
        max_tokens: int | None,
    ) -> "ContextItem | None":
        """Build a type-owned representation without a global tier policy."""

        if representation == "raw":
            return self
        if representation == "drop" and not self.required:
            return None
        if representation == "compact" and not self.required:
            content = deepcopy(self.content)
            if self.type == ContextItemType.MEMORY:
                allowed = {"memory", "content", "memory_level", "score"}
                content = {key: value for key, value in content.items() if key in allowed}
                text_key = "memory" if "memory" in content else "content"
            else:
                text_key = "text"
            text = str(content.get(text_key, ""))
            if max_tokens is not None:
                empty_content = {**content, text_key: ""}
                overhead = len(json.dumps(empty_content, ensure_ascii=False))
                char_limit = max(0, int(max_tokens * 1.5) - overhead)
                if len(text) > char_limit:
                    marker = "\n...[context item compacted]"
                    if char_limit <= len(marker):
                        text = marker[:char_limit]
                    else:
                        text = text[: char_limit - len(marker)] + marker
            content = {**content, text_key: text}
            estimated = max(1, int(len(json.dumps(content, ensure_ascii=False)) / 1.5))
            data = self.model_dump(exclude={"content", "token_estimate"})
            return ContextItem(**data, content=content, token_estimate=estimated)
        raise ValueError(f"unsupported representation: {representation}")


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
