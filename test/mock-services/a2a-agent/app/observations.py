"""Bounded in-memory request observations for test assertions."""

from __future__ import annotations

import threading
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


class ObservationStore:
    def __init__(self, limit: int = 1000) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def add(self, item: dict[str, Any]) -> None:
        entry = deepcopy(item)
        entry["observed_at"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._items.append(entry)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._items))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

