"""In-memory store for offloaded step content, keyed by UUID handle."""

import uuid
import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger("agent_context.offload_store")


class OffloadStore:
    """In-memory store for offloaded step content, keyed by UUID handle."""

    def __init__(self, max_entries: int = 200):
        self._store: Dict[str, str] = {}
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def store(self, content: str) -> str:
        """Store content and return a UUID handle for later retrieval."""
        handle = uuid.uuid4().hex
        with self._lock:
            if len(self._store) >= self._max_entries:
                oldest = next(iter(self._store))
                del self._store[oldest]
            self._store[handle] = content
        return handle

    def reload(self, handle: str) -> Optional[str]:
        """Retrieve offloaded content by handle. Returns None if not found."""
        with self._lock:
            return self._store.get(handle)

    def clear(self) -> None:
        """Clear all offloaded content."""
        with self._lock:
            self._store.clear()
