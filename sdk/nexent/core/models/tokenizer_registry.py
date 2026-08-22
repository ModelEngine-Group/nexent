from __future__ import annotations

import json
import logging
import re
from typing import Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .capacity_resolver import CountingMode

logger = logging.getLogger("tokenizer_registry")


TOKENIZER_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{0,49}$")


def is_valid_family_identifier(family: str) -> bool:
    """Validate against the naming convention fixed by W1 ADR Decision 1."""
    return bool(TOKENIZER_FAMILY_PATTERN.match(family))


@runtime_checkable
class TokenizerAdapter(Protocol):
    """Contract for a tokenizer-family counting implementation.

    Implementations must be deterministic, side-effect free, and threadsafe.
    Promotion from `estimated` to `exact` requires meeting the accuracy gate
    defined in W1 ADR Decision 1 (>=100-message fixture, MAE <= 0.5%, max single
    error <= 2%).
    """

    family: str

    def count_tokens(self, messages: Sequence[dict]) -> int: ...


class FallbackEstimator:
    """Generic character-to-token estimator used when no family adapter matches.

    Never marked `exact`. Purpose: avoid hard failures when a catalog entry has
    an unknown tokenizer family — operators always see a budget number, just one
    that triggers W2's 10% uncertainty reserve.
    """

    family = "_fallback"

    def count_tokens(self, messages: Sequence[dict]) -> int:
        encoded = json.dumps(list(messages), ensure_ascii=False)
        return max(1, len(encoded) // 4)


FALLBACK: TokenizerAdapter = FallbackEstimator()


REGISTRY: Dict[str, TokenizerAdapter] = {}


def register(adapter: TokenizerAdapter) -> None:
    """Register a verified adapter. Called once at import time by adapter modules."""
    family = adapter.family
    if not is_valid_family_identifier(family):
        raise ValueError(
            f"Tokenizer family {family!r} does not match required pattern "
            f"{TOKENIZER_FAMILY_PATTERN.pattern}"
        )
    if family in REGISTRY:
        raise ValueError(f"Tokenizer family {family!r} is already registered")
    REGISTRY[family] = adapter


def resolve(family: Optional[str]) -> Tuple[TokenizerAdapter, CountingMode]:
    """Return (adapter, counting_mode) for the requested tokenizer family.

    Returns FALLBACK with `estimated` when family is None or unmapped. Returns
    the registered adapter with `exact` when a verified mapping exists.
    """
    if family is None or family not in REGISTRY:
        return FALLBACK, "estimated"
    return REGISTRY[family], "exact"
