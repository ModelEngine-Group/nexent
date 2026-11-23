"""Benchmark-only deterministic record/replay for ``ExaSearchTool``."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any


CACHE_SCHEMA_VERSION = 1
_controller: "ExaReplayController | None" = None
_original_forward = None


class ExaReplayController:
    """Thread-safe file-backed cache with strict replay miss behavior."""

    def __init__(self, mode: str, path: Path):
        if mode not in {"record", "replay"}:
            raise ValueError("Exa cache mode must be 'record' or 'replay'")
        self.mode = mode
        self.path = path
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._stats = {"hits": 0, "misses": 0, "live_calls": 0, "writes": 0}
        self._load()

    def call(self, tool: Any, query: str, original_forward) -> str:
        request = {
            "query": str(query),
            "max_results": int(getattr(tool, "max_results", 0) or 0),
            "image_filter": bool(getattr(tool, "image_filter", False)),
        }
        key = _cache_key(request)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._stats["hits"] += 1
                output = str(entry["output"])
                _emit_replayed_observer_events(tool, query, output)
                return output
            self._stats["misses"] += 1
            if self.mode == "replay":
                raise RuntimeError(
                    "Exa replay cache miss; live fallback is disabled "
                    f"(query_sha256={hashlib.sha256(str(query).encode()).hexdigest()})"
                )

        output = original_forward(tool, query)
        with self._lock:
            self._stats["live_calls"] += 1
            self._entries[key] = {
                "request": request,
                "output": output,
            }
            self._write()
            self._stats["writes"] += 1
        return output

    def snapshot(self) -> dict[str, Any]:
        """Return non-secret run metadata and counters."""
        with self._lock:
            return {
                "mode": self.mode,
                "path": str(self.path),
                "schema_version": CACHE_SCHEMA_VERSION,
                "entry_count": len(self._entries),
                **self._stats,
            }

    def _load(self) -> None:
        if not self.path.exists():
            if self.mode == "replay":
                raise FileNotFoundError(
                    f"Exa replay cache does not exist: {self.path}"
                )
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported Exa cache schema in {self.path}: "
                f"{payload.get('schema_version')!r}"
            )
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            raise ValueError(f"Invalid Exa replay cache entries: {self.path}")
        self._entries = entries

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "entries": self._entries,
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


def install_exa_record_replay(mode: str, path: str | Path) -> ExaReplayController:
    """Patch Exa only inside the benchmark process and return its controller."""
    global _controller, _original_forward

    from nexent.core.tools.exa_search_tool import ExaSearchTool

    controller = ExaReplayController(mode=mode, path=Path(path).resolve())
    if _original_forward is None:
        _original_forward = ExaSearchTool.forward

        def cached_forward(tool, query: str):
            if _controller is None:
                return _original_forward(tool, query)
            return _controller.call(tool, query, _original_forward)

        ExaSearchTool.forward = cached_forward
    _controller = controller
    return controller


def uninstall_exa_record_replay() -> None:
    """Restore the SDK class; intended for tests and embedded benchmark callers."""
    global _controller, _original_forward

    if _original_forward is not None:
        from nexent.core.tools.exa_search_tool import ExaSearchTool

        ExaSearchTool.forward = _original_forward
    _controller = None
    _original_forward = None


def _cache_key(request: dict[str, Any]) -> str:
    canonical = json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _emit_replayed_observer_events(tool: Any, query: str, output: str) -> None:
    observer = getattr(tool, "observer", None)
    if observer is None:
        return
    from nexent.core.utils.observer import ProcessType

    observer.add_message(
        "",
        ProcessType.CARD,
        json.dumps([{"icon": "search", "text": query}], ensure_ascii=False),
    )
    observer.add_message("", ProcessType.SEARCH_CONTENT, output)
    try:
        result_count = len(json.loads(output))
    except (TypeError, ValueError, json.JSONDecodeError):
        result_count = 0
    if hasattr(tool, "record_ops"):
        tool.record_ops += result_count
