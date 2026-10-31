# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validate source-grounded memory candidates before automatic persistence."""

from __future__ import annotations

import json
import re


_REQUEST_LOCAL = re.compile(
    r"本(?:轮|次|回合)|这(?:次|一轮|一回)|此次|当前任务|仅(?:限|用于)|临时|今天|今日|明天|"
    r"\b(?:this (?:time|turn|answer|response|request|task|session)|"
    r"current (?:task|request|session|answer)|for (?:now|today|this)|today|tomorrow|temporary|temporarily|one[- ]off)\b",
    re.IGNORECASE,
)
_LASTING_INTENT = re.compile(
    r"长期|固定|默认|今后|以后|一贯|总是|始终|习惯|偏好|喜欢|通常|"
    r"每(?:天|周|月|年)|一直|所有|必须|不得|禁止|"
    r"\b(?:prefer\w*|usually|always|typically|habit\w*|never|must|policy|"
    r"by default|from now on|in (?:the )?future|long[- ]term)\b",
    re.IGNORECASE,
)
_CONFIRMED_OUTCOME = re.compile(
    r"已(?:经|完成|验证|确认|部署|修复)|成功|\b(?:completed|verified|confirmed|succeeded|resolved)\b",
    re.IGNORECASE,
)
_SUGGESTION = re.compile(
    r"建议|可以|应当|应该|用户偏好|用户喜欢|\b(?:recommend\w*|should|could|user prefers|user preference)\b",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY = re.compile(r"[。！？!?；;\n]|\.(?=\s|$)")
_REFERENCE_REQUEST = re.compile(
    r"^(?:请按(?:照)?|按照我|沿用|根据你|按我(?:的|长期|既有|一贯))|[?？]|"
    r"(?:沿用|仍用|按(?:照)?|遵循|依照|继续使用|保持).{0,30}"
    r"(?:既有|已有|之前|原有|一贯|常态|我(?:的)?|长期|你记(?:得|住)).{0,16}"
    r"(?:偏好|习惯|结构|格式|风格|要求|约定|规范)|"
    r"\b(?:follow|use|using|keep|stick with).{0,40}"
    r"(?:my|existing|previous|usual|long[- ]term).{0,25}"
    r"(?:preferences?|formats?|styles?|structures?|habits?)\b",
    re.IGNORECASE,
)
_CATEGORIES = {"user_preference", "user_fact", "task_outcome", "lesson"}
MAX_CANDIDATES = 20
MAX_EVIDENCE_CHARS = 1000


def _source_context(source: str, evidence: str) -> str:
    """Include scope qualifiers omitted from a model's supporting excerpt."""
    contexts = []
    offset = 0
    while (position := source.find(evidence, offset)) >= 0:
        before = list(_CLAUSE_BOUNDARY.finditer(source, 0, position))
        after = _CLAUSE_BOUNDARY.search(source, position + len(evidence) - 1)
        start = before[-1].end() if before else 0
        end = after.start() if after else len(source)
        contexts.append(source[start:end])
        offset = position + len(evidence)
    return "\n".join(contexts)


def parse_grounded_items(raw: str, user_query: str, final_answer: str) -> list[str]:
    """Fail closed on untyped, invented, local or assistant-derived preferences.

    Persist the supporting excerpt, not the model's paraphrase, so a valid
    source quote cannot be used to smuggle an unsupported preference into it.
    The JSON protocol is internal to automatic extraction; stored records and
    public memory APIs keep their existing content-only contract.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    candidates = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        return []

    items = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("scope") != "durable":
            continue
        category = candidate.get("category")
        origin = candidate.get("source")
        evidence = candidate.get("evidence")
        if not isinstance(category, str) or category not in _CATEGORIES or not isinstance(evidence, str):
            continue
        evidence = evidence.strip()
        if not evidence or len(evidence) > MAX_EVIDENCE_CHARS:
            continue
        if _REFERENCE_REQUEST.search(evidence):
            continue
        source = user_query if origin == "user" else final_answer if origin == "final_answer" else ""
        if not source or evidence not in source:
            continue
        context = _source_context(source, evidence)
        if _REQUEST_LOCAL.search(context):
            continue
        if category in {"user_preference", "user_fact"}:
            if origin != "user":
                continue
            if category == "user_preference" and not _LASTING_INTENT.search(context):
                continue
        elif origin == "final_answer":
            if not _CONFIRMED_OUTCOME.search(evidence) or _SUGGESTION.search(evidence):
                continue
        if evidence not in items:
            items.append(evidence)
    return items
