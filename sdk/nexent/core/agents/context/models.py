"""Immutable, fine-grained context items used by the managed runtime."""

from __future__ import annotations

import json
from copy import deepcopy
from enum import Enum, IntEnum
from threading import Lock
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


class ContextItemType(str, Enum):
    SYSTEM = "system"
    TOOL = "tool"
    SKILL = "skill"
    MEMORY = "memory"
    KNOWLEDGE_BASE = "knowledge_base"
    MANAGED_AGENT = "managed_agent"
    EXTERNAL_AGENT = "external_agent"
    HISTORY_SUMMARY = "history_summary"
    CONVERSATION_TURN = "conversation_turn"
    CURRENT_TASK = "current_task"
    CURRENT_PLANNING = "current_planning"
    CURRENT_ACTION = "current_action"


class ContextSection(IntEnum):
    """Class-defined order keeps the stable prefix and run layout predictable."""

    SYSTEM = 0
    TOOL = 10
    SKILL = 20
    MANAGED_AGENT = 30
    EXTERNAL_AGENT = 40
    MEMORY = 50
    KNOWLEDGE_BASE = 60
    HISTORY_SUMMARY = 70
    CONVERSATION_TURN = 80
    CURRENT_TASK = 90
    CURRENT_PLANNING = 100
    CURRENT_ACTION = 110


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
            ContextItemType.MANAGED_AGENT: ("name",),
            ContextItemType.EXTERNAL_AGENT: ("agent_id", "name"),
            ContextItemType.HISTORY_SUMMARY: ("summary", "covered_through_message_id"),
            ContextItemType.CONVERSATION_TURN: (
                "user_message", "assistant_final_answer",
                "user_message_id", "assistant_message_id",
            ),
        }.get(self.type, ())
        missing = [name for name in required_fields if self.content.get(name) is None]
        if missing:
            raise ValueError(f"{self.type.value} content missing fields: {', '.join(missing)}")
        if self.type == ContextItemType.MEMORY and not any(
            self.content.get(name) for name in ("memory", "content", "text")
        ):
            raise ValueError("memory content requires memory, content or text")
        if self.type in {
            ContextItemType.SYSTEM, ContextItemType.KNOWLEDGE_BASE,
            ContextItemType.CURRENT_TASK, ContextItemType.CURRENT_PLANNING,
        } and "template" not in self.content and not isinstance(self.content.get("text"), str):
            raise ValueError(f"{self.type.value} content requires text")
        return self


