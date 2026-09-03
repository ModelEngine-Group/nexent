"""Validated, one-call selection of relevant Markdown long-term memory blocks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from smolagents.models import ChatMessage, MessageRole


@dataclass(frozen=True)
class MarkdownBlock:
    block_id: str
    scope: str
    text: str
    headings: tuple[str, ...]
    order: int


def parse_markdown_blocks(scope: str, markdown: str) -> list[MarkdownBlock]:
    """Split headings, paragraphs and list items into stable code-owned blocks."""
    blocks: list[MarkdownBlock] = []
    headings: list[str] = []
    paragraph: list[str] = []

    def append(text: str) -> None:
        normalized = text.strip()
        if not normalized:
            return
        digest = hashlib.sha256(f"{scope}\0{len(blocks)}\0{normalized}".encode()).hexdigest()[:16]
        blocks.append(MarkdownBlock(f"{scope}:{digest}", scope, normalized, tuple(headings), len(blocks)))

    def flush() -> None:
        if paragraph:
            append("\n".join(paragraph))
            paragraph.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        marker_length = len(stripped) - len(stripped.lstrip("#"))
        is_heading = (
            1 <= marker_length <= 6
            and len(stripped) > marker_length
            and stripped[marker_length].isspace()
            and bool(stripped[marker_length:].strip())
        )
        if is_heading:
            flush()
            headings[:] = headings[: marker_length - 1]
            headings.append(stripped)
        elif re.match(r"^\s*(?:[-*+] |\d+[.)] )", line):
            flush()
            append(line.strip())
        elif line.strip():
            paragraph.append(line.rstrip())
        else:
            flush()
    flush()
    return blocks


def _render(blocks: Iterable[MarkdownBlock]) -> str:
    output: list[str] = []
    active: tuple[str, ...] = ()
    for block in sorted(blocks, key=lambda value: value.order):
        common = 0
        while common < min(len(active), len(block.headings)) and active[common] == block.headings[common]:
            common += 1
        output.extend(block.headings[common:])
        output.append(block.text)
        active = block.headings
    return "\n\n".join(output)


def _fair_fallback(by_scope: dict[str, list[MarkdownBlock]], max_chars: int) -> dict[str, str]:
    scopes = [scope for scope, blocks in by_scope.items() if blocks]
    if not scopes:
        return {}
    share = max(1, max_chars // len(scopes))
    result: dict[str, str] = {}
    for scope in scopes:
        selected: list[MarkdownBlock] = []
        for block in by_scope[scope]:
            candidate = _render([*selected, block])
            if len(candidate) <= share:
                selected.append(block)
            elif not selected:
                marker = "\n\n[… long-term memory block omitted …]\n\n"
                room = max(0, share - len(marker))
                head = room // 2
                text = block.text[:head] + marker + block.text[-(room - head):]
                selected.append(MarkdownBlock(block.block_id, scope, text, block.headings, block.order))
                break
        result[scope] = _render(selected)
    return result


def select_long_term_memory(
    documents: dict[str, str], *, task: str, target_tokens: int, model: Any, chars_per_token: float
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return validated Markdown subsets; model can select IDs but never author text."""
    by_scope = {scope: parse_markdown_blocks(scope, text) for scope, text in documents.items()}
    max_chars = max(1, math.floor(target_tokens * chars_per_token))
    catalog = {
        scope: [{"id": block.block_id, "text": block.text} for block in blocks]
        for scope, blocks in by_scope.items()
    }
    prompt = json.dumps({
        "task": task,
        "budget_chars": max_chars,
        "blocks": catalog,
        "response_schema": {"selections": {scope: ["block-id"] for scope in catalog}},
        "rules": ["Return JSON only", "Select IDs only", "Keep each ID at most once"],
    }, ensure_ascii=False)
    try:
        usage_kwargs = (
            {
                "usage_purpose": "history_summary",
                "usage_turn_id": getattr(model, "default_usage_turn_id", None),
            }
            if hasattr(model, "provider_call_usages")
            else {}
        )
        response = model(
            [ChatMessage(role=MessageRole.USER, content=[{"type": "text", "text": prompt}])],
            stop_sequences=[],
            **usage_kwargs,
        )
        output = response.content
        if isinstance(output, list):
            output = "".join(block.get("text", "") for block in output if isinstance(block, dict))
        envelope = json.loads(str(output))
        selections = envelope.get("selections")
        if not isinstance(selections, dict) or set(selections) != set(by_scope):
            raise ValueError("invalid selector envelope")
        rendered: dict[str, str] = {}
        for scope, blocks in by_scope.items():
            ids = selections[scope]
            if not isinstance(ids, list) or len(ids) != len(set(ids)):
                raise ValueError("duplicate or invalid block ids")
            lookup = {block.block_id: block for block in blocks}
            if any(block_id not in lookup for block_id in ids):
                raise ValueError("unknown or cross-scope block id")
            rendered[scope] = _render(lookup[block_id] for block_id in ids)
        if sum(len(value) for value in rendered.values()) > max_chars:
            raise ValueError("selector output exceeds budget")
        return rendered, {"outcome": "selected", "input_chars": len(prompt), "output_chars": len(str(output))}
    except Exception as exc:
        return _fair_fallback(by_scope, max_chars), {
            "outcome": "fallback", "input_chars": len(prompt), "error_type": type(exc).__name__
        }
