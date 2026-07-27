"""Reduction result models for context item representation transforms."""

from dataclasses import dataclass, field
from typing import Any, Dict

from .context_item import RepresentationTier


@dataclass(frozen=True)
class ReductionResult:
    """Immutable record of a context item reduction operation.

    Captures the output representation tier, token count, generator
    metadata, admissibility flag, and any loss metadata describing
    what information was discarded during reduction.
    """

    representation: RepresentationTier
    source_fingerprint: str
    token_count: int
    generator: str
    generator_version: str
    admissible: bool
    loss_metadata: Dict[str, Any]
    content: Any
