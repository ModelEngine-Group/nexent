"""In-memory store for offloaded step content, keyed by UUID handle."""

import uuid
import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger("agent_context.offload_store")


class OffloadStore:
    """In-memory store for offloaded step content, keyed by UUID handle."""

    def __init__(self, max_entries: int = 200, max_total_chars: int = 2_000_000, max_entry_chars: int = 30000):
        self._store: Dict[str, str] = {}
        self._max_entries = max_entries
        self._max_total_chars = max_total_chars
        self._max_entry_chars = max_entry_chars
        self._current_total = 0
        self._lock = threading.Lock()

    def store(self, content: str) -> Optional[str]:
        """Store content and return a UUID handle for later retrieval.

        Returns None if the content exceeds ``max_entry_chars`` and cannot be stored.
        """
        if len(content) > self._max_entry_chars:
            logger.warning(
                f"Content exceeds max_entry_chars ({self._max_entry_chars}), "
                f"skipping offload for {len(content)} chars"
            )
            return None

        handle = uuid.uuid4().hex
        with self._lock:
            # Evict oldest entries if total chars would exceed budget
            while (self._current_total + len(content) > self._max_total_chars
                   and self._store):
                oldest = next(iter(self._store))
                self._current_total -= len(self._store[oldest])
                del self._store[oldest]

            # Evict oldest entry if count budget exceeded
            if len(self._store) >= self._max_entries:
                oldest = next(iter(self._store))
                self._current_total -= len(self._store[oldest])
                del self._store[oldest]

            self._store[handle] = content
            self._current_total += len(content)
        return handle

    def reload(self, handle: str) -> Optional[str]:
        """Retrieve offloaded content by handle. Returns None if not found."""
        with self._lock:
            return self._store.get(handle)

    def __len__(self) -> int:
        """Return the number of stored entries. Thread-safe."""
        with self._lock:
            return len(self._store)

    def items(self):
        """Return a thread-safe snapshot of all (handle, content) pairs."""
        with self._lock:
            return list(self._store.items())

    def clear(self) -> None:
        """Clear all offloaded content."""
        with self._lock:
            self._store.clear()
            self._current_total = 0