class ContextItem(BaseModel):
    """Run-local immutable view with one optional deterministic compact form."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ITEM_TYPE: ClassVar[ContextItemType | None] = None
    SECTION: ClassVar[ContextSection]
    REQUIRED: ClassVar[bool] = False
    SUPPORTS_COMPACT: ClassVar[bool] = False

    id: str
    type: ContextItemType
    content: dict[str, Any]
    source: tuple[str, ...] = ()
    priority: int = 10
    metadata: dict[str, Any] = Field(default_factory=dict)
    token_estimate: int = Field(default=0, ge=0)

    _compact_result: "ContextItem | None" = PrivateAttr(default=None)
    _compact_lock: Lock = PrivateAttr(default_factory=Lock)
    _compact_cache_hits: int = PrivateAttr(default=0)
    _compact_cache_misses: int = PrivateAttr(default=0)

    @model_validator(mode="after")
    def _validate_concrete_type(self) -> "ContextItem":
        if self.ITEM_TYPE is not None and self.type != self.ITEM_TYPE:
            raise ValueError(
                f"{self.__class__.__name__} requires type {self.ITEM_TYPE.value}"
            )
        return self

    @classmethod
    def from_input(cls, value: ContextItemInput) -> "ContextItem":
        data = deepcopy(value.model_dump())
        data["token_estimate"] = _estimate(data["content"])
        item_class = _ITEM_CLASSES[value.type]
        return item_class(**data)

    @property
    def layout_key(self) -> tuple[int, int, int, str]:
        order = self.metadata.get("layout_order", 0)
        return int(self.SECTION), int(order), -self.priority, self.id

    @property
    def supports_compact(self) -> bool:
        return self.SUPPORTS_COMPACT

    @property
    def required(self) -> bool:
        """Requiredness is defined once by the concrete Item type."""
        return self.REQUIRED

    @property
    def supported_representations(self) -> tuple[str, ...]:
        return ("raw", "compact") if self.supports_compact else ("raw",)

    def compact(self) -> "ContextItem":
        """Return the single class-defined compact form, cached after success."""
        if not self.supports_compact:
            raise ValueError(f"{self.type.value} does not support compact")
        with self._compact_lock:
            if self._compact_result is not None:
                self._compact_cache_hits += 1
                return self._compact_result
            result = self._build_compact_result()
            self._compact_result = result
            self._compact_cache_misses += 1
            return result

    def represent(self, representation: str = "raw") -> "ContextItem":
        """Small rendering adapter; deletion and dynamic compact budgets do not exist."""
        if representation == "raw":
            return self
        if representation == "compact":
            return self.compact()
        raise ValueError(f"unsupported representation: {representation}")

    @property
    def representation_cache_stats(self) -> tuple[int, int]:
        return self._compact_cache_hits, self._compact_cache_misses

    def _build_compact_result(self) -> "ContextItem":
        compacted = self._build_compact_content(deepcopy(self.content))
        data = self.model_dump(exclude={"content", "token_estimate", "metadata"})
        data["metadata"] = {**deepcopy(self.metadata), "representation": "compact"}
        return self.__class__(**data, content=compacted, token_estimate=_estimate(compacted))

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.type.value} does not define compact")


class SystemContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.SYSTEM
    SECTION = ContextSection.SYSTEM
    REQUIRED = True


class ToolContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.TOOL
    SECTION = ContextSection.TOOL
    REQUIRED = True
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_tool(content)


class SkillContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.SKILL
    SECTION = ContextSection.SKILL
    REQUIRED = True
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_skill(content)


class ManagedAgentContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.MANAGED_AGENT
    SECTION = ContextSection.MANAGED_AGENT
    REQUIRED = True
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_managed_agent(content)


class ExternalAgentContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.EXTERNAL_AGENT
    SECTION = ContextSection.EXTERNAL_AGENT
    REQUIRED = True
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_external_agent(content)


class MemoryContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.MEMORY
    SECTION = ContextSection.MEMORY
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_memory(content)


class KnowledgeBaseContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.KNOWLEDGE_BASE
    SECTION = ContextSection.KNOWLEDGE_BASE
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_text(content)


class HistorySummaryContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.HISTORY_SUMMARY
    SECTION = ContextSection.HISTORY_SUMMARY
    REQUIRED = True


class ConversationTurnContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.CONVERSATION_TURN
    SECTION = ContextSection.CONVERSATION_TURN
    REQUIRED = True


class CurrentTaskContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.CURRENT_TASK
    SECTION = ContextSection.CURRENT_TASK
    REQUIRED = True


class CurrentPlanningContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.CURRENT_PLANNING
    SECTION = ContextSection.CURRENT_PLANNING
    REQUIRED = True
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_text(content)


class CurrentActionContextItem(ContextItem):
    ITEM_TYPE = ContextItemType.CURRENT_ACTION
    SECTION = ContextSection.CURRENT_ACTION
    REQUIRED = True
    SUPPORTS_COMPACT = True

    def _build_compact_content(self, content: dict[str, Any]) -> dict[str, Any]:
        return _compact_action(content)


_ITEM_CLASSES: dict[ContextItemType, type[ContextItem]] = {
    item_class.ITEM_TYPE: item_class
    for item_class in (
        SystemContextItem,
        ToolContextItem,
        SkillContextItem,
        ManagedAgentContextItem,
        ExternalAgentContextItem,
        MemoryContextItem,
        KnowledgeBaseContextItem,
        HistorySummaryContextItem,
        ConversationTurnContextItem,
        CurrentTaskContextItem,
        CurrentPlanningContextItem,
        CurrentActionContextItem,
    )
}


def normalize_context_inputs(values: list[ContextItemInput]) -> list[ContextItem]:
    items: list[ContextItem] = []
    seen: set[str] = set()
    for value in values:
        item = ContextItem.from_input(value)
        if item.id in seen:
            raise ValueError(f"duplicate context item id: {item.id}")
        if item.required and _is_empty(item.content):
            raise ValueError(f"required context item is empty: {item.id}")
        seen.add(item.id)
        items.append(item)
    return sorted(items, key=lambda item: item.layout_key)


def _estimate(content: dict[str, Any]) -> int:
    return max(1, int(len(json.dumps(content, ensure_ascii=False, default=str)) / 1.5))


def _is_empty(content: dict[str, Any]) -> bool:
    return not content or ("text" in content and content["text"] == "")


def _limit_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    half = max(0, (limit - 45) // 2)
    return f"{text[:half]}\n...[deterministically compacted]...\n{text[-half:]}"


def _compact_text(content: dict[str, Any]) -> dict[str, Any]:
    return {**content, "text": _limit_text(content.get("text"))}


def _compact_action(content: dict[str, Any]) -> dict[str, Any]:
    """Keep the action/result boundary and remove verbose reasoning/process fields."""
    allowed = ("step_number", "tool_calls", "observations", "error", "result")
    result = {name: deepcopy(content[name]) for name in allowed if content.get(name) is not None}
    if "observations" in result:
        result["observations"] = _limit_text(result["observations"])
    if "result" in result:
        result["result"] = _limit_text(result["result"])
    return result


def _compact_tool(content: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(content[name]) for name in ("name", "description", "inputs", "output_type") if name in content}


def _compact_skill(content: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(content[name]) for name in ("name", "trigger", "constraints", "description") if name in content}


def _compact_memory(content: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(content[name]) for name in ("memory", "content", "text", "memory_level", "source") if name in content}


def _compact_managed_agent(content: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(content[name]) for name in ("name", "description", "tools", "requirements") if name in content}


def _compact_external_agent(content: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(content[name]) for name in ("agent_id", "name", "description", "url", "protocol", "requirements") if name in content}
