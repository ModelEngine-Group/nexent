"""Runtime scenario catalog and selection state."""

from __future__ import annotations

import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class ScenarioCatalog:
    def __init__(self, path: str, default: str) -> None:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        scenarios = raw.get("scenarios")
        if not isinstance(scenarios, dict) or not scenarios:
            raise ValueError("Scenario catalog must define a non-empty 'scenarios' mapping")
        if default not in scenarios:
            raise ValueError(f"Default scenario '{default}' does not exist")
        self._scenarios: dict[str, dict[str, Any]] = scenarios
        self._default = default
        self._current = default
        self._lock = threading.Lock()

    @property
    def current_name(self) -> str:
        with self._lock:
            return self._current

    def current(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._scenarios[self._current])

    def select(self, name: str) -> dict[str, Any]:
        if name not in self._scenarios:
            raise KeyError(name)
        with self._lock:
            self._current = name
        return self.current()

    def reset(self) -> None:
        with self._lock:
            self._current = self._default

    def names(self) -> list[str]:
        return sorted(self._scenarios)

