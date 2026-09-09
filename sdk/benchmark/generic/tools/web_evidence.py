"""Benchmark-only normalization and aggregation for web retrieval traces."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag


SEARCH_TOOL_NAMES = {
    "exa_search",
    "tavily_search",
    "linkup_search",
}
FETCH_TOOL_NAMES = {
    "tavily_extract",
}
_TERMINAL_FETCH_RE = re.compile(
    r"\b(?:curl|wget)\b[\s\S]*?https?://[^\s\"']+",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s\"'<>\])}]+", re.IGNORECASE)


def classify_web_tool(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Classify a tool call into a stable web-retrieval role."""
    normalized = (tool_name or "").strip().lower()
    if normalized in SEARCH_TOOL_NAMES:
        return "search"
    if normalized in FETCH_TOOL_NAMES:
        return "fetch"
    if normalized == "terminal":
        command = str(arguments.get("command", ""))
        return "terminal_fetch" if _TERMINAL_FETCH_RE.search(command) else "terminal"
    return None


def build_web_evidence(
    steps: list[dict[str, Any]],
    *,
    task_query: str = "",
    answer_candidate: str = "",
) -> dict[str, Any]:
    """Build a per-item evidence ledger from observer events retained by Benchmark.

    This is deliberately observational. It records what URL was discovered and
    what URL was fetched, but does not claim that a source directly supports the
    final answer without a semantic judge.
    """
    events: list[dict[str, Any]] = []
    pending_searches: list[int] = []

    for step in steps:
        step_number = step.get("step_number")
        if not isinstance(step_number, int):
            continue
        for raw_event in step.get("web_events", []):
            event_type = raw_event.get("event_type")
            if event_type == "tool_call":
                tool_name = str(raw_event.get("tool_name", ""))
                arguments = raw_event.get("tool_arguments")
                if not isinstance(arguments, dict):
                    arguments = {}
                role = classify_web_tool(tool_name, arguments)
                if role is None:
                    continue
                event = {
                    "sequence": len(events) + 1,
                    "step_number": step_number,
                    "event_type": "tool_call",
                    "tool_name": tool_name,
                    "role": role,
                    "arguments": arguments,
                    "query": str(arguments.get("query", "")) or None,
                    "requested_urls": _requested_urls(arguments, role),
                    "returned_urls": [],
                }
                events.append(event)
                if role == "search":
                    pending_searches.append(len(events) - 1)
            elif event_type == "search_content":
                urls = _extract_result_urls(raw_event.get("content"))
                if pending_searches:
                    events[pending_searches.pop(0)]["returned_urls"].extend(urls)

    metrics = _item_metrics(events)
    ledger = _evidence_ledger(events)
    missing_evidence = []
    if not ledger:
        missing_evidence.append("no_source_url_discovered")
    if metrics["discovered_url_but_no_fetch"]:
        missing_evidence.append("discovered_source_not_fetched")
    if ledger:
        missing_evidence.append("semantic_direct_support_not_assessed")
    return {
        "contract_version": 1,
        "task_query": task_query,
        "answer_candidate": answer_candidate,
        "evidence_ledger": ledger,
        "missing_evidence": missing_evidence,
        "semantics": {
            "direct_support_assessed": False,
            "note": (
                "URL discovery and fetch transitions are observed; semantic "
                "support for the final answer is not inferred."
            ),
        },
        "events": events,
        "metrics": metrics,
    }


def aggregate_web_evidence(
    item_evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate stable web-tool counters across benchmark items."""
    additive_fields = (
        "web_tool_calls",
        "search_calls",
        "exa_search_calls",
        "tavily_search_calls",
        "fetch_calls",
        "tavily_extract_calls",
        "terminal_calls",
        "terminal_fetch_calls",
        "repeated_search_queries",
        "search_after_url_discovery",
        "discovered_url_count",
        "fetched_discovered_url_count",
    )
    totals = {
        field: sum(
            int(evidence.get("metrics", {}).get(field, 0) or 0)
            for evidence in item_evidence.values()
        )
        for field in additive_fields
    }
    totals.update({
        "item_count": len(item_evidence),
        "items_with_web_calls": sum(
            bool(evidence.get("metrics", {}).get("web_tool_calls"))
            for evidence in item_evidence.values()
        ),
        "items_with_search_but_no_fetch": sum(
            bool(evidence.get("metrics", {}).get("search_but_no_fetch"))
            for evidence in item_evidence.values()
        ),
        "items_with_discovered_url_but_no_fetch": sum(
            bool(evidence.get("metrics", {}).get("discovered_url_but_no_fetch"))
            for evidence in item_evidence.values()
        ),
    })
    return totals


def write_web_evidence_artifact(
    *,
    output_dir: Path,
    run_name: str,
    dataset_name: str,
    item_evidence: dict[str, dict[str, Any]],
    exa_cache: dict[str, Any] | None = None,
) -> Path:
    """Persist one immutable web evidence artifact for a benchmark run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = web_evidence_artifact_path(output_dir, run_name)
    payload = {
        "schema_version": 1,
        "run_name": run_name,
        "dataset_name": dataset_name,
        "aggregate": aggregate_web_evidence(item_evidence),
        "exa_cache": exa_cache or {"mode": "off"},
        "items": item_evidence,
    }
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def web_evidence_artifact_path(output_dir: Path, run_name: str) -> Path:
    """Return the canonical artifact path for a run."""
    safe_name = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in run_name
    )
    return output_dir / f"{safe_name}.web-evidence.json"


