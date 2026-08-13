"""Streaming guard for buffered A2UI blocks during streaming output."""

from __future__ import annotations

import logging
from typing import Any

from .constants import A2UI_CLOSE_TAG, A2UI_OPEN_TAG
from .parser import may_contain_a2ui_content
from .validator import validate_a2ui_response

logger = logging.getLogger(__name__)


class A2UIStreamGuard:
    """Buffers and validates A2UI blocks during streaming output.

    Ensures that complete A2UI blocks are validated before being passed to
    the frontend. Falls back gracefully when validation fails.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside_block = False

    def feed(self, content: str) -> list[str]:
        """Process a chunk of streaming content.

        Returns validated text/A2UI fragments ready for output.
        """
        if not content:
            return []
        self._buffer += content
        return self._drain()

    def finish(self) -> list[str]:
        """Process remaining buffer at end of stream."""
        if not self._buffer:
            return []
        if self._inside_block:
            # Incomplete block - extract what we can as text
            fallback = self._buffer.strip()
            self._buffer = ""
            self._inside_block = False
            return [fallback] if fallback else []
        remaining = self._buffer
        self._buffer = ""
        return [remaining] if remaining else []

    def _drain(self) -> list[str]:
        """Drain complete blocks from the buffer."""
        emitted: list[str] = []
        while self._buffer:
            if not self._inside_block:
                start = self._buffer.find(A2UI_OPEN_TAG)
                if start < 0:
                    # Keep a small suffix to handle split tags
                    keep = max(len(A2UI_OPEN_TAG) - 1, 0)
                    if len(self._buffer) <= keep:
                        break
                    emitted.append(self._buffer[:-keep])
                    self._buffer = self._buffer[-keep:]
                    break
                if start > 0:
                    emitted.append(self._buffer[:start])
                    self._buffer = self._buffer[start:]
                self._inside_block = True

            end = self._buffer.find(A2UI_CLOSE_TAG)
            if end < 0:
                break

            block_end = end + len(A2UI_CLOSE_TAG)
            block = self._buffer[:block_end]
            self._buffer = self._buffer[block_end:]
            self._inside_block = False

            # Validate the complete block
            validation = validate_a2ui_response(block)
            if validation.valid:
                emitted.append(block)
            else:
                logger.warning("A2UI stream guard: block validation failed: %s", validation.error)
                # Fall back to text - extract any readable content
                from .parser import strip_tagged_a2ui_blocks
                fallback = strip_tagged_a2ui_blocks(block)
                if fallback:
                    emitted.append(fallback)

        return [item for item in emitted if item]


__all__ = ["A2UIStreamGuard"]