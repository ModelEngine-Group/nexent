"""Token-counting utilities for the memory retrieval pipeline."""

from __future__ import annotations

import re
from typing import List


def count_tokens(text: str) -> int:
    """Estimate the number of tokens in a string.

    Splits on whitespace and common punctuation, then adds a fixed overhead
    of 1 token per chunk to approximate typical LLM tokenisation.
    """
    if not text:
        return 0
    chunks = re.split(r"[\s\n\r\t]+|[,.:;!?()\[\]{}«»""''…—–\-]+", text)
    non_empty = [c for c in chunks if c]
    return len(non_empty) + len(non_empty)


def count_tokens_from_records(records: List[dict]) -> int:
    """Sum the estimated token counts for a list of memory record dicts."""
    return sum(count_tokens(r.get("content", "")) for r in records)
