"""LLM compression call record used by context evidence."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CompressionCallRecord:
    """Record of a compression LLM call for logging and metrics."""
    call_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    input_chars: int = 0
    output_chars: int = 0
    cache_hit: bool = False
    details: Optional[dict] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}
