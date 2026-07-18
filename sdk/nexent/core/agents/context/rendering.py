"""Rendering boundary for selected fine-grained context items."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .formatting import (
    _format_agent_fallback,
    _format_external_agents_description,
    _format_managed_agents_description,
    _format_memory_context,
    _format_skills_description,
    _format_skills_usage_requirements,
    _format_tools_description,
)
from .models import ContextItem, ContextItemType


class ContextItemRenderingError(RuntimeError):
    """Raised when a selected item cannot be rendered safely."""


ItemHandler = Callable[[ContextItem], list[dict[str, Any]]]


def _text_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _render_text(item: ContextItem, *, default_role: str) -> list[dict[str, Any]]:
    content = item.content
    if isinstance(content, dict) and "template" in content:
        template = content.get("template")
        if template == "skills_usage":
            text = _format_skills_usage_requirements(
                content.get("skills", []),
                language=content.get("language", "zh"),
                is_manager=bool(content.get("is_manager", True)),
            )
        elif template == "agent_fallback":
            text = _format_agent_fallback({}, {}, language=content.get("language", "zh"))
        else:
            raise ContextItemRenderingError(f"unknown system template for item {item.id}: {template}")
        return [_text_message(default_role, text)] if text else []
    if not isinstance(content, dict) or set(content) - {"text", "role"}:
        raise ContextItemRenderingError(f"invalid {item.type.value} payload for item {item.id}")
    text = content.get("text")
    if not isinstance(text, str):
        raise ContextItemRenderingError(f"missing text for item {item.id}")
    if not text:
        return []
    role = content.get("role", default_role)
    if role not in {"system", "developer", "user", "assistant", "tool"}:
        raise ContextItemRenderingError(f"invalid role for item {item.id}: {role}")
    return [_text_message(role, text)]


class ContextItemRenderer:
    """Registry-backed renderer that consumes only the selected item values."""

    def __init__(self, handlers: dict[ContextItemType, ItemHandler] | None = None):
        self._handlers = {
            ContextItemType.SYSTEM_PROMPT: lambda item: _render_text(item, default_role="system"),
            ContextItemType.KNOWLEDGE_BASE: lambda item: _render_text(item, default_role="user"),
            ContextItemType.HISTORY: lambda item: _render_text(item, default_role="user"),
        }
        self._handlers.update(handlers or {})

    def register(self, item_type: ContextItemType, handler: ItemHandler) -> None:
        self._handlers[item_type] = handler

    def render(self, items: Iterable[ContextItem]) -> list[dict[str, Any]]:
        selected = list(items)
        messages: list[dict[str, Any]] = []
        rendered_groups: set[str] = set()
        for item in selected:
            group = item.metadata.get("render_group")
            if group:
                if not isinstance(group, str):
                    raise ContextItemRenderingError(f"invalid render group for item {item.id}")
                if group in rendered_groups:
                    continue
                grouped_items = [candidate for candidate in selected if candidate.metadata.get("render_group") == group]
                messages.extend(self._render_group(grouped_items))
                rendered_groups.add(group)
                continue
            handler = self._handlers.get(item.type)
            if handler is None:
                raise ContextItemRenderingError(f"no handler for context item type: {item.type.value}")
            try:
                messages.extend(handler(item))
            except ContextItemRenderingError:
                raise
            except Exception as exc:
                raise ContextItemRenderingError(f"handler failed for item {item.id}") from exc
        return messages

    @staticmethod
    def _render_group(items: list[ContextItem]) -> list[dict[str, Any]]:
        first = items[0]
        if any(item.type != first.type for item in items[1:]):
            raise ContextItemRenderingError(
                f"render group {first.metadata['render_group']} mixes context item types"
            )
        language = first.metadata.get("language", "zh")
        is_manager = bool(first.metadata.get("is_manager", True))
        if any(
            item.metadata.get("language", "zh") != language
            or bool(item.metadata.get("is_manager", True)) != is_manager
            for item in items[1:]
        ):
            raise ContextItemRenderingError(
                f"render group {first.metadata['render_group']} has inconsistent rendering metadata"
            )
        contents = [item.content for item in items]
        try:
            if first.type == ContextItemType.TOOL:
                data = {str(item["name"]): item for item in contents}
                text = _format_tools_description(data, language=language, is_manager=is_manager)
            elif first.type == ContextItemType.SKILL:
                text = _format_skills_description(contents, language=language)
            elif first.type == ContextItemType.MEMORY:
                text = _format_memory_context(contents, language=language)
            elif first.type == ContextItemType.MANAGED_AGENT:
                data = {str(item["name"]): item for item in contents}
                text = _format_managed_agents_description(data, language=language)
            elif first.type == ContextItemType.EXTERNAL_AGENT:
                data = {str(item["agent_id"]): item for item in contents}
                text = _format_external_agents_description(data, language=language)
            else:
                raise ContextItemRenderingError(f"unsupported render group type: {first.type.value}")
        except ContextItemRenderingError:
            raise
        except Exception as exc:
            raise ContextItemRenderingError(f"handler failed for item group {first.metadata['render_group']}") from exc
        role = "user" if first.type == ContextItemType.MEMORY else "system"
        return [_text_message(role, text)] if text else []