def _item_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    tool_counts = Counter(event["tool_name"].lower() for event in events)
    search_events = [event for event in events if event["role"] == "search"]
    fetch_events = [
        event for event in events if event["role"] in {"fetch", "terminal_fetch"}
    ]
    discovered_urls: list[str] = []
    fetched_urls: list[str] = []
    searches_after_discovery = 0
    seen_query_counts: Counter[str] = Counter()

    for event in events:
        if event["role"] == "search":
            if discovered_urls:
                searches_after_discovery += 1
            normalized_query = " ".join((event.get("query") or "").lower().split())
            if normalized_query:
                seen_query_counts[normalized_query] += 1
            discovered_urls.extend(event.get("returned_urls", []))
        elif event["role"] in {"fetch", "terminal_fetch"}:
            fetched_urls.extend(event.get("requested_urls", []))

    discovered = set(discovered_urls)
    fetched = set(fetched_urls)
    return {
        "web_tool_calls": len(events),
        "search_calls": len(search_events),
        "exa_search_calls": tool_counts["exa_search"],
        "tavily_search_calls": tool_counts["tavily_search"],
        "fetch_calls": len(fetch_events),
        "tavily_extract_calls": tool_counts["tavily_extract"],
        "terminal_calls": tool_counts["terminal"],
        "terminal_fetch_calls": sum(
            event["role"] == "terminal_fetch" for event in events
        ),
        "repeated_search_queries": sum(
            max(count - 1, 0) for count in seen_query_counts.values()
        ),
        "search_after_url_discovery": searches_after_discovery,
        "discovered_url_count": len(discovered),
        "fetched_discovered_url_count": len(discovered & fetched),
        "search_but_no_fetch": bool(search_events and not fetch_events),
        "discovered_url_but_no_fetch": bool(discovered and not (discovered & fetched)),
    }


def _evidence_ledger(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    discovered_by_url: dict[str, dict[str, Any]] = {}
    fetched_by_url: dict[str, list[str]] = {}
    for event in events:
        for url in event.get("returned_urls", []):
            discovered_by_url.setdefault(url, {
                "url": url,
                "discovered_by": event["tool_name"],
                "fetched": False,
                "fetch_tools": [],
                "directly_supports_answer": None,
            })
        if event["role"] in {"fetch", "terminal_fetch"}:
            for url in event.get("requested_urls", []):
                fetched_by_url.setdefault(url, []).append(event["tool_name"])
    for url, entry in discovered_by_url.items():
        tools = list(dict.fromkeys(fetched_by_url.get(url, [])))
        entry["fetched"] = bool(tools)
        entry["fetch_tools"] = tools
    return list(discovered_by_url.values())


def _requested_urls(arguments: dict[str, Any], role: str) -> list[str]:
    if role == "fetch":
        raw_urls = arguments.get("url") or arguments.get("urls")
        if isinstance(raw_urls, str):
            raw_urls = [raw_urls]
        if isinstance(raw_urls, list):
            return _dedupe_urls(str(url) for url in raw_urls)
    if role == "terminal_fetch":
        return _dedupe_urls(_URL_RE.findall(str(arguments.get("command", ""))))
    return []


def _extract_result_urls(content: Any) -> list[str]:
    parsed = content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _dedupe_urls(_URL_RE.findall(content))
    values = parsed if isinstance(parsed, list) else [parsed]
    urls: list[str] = []
    for value in values:
        if isinstance(value, dict):
            candidate = value.get("url")
            if candidate:
                urls.append(str(candidate))
    return _dedupe_urls(urls)


def _dedupe_urls(urls) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = urldefrag(str(raw_url).strip())[0].rstrip(".,;")
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result
