"""Statistics and export pure functions for ContextManager."""

import logging
from typing import List, Optional

from ..summary_cache import CompressionCallRecord

logger = logging.getLogger("agent_context.stats_export")


def get_step_compression_stats(step_local_log: List[CompressionCallRecord]) -> dict:
    """Compute compression statistics for the current step."""
    if not step_local_log:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_types": []}
    cache_types = [r.call_type for r in step_local_log if r.cache_hit]
    return {
        "calls": len([r for r in step_local_log if not r.cache_hit]),
        "input_tokens": sum(r.input_tokens for r in step_local_log),
        "output_tokens": sum(r.output_tokens for r in step_local_log),
        "input_chars": sum(r.input_chars for r in step_local_log),
        "output_chars": sum(r.output_chars for r in step_local_log),
        "cache_hits": sum(1 for r in step_local_log if r.cache_hit),
        "cache_types": cache_types,
    }


def get_all_compression_stats(calls_log: List[CompressionCallRecord]) -> dict:
    """Compute cumulative compression statistics across all calls."""
    real_calls = [r for r in calls_log if not r.cache_hit]
    return {
        "total_calls": len(real_calls),
        "total_attempts": len(calls_log),
        "total_input_tokens": sum(r.input_tokens for r in real_calls),
        "total_output_tokens": sum(r.output_tokens for r in real_calls),
        "total_cache_hits": sum(1 for r in calls_log if r.cache_hit),
    }


def export_summary(prev_cache, curr_cache, config) -> dict:
    """Export current compression summary state for benchmark inspection.

    Returns a dict with the compressed summary texts, cache metadata,
    and compression boundary information. The boundary info tells the
    benchmark author which pairs/steps were compressed into the summary
    vs. which were retained verbatim -- this is critical for validating
    probe design (probes should only target compressed content).
    """
    return {
        "previous_summary": prev_cache.summary_text if prev_cache else None,
        "current_summary": curr_cache.summary_text if curr_cache else None,
        "previous_cache_info": (
            {
                "covered_pairs": prev_cache.covered_pairs,
                "is_fallback": "[CONTEXT COMPACTION" in (prev_cache.summary_text or ""),
            }
            if prev_cache else None
        ),
        "current_cache_info": (
            {
                "end_steps": curr_cache.end_steps,
                "is_fallback": "[CONTEXT COMPACTION" in (curr_cache.summary_text or ""),
            }
            if curr_cache else None
        ),
        "compression_boundary": {
            "config_keep_recent_pairs": config.keep_recent_pairs,
            "config_keep_recent_steps": config.keep_recent_steps,
            "previous_compressed_pairs": (
                prev_cache.covered_pairs if prev_cache else 0
            ),
            "previous_retained_pairs": config.keep_recent_pairs,
            "current_compressed_steps": (
                curr_cache.end_steps if curr_cache else 0
            ),
            "current_retained_steps": config.keep_recent_steps,
        },
    }


def get_token_counts(last_uncompressed: Optional[int], last_compressed: Optional[int]) -> dict:
    """Return token counts from the most recent compression pass.

    Returns dict with last_uncompressed and last_compressed token counts,
    enabling accurate token_reduction measurement in benchmarks.
    """
    return {
        "last_uncompressed": last_uncompressed,
        "last_compressed": last_compressed,
    }
