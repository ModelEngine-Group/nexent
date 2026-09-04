"""Run-local searchable history archive used by emergency context recovery."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from smolagents import Tool


ARCHIVE_KINDS = frozenset({"chat_turn", "tool_call", "observation", "error", "result"})
_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|token)$", re.IGNORECASE)
_WORD = re.compile(r"[\w]+", re.UNICODE)


def _redact(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(name): _redact(item, key=str(name))
            for name, item in value.items()
            if str(name).lower() not in {"reasoning", "thoughts", "chain_of_thought"}
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "[BINARY OMITTED]"
    return value


def _text(value: Any) -> str:
    return json.dumps(_redact(value), ensure_ascii=False, sort_keys=True, default=str)


def _features(value: str) -> set[str]:
    normalized = value.casefold()
    words = set(_WORD.findall(normalized))
    compact = re.sub(r"\s+", "", normalized)
    grams = {compact[i:i + size] for size in (2, 3) for i in range(max(0, len(compact) - size + 1))}
    return words | grams


@dataclass(frozen=True)
class ArchiveRecord:
    archive_id: str
    kind: str
    source_id: str
    content: str
    ordinal: int


class RunHistoryArchive:
    """An isolated in-memory index whose lifetime is one Agent run."""

    def __init__(self, *, run_id: str, hard_input_budget: int, chars_per_token: float = 1.5):
        self.run_id = run_id
        self.hard_input_budget = max(1, int(hard_input_budget))
        self.chars_per_token = max(0.1, float(chars_per_token))
        self._records: list[ArchiveRecord] = []
        self.recall_invocations = 0
        self.recalled_tokens = 0

    @property
    def records(self) -> tuple[ArchiveRecord, ...]:
        return tuple(self._records)

    def add(self, *, kind: str, source_id: str, content: Any) -> ArchiveRecord | None:
        if kind not in ARCHIVE_KINDS:
            raise ValueError(f"unsupported archive kind: {kind}")
        rendered = _text(content)
        if not rendered or rendered in {'""', "null", "[]", "{}"}:
            return None
        ordinal = len(self._records)
        digest = hashlib.sha256(f"{self.run_id}\0{kind}\0{source_id}\0{ordinal}".encode()).hexdigest()[:16]
        record = ArchiveRecord(f"archive:{digest}", kind, str(source_id), rendered, ordinal)
        self._records.append(record)
        return record

    def search(self, query: str, top_k: int = 5, kinds: Iterable[str] | None = None) -> dict[str, Any]:
        self.recall_invocations += 1
        limit = min(5, max(1, int(top_k)))
        selected_kinds = set(kinds or ARCHIVE_KINDS)
        invalid = selected_kinds - ARCHIVE_KINDS
        if invalid:
            raise ValueError(f"unsupported archive kinds: {', '.join(sorted(invalid))}")
        query_features = _features(str(query))
        ranked = []
        for record in self._records:
            if record.kind not in selected_kinds:
                continue
            record_features = _features(record.content)
            overlap = len(query_features & record_features)
            if not overlap:
                continue
            score = overlap / math.sqrt(max(1, len(query_features) * len(record_features)))
            ranked.append((score, record.ordinal, record))
        ranked.sort(key=lambda row: (-row[0], -row[1], row[2].archive_id))

        token_cap = max(1, int(self.hard_input_budget * 0.2))
        char_cap = max(1, int(token_cap * self.chars_per_token))
        used_chars = 0
        results = []
        for score, _, record in ranked[:limit]:
            remaining = char_cap - used_chars
            if remaining <= 0:
                break
            content = record.content[:remaining]
            used_chars += len(content)
            results.append({
                "archive_id": record.archive_id,
                "kind": record.kind,
                "source_id": record.source_id,
                "score": round(score, 6),
                "content": content,
            })
        recalled = min(token_cap, math.ceil(used_chars / self.chars_per_token))
        self.recalled_tokens += recalled
        return {"results": results, "recalled_tokens": recalled, "token_cap": token_cap}


class SearchArchivedHistoryTool(Tool):
    name = "search_archived_history"
    description = (
        "Search older run history that was removed from the active prompt during context recovery. "
        "Use only when missing prior user, answer, tool, observation, error, or result detail is relevant."
    )
    inputs = {
        "query": {"type": "string", "description": "Natural-language or keyword search."},
        "top_k": {"type": "integer", "description": "Number of results, clamped to 1-5.", "nullable": True},
        "kinds": {
            "type": "array", "description": "Optional archive kind filter.",
            "items": {"type": "string"}, "nullable": True,
        },
    }
    output_type = "object"

    def __init__(self, archive: RunHistoryArchive):
        self.archive = archive
        super().__init__()

    def forward(self, query: str, top_k: int = 5, kinds: list[str] | None = None) -> dict[str, Any]:
        return self.archive.search(query=query, top_k=top_k, kinds=kinds)
