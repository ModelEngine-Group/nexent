# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rendering boundary for selected fine-grained context items."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from nexent.core.prompts import load_prompt

from .formatting import (
    _format_external_agents_description,
    _format_worker_agents_description,
    _format_skills_inventory,
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
        raise ContextItemRenderingError(
            f"unknown system template for item {item.id}: {content.get('template')}"
        )
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


def _render_summary(item: ContextItem) -> list[dict[str, Any]]:
    labels = load_prompt(item.metadata.get("language", "en"), "agent/context_sections")["history"]
    summary = item.content["summary"]
    if isinstance(summary, str):
        text = summary
    else:
        text = _summary_dict_to_markdown(summary, labels)
    return [_text_message("user", f"{labels['summary_prefix']}\n{text}")]


def _summary_dict_to_markdown(data: dict, labels: dict | None = None) -> str:
    """Render a legacy dict-typed summary as Markdown with section headings."""
    labels = labels or load_prompt("en", "agent/context_sections")["history"]
    sections: list[str] = []
    for key, value in data.items():
        heading = labels["field_headings"].get(key, key.replace("_", " ").title())
        if isinstance(value, list):
            items = [str(v) for v in value if v]
            if not items:
                continue
            body = "\n".join(f"- {item}" for item in items)
        elif isinstance(value, str):
            body = value.strip()
            if not body:
                continue
        elif value is None:
            continue
        else:
            body = str(value)
        sections.append(f"### {heading}\n\n{body}")
    if not sections:
        return json.dumps(data, ensure_ascii=False, indent=2)
    return labels["compact_heading"] + "\n\n" + "\n\n".join(sections)


def _render_turn(item: ContextItem) -> list[dict[str, Any]]:
    return [
        _text_message("user", str(item.content["user_message"])),
        _text_message("assistant", str(item.content["assistant_final_answer"])),
    ]


def _render_tool_arguments(arguments: Any) -> str:
    """Render tool arguments without dropping string-typed interpreter source."""
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False, default=str)


def _render_current_action(item: ContextItem) -> list[dict[str, Any]]:
    if "messages" in item.content:
        return list(item.content["messages"])
    from html import escape
    from .execution_history import result_text

    c = item.content
    messages = []
    original = c.get("assistant_output")
    if original:
        messages.append(_text_message("assistant", original))
    fields = c.get("execution_fields")
    if fields is None:
        # Compatibility for externally supplied ContextItems, without duplicating result text.
        fields = {}
        if c.get("observations") is not None:
            fields["OUTPUT"] = str(c["observations"])
        result = c.get("result")
        if result is not None and str(result) != str(c.get("observations", "")):
            fields["RETURN_VALUE"] = str(result)
        if c.get("error"):
            fields["ERROR"] = str(c["error"])
    if not original and c.get("tool_calls"):
        calls = c["tool_calls"]
        calls = calls if isinstance(calls, list) else [calls]
        code = "\n\n".join(_render_tool_arguments(call.get("arguments", "")) for call in calls if isinstance(call, dict))
        if not code:
            fields["TOOL_RECORD"] = json.dumps(calls, ensure_ascii=False, default=str)
        if code:
            messages.append(_text_message("assistant", f"<code>\n{code}\n</code>"))
    if not fields:
        fields = {"STDOUT": ""}
    if c.get("summary"):
        body = f"<SUMMARIED_RESULT>{escape(c['summary'])}</SUMMARIED_RESULT>"
    elif c.get("preview") is not None:
        body = '<OUTPUT preview="head_tail">' + escape(c["preview"]) + "</OUTPUT>"
    else:
        body = result_text(fields)
    if (c.get("summary") or c.get("preview") is not None) and fields.get("ERROR"):
        body += "\n<ERROR>" + escape(fields["ERROR"]) + "</ERROR>"
    if c.get("output_ref"):
        body += "\n<OUTPUT_REF>" + escape(c["output_ref"]) + "</OUTPUT_REF>"
    messages.append(_text_message("assistant", "<CODE_EXEC_RESULT>\n" + body + "\n</CODE_EXEC_RESULT>"))
    return messages


class ContextItemRenderer:
    """Registry-backed renderer that consumes only the selected item values."""

    def __init__(self, handlers: dict[ContextItemType, ItemHandler] | None = None):
        self._handlers = {
            ContextItemType.SYSTEM: lambda item: _render_text(item, default_role="system"),
            ContextItemType.KNOWLEDGE_BASE: lambda item: _render_text(item, default_role="user"),
            ContextItemType.HISTORY_SUMMARY: _render_summary,
            ContextItemType.CONVERSATION_TURN: _render_turn,
            ContextItemType.CURRENT_TASK: lambda item: _render_text(item, default_role="user"),
            ContextItemType.CURRENT_PLANNING: lambda item: _render_text(item, default_role="assistant"),
            ContextItemType.CURRENT_ACTION: _render_current_action,
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
        usage_guidance = first.metadata.get("usage_guidance", "")
        if any(
            item.metadata.get("language", "zh") != language
            or bool(item.metadata.get("is_manager", True)) != is_manager
            or item.metadata.get("usage_guidance", "") != usage_guidance
            for item in items[1:]
        ):
            raise ContextItemRenderingError(
                f"render group {first.metadata['render_group']} has inconsistent rendering metadata"
            )
        contents = [item.content for item in items]
        try:
            if first.type == ContextItemType.TOOL:
                data = {str(item["name"]): item for item in contents}
                text = _format_tools_description(
                    data, language=language, is_manager=is_manager,
                )
            elif first.type == ContextItemType.SKILL:
                text = _format_skills_inventory(contents, language=language)
                if usage_guidance:
                    text += f"\n\n{usage_guidance}"
            elif first.type == ContextItemType.MEMORY:
                memory_text = "\n\n".join(
                    str(value)
                    for item in contents
                    for value in [item.get("memory") or item.get("content")]
                    if value
                )
                heading = load_prompt(language, "agent/context_sections")["retrieved_context"]["memory_heading"]
                text = f"{heading}\n{memory_text}" if memory_text else ""
            elif first.type == ContextItemType.WORKER_AGENT:
                data = {str(item["name"]): item for item in contents}
                text = _format_worker_agents_description(data, language=language)
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
