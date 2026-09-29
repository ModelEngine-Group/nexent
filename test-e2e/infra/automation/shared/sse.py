from __future__ import annotations

import json
import asyncio
from collections import Counter
import os
from pathlib import Path
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx


async def read_sse(response: httpx.Response, limit: int = 1000) -> list[dict[str, Any]]:
    """Consume the whole stream; answer/sub-agent events are not EOF.

    Legacy callers pass token-sized limits (1000/2000). Keep those calls
    compatible, but enforce explicit stream-wide event/byte/time budgets.
    Neither reaching a budget nor receiving an error is a successful terminal.
    """
    events: list[dict[str, Any]] = []
    event_name = "message"
    pending: list[str] = []
    counts: Counter = Counter()
    max_events = int(os.environ.get("NEXENT_SSE_MAX_EVENTS", str(max(limit, 50000))))
    max_bytes = int(os.environ.get("NEXENT_SSE_MAX_BYTES", str(32 * 1024 * 1024)))
    timeout = float(os.environ.get("NEXENT_SSE_TOTAL_TIMEOUT", "300"))
    if min(max_events, max_bytes, timeout) <= 0:
        raise ValueError("SSE budgets must be positive")
    started, byte_count, ending = time.monotonic(), 0, "interrupted"

    def dispatch() -> bool:
        nonlocal event_name
        if not pending:
            event_name = "message"
            return False
        data = "\n".join(pending)
        pending.clear()
        if len(events) >= max_events:
            raise AssertionError(f"SSE_EVENT_BUDGET_EXCEEDED: limit={max_events}; types={dict(counts)}")
        if data == "[DONE]":
            events.append({"event": "done", "data": None})
            counts["[DONE]"] += 1
            return True
        try:
            payload: Any = json.loads(data)
        except json.JSONDecodeError:
            payload = data
        events.append({"event": event_name, "data": payload})
        counts[str(payload.get("type", event_name)) if isinstance(payload, dict) else event_name] += 1
        event_name = "message"
        return False

    try:
        async with asyncio.timeout(timeout):
            async for raw in response.aiter_lines():
                byte_count += len(raw.encode("utf-8")) + 1
                if byte_count > max_bytes:
                    raise AssertionError(f"SSE_BYTE_BUDGET_EXCEEDED: limit={max_bytes}")
                line = raw.rstrip("\r")
                if not line:
                    if dispatch():
                        ending = "done_marker"
                        break
                elif line.startswith("event:"):
                    event_name = line[6:].lstrip(" ")
                elif line.startswith("data:"):
                    pending.append(line[5:].removeprefix(" "))
            else:
                ending = "done_marker" if dispatch() else "eof"
        return events
    except TimeoutError:
        ending = "timeout"
        raise
    except BaseException as exc:
        ending = type(exc).__name__
        raise
    finally:
        # Metadata only: no prompt, content, URL, headers or credentials.
        if os.environ.get("RESULT_DIR"):
            path = Path(os.environ["RESULT_DIR"]) / "runtime/sse-streams.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"events": len(events), "types": dict(counts),
                    "bytes": byte_count, "ending": ending, "max_events": max_events,
                    "duration_seconds": round(time.monotonic() - started, 3)}) + "\n")


def assert_terminal_event(events: list[dict[str, Any]]) -> None:
    assert events, "SSE stream returned no events"
    names = {str(item.get("event", "")).lower() for item in events}
    def terminal_payload(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("is_complete") is True or value.get("isComplete") is True or value.get("done") is True:
                return True
            if str(value.get("status", "")).lower() in {"done", "complete", "completed", "final", "success"}:
                return True
            # Nexent runtime emits the terminal answer as a regular SSE
            # `message` whose payload type is `final_answer`; it does not emit
            # a second `done` event.  Treat the documented payload type as the
            # terminal marker while leaving content assertions to each case.
            if str(value.get("type", "")).lower() in {"final", "final_answer", "completed"}:
                return True
            return any(terminal_payload(child) for child in value.values())
        if isinstance(value, list):
            return any(terminal_payload(child) for child in value)
        return False

    assert names.intersection({"done", "complete", "completed", "final", "result"}) or any(
        terminal_payload(item.get("data")) for item in events
    ), (
        f"SSE stream has no terminal event; observed={sorted(names)}"
    )
