"""Cache dataclasses for agent context compression."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PreviousSummaryCache:
    """Caches the compressed summary from the previous run."""
    summary_text: str
    covered_pairs: int
    anchor_fingerprint: str


@dataclass
class CurrentSummaryCache:
    """Caches the compressed summary for the current run."""
    summary_text: str
    end_steps: int
    anchor_fingerprint: str


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