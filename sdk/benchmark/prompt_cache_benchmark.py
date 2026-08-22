"""Offline evidence aggregation for W3 repeated-turn prompt-cache benchmarks.

Feed this module the final manifests and usage records emitted by a real agent
run.  It does not manufacture provider hits: prefix reuse and provider cache
hits remain separate measurements so deployments can compare both values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from nexent.core.models.prompt_cache import PromptCacheUsage


@dataclass(frozen=True)
class RepeatedTurnCacheBenchmark:
    turn_count: int
    repeated_turn_count: int
    stable_prefix_reuse_ratio: float
    provider_cache_hit_ratio: float
    cached_input_tokens: int
    uncached_input_tokens: int
    estimated_saved_input_tokens: float

    def to_dict(self) -> dict:
        return asdict(self)


def summarize_repeated_turn_cache_benchmark(
    manifests: Sequence[Any],
    usages: Sequence[PromptCacheUsage],
) -> RepeatedTurnCacheBenchmark:
    """Summarize one repeated-turn run from ContextManager evidence."""
    if len(manifests) != len(usages):
        raise ValueError("manifests and usages must contain one record per turn")

    repeated_turn_count = sum(
        1
        for previous, current in zip(manifests, manifests[1:])
        if previous.stable_prefix_fingerprint == current.stable_prefix_fingerprint
    )
    turn_count = len(manifests)
    cached = sum(usage.cached_input_tokens for usage in usages)
    uncached = sum(usage.uncached_input_tokens for usage in usages)
    cache_hits = sum(1 for usage in usages if usage.provider_cache_hit)
    return RepeatedTurnCacheBenchmark(
        turn_count=turn_count,
        repeated_turn_count=repeated_turn_count,
        stable_prefix_reuse_ratio=round(repeated_turn_count / max(turn_count - 1, 1), 4),
        provider_cache_hit_ratio=round(cache_hits / turn_count, 4) if turn_count else 0.0,
        cached_input_tokens=cached,
        uncached_input_tokens=uncached,
        estimated_saved_input_tokens=round(
            sum(usage.estimated_saved_input_tokens for usage in usages), 2
        ),
    )
