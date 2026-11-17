# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Core-independent authorized context inputs, messages and evidence."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Tuple

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class ContextItemType(str, Enum):
    SYSTEM = "system"
    TOOL = "tool"
    SKILL = "skill"
    MEMORY = "memory"
    KNOWLEDGE_BASE = "knowledge_base"
    WORKER_AGENT = "worker_agent"
    EXTERNAL_AGENT = "external_agent"
    HISTORY_SUMMARY = "history_summary"
    CONVERSATION_TURN = "conversation_turn"
    CURRENT_TASK = "current_task"
    CURRENT_PLANNING = "current_planning"
    CURRENT_ACTION = "current_action"


class ContextItemInput(BaseModel):
    """Serializable backend-to-SDK DTO; it never carries database objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    type: ContextItemType
    content: dict[str, Any]
    source: tuple[str, ...] = ()
    priority: int = 10
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
    def _reject_source_objects(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "_source_component" in value:
            raise ValueError("_source_component fallback is not permitted")
        return value

    @model_validator(mode="after")
    def _validate_payload(self) -> "ContextItemInput":
        required_fields = {
            ContextItemType.TOOL: ("name",),
            ContextItemType.SKILL: ("name",),
            ContextItemType.WORKER_AGENT: ("name",),
            ContextItemType.EXTERNAL_AGENT: ("agent_id", "name"),
            ContextItemType.HISTORY_SUMMARY: ("summary", "covered_through_message_id"),
            ContextItemType.CONVERSATION_TURN: (
                "user_message",
                "assistant_final_answer",
                "user_message_id",
                "assistant_message_id",
            ),
        }.get(self.type, ())
        missing = [name for name in required_fields if self.content.get(name) is None]
        if missing:
            raise ValueError(f"{self.type.value} content missing fields: {', '.join(missing)}")
        if self.type == ContextItemType.MEMORY and not any(
            self.content.get(name) for name in ("memory", "content", "text")
        ):
            raise ValueError("memory content requires memory, content or text")
        if (
            self.type
            in {
                ContextItemType.SYSTEM,
                ContextItemType.KNOWLEDGE_BASE,
                ContextItemType.CURRENT_TASK,
                ContextItemType.CURRENT_PLANNING,
            }
            and "template" not in self.content
            and not isinstance(self.content.get("text"), str)
        ):
            raise ValueError(f"{self.type.value} content requires text")
        return self


@dataclass(frozen=True)
class ContextInput:
    """Immutable context snapshot supplied by the application boundary.

    The SDK consumes this snapshot without loading business data or inferring
    user and tenant permissions. Every item is fully materialized and
    authorized by the application before crossing this boundary.
    """

    items: Tuple[ContextItemInput, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("ContextInput collections must be immutable tuples")
        frozen_items = tuple(ContextItemInput.model_validate(deepcopy(item.model_dump())) for item in self.items)
        object.__setattr__(self, "items", frozen_items)


@dataclass(frozen=True)
class ContextMessage:
    """Neutral message for auxiliary CM model calls; no native message instance."""

    role: str
    content: str | list[dict[str, JsonValue]]
    fingerprint_payload: dict[str, JsonValue] | None = None

    def model_dump(self):
        """Retain the bridge's existing audit representation without native objects."""
        if self.fingerprint_payload is not None:
            return deepcopy(self.fingerprint_payload)
        return {"role": self.role, "content": deepcopy(self.content)}


@dataclass(frozen=True)
class ContextToolView:
    """Detached tool audit data with the pre-existing token-estimation text."""

    fingerprint_payload: dict[str, JsonValue]
    budget_text: str

    def model_dump(self):
        return deepcopy(self.fingerprint_payload)

    def __str__(self):
        return self.budget_text


ModelMessage = ContextMessage | dict[str, object]
ModelTool = ContextToolView | dict[str, object]


class ContextSummaryResponse(Protocol):
    """Summary response fields consumed by common context algorithms."""

    content: str | list[dict[str, JsonValue]]


class ContextSummaryModel(Protocol):
    """Core supplies native conversion and the configured model invocation."""

    def __call__(
        self, messages: list[ModelMessage], *, stop_sequences: list[str], **parameters: object
    ) -> ContextSummaryResponse:
        """Invoke the already selected model without selecting a Core or outlet."""


@dataclass(frozen=True)
class ContextEvidence:
    purpose: str = "step"
    selected_item_ids: tuple[str, ...] = ()
    selected_item_types: tuple[str, ...] = ()
    stable_message_count: int = 0
    dynamic_message_count: int = 0
    compression_records: tuple[object, ...] = ()
    stable_prefix_fingerprint: str | None = None
    prefix_change_reasons: tuple[str, ...] = ()
    policy_fingerprint: str | None = None
    processing_mode: str = "passthrough"
    effective_input_limit_tokens: int = 0
    compaction_trigger_threshold_tokens: int = 0
    compaction_target_tokens: int = 0
    compaction_attempts: int = 0
    compressible_history_tokens: int = 0
    non_history_tokens: int = 0
    compaction_stop_reason: str = "not_triggered"
    raw_token_estimate: int = 0
    final_token_estimate: int = 0
    loaded_summary_unit_id: int | None = None
    loaded_summary_coverage: int | None = None
    new_history_turn_count: int = 0
    history_compression_triggered: bool = False
    new_summary_coverage: int | None = None
    summary_persist_status: str = "not_attempted"
    item_representations: tuple[tuple[str, str], ...] = ()
    current_action_compact_count: int = 0
    representation_cache_hits: int = 0
    representation_cache_misses: int = 0
    compaction_attempts_exhausted: bool = False
    exceeds_effective_input_limit: bool = False
    model_call_count: int = 0
    loop_status: str | None = None
    messages_fingerprint: str | None = None
    tools_fingerprint: str | None = None
    system_messages_fingerprint: str | None = None
    history_messages_fingerprint: str | None = None
    final_answer_prompt_fingerprint: str | None = None
    message_roles: tuple[str, ...] = ()
    history_message_roles: tuple[str, ...] = ()
    compression_attempted: bool = False
    fallback_compaction_used: bool = False


@dataclass(frozen=True)
class FinalContext:
    """The only context payload permitted to enter a model call."""

    messages: list[ModelMessage]
    tools: list[dict[str, object]] = field(default_factory=list)
    evidence: ContextEvidence = field(default_factory=ContextEvidence)
    memory_messages: list[ModelMessage] | None = None
