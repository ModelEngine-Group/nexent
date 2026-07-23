"""Lightweight REM analysis and candidate construction."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .models import DreamingCandidate


NOISE_PATTERNS = (
    r"\b(todo|today|temporary|this session|current task)\b",
    r"(今日|今天|待办|临时|本轮|当前任务)",
)
CONCEPT_PATTERNS = {
    "preference": (r"\b(prefer|preference|always use|likes?)\b", r"(偏好|喜欢|习惯|总是使用)"),
    "persistent": (r"\b(always|persist|long[- ]term|stable)\b", r"(长期|稳定|持续|固定)"),
    "build": (r"\b(build|compile|deploy|package)\b", r"(构建|编译|部署|打包)"),
    "failure": (r"\b(error|failure|failed|exception|bug)\b", r"(错误|失败|异常|故障)"),
    "transaction": (r"\b(transaction|commit|rollback|atomic)\b", r"(事务|提交|回滚|原子)"),
    "routing": (r"\b(route|routing|gateway|proxy)\b", r"(路由|网关|代理)"),
}


def analyze_rem_content(content: str) -> Tuple[List[str], bool]:
    normalized = " ".join(content.split()).lower()
    noise = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in NOISE_PATTERNS)
    tags = [
        tag
        for tag, patterns in CONCEPT_PATTERNS.items()
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)
    ]
    word_tags = re.findall(r"[\u4e00-\u9fff]{2,8}|[a-z][a-z0-9_-]{2,}", normalized)
    for tag in word_tags:
        if tag not in tags and len(tags) < 8:
            tags.append(tag)
    return tags, noise


def build_candidate(record: Dict[str, Any], total_retrieval_score: float) -> DreamingCandidate:
    tags, noise = analyze_rem_content(str(record.get("content") or ""))
    merged_tags = list(dict.fromkeys([*(record.get("concept_tags") or []), *tags]))
    return DreamingCandidate(
        memory_id=int(record["memory_id"]),
        tenant_id=str(record["tenant_id"]),
        user_id=str(record["user_id"]),
        agent_id=str(record["agent_id"]),
        content=str(record.get("content") or ""),
        recall_count=int(record.get("recall_count") or 0),
        daily_count=int(record.get("daily_count") or 0),
        grounded_count=int(record.get("grounded_count") or 0),
        total_retrieval_score=float(total_retrieval_score or 0),
        query_hashes=list(record.get("query_hashes") or []),
        recall_days=list(record.get("recall_days") or []),
        concept_tags=merged_tags,
        light_hits=int(record.get("light_hits") or 0),
        rem_hits=int(record.get("rem_hits") or 0),
        last_recalled_at=record.get("last_recalled_at"),
        last_light_at=record.get("last_light_at"),
        last_rem_at=record.get("last_rem_at"),
        noise=noise,
        already_promoted=bool(record.get("already_promoted", False)),
    )
