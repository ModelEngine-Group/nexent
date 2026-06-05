"""
unit/test_stats_export.py
Tests for stats_export.py pure functions and their ContextManager wrappers.
"""

from factories import make_cm
from loader import (
    CompressionCallRecord,
    ContextManagerConfig,
    CurrentSummaryCache,
    PreviousSummaryCache,
    export_summary_fn,
    get_all_compression_stats,
    get_step_compression_stats,
    get_token_counts,
)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_record(call_type="summary", input_tokens=100, output_tokens=50,
                 input_chars=400, output_chars=200, cache_hit=False):
    return CompressionCallRecord(
        call_type=call_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_chars=input_chars,
        output_chars=output_chars,
        cache_hit=cache_hit,
    )


# ──────────────────────────────────────────────────────────────
# get_step_compression_stats
# ──────────────────────────────────────────────────────────────

class TestGetStepCompressionStats:

    def test_empty_log_returns_defaults(self):
        result = get_step_compression_stats([])
        assert result == {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_hits": 0, "cache_types": [],
        }

    def test_single_real_call(self):
        log = [_make_record(call_type="previous_summary")]
        result = get_step_compression_stats(log)
        assert result["calls"] == 1
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["input_chars"] == 400
        assert result["output_chars"] == 200
        assert result["cache_hits"] == 0
        assert result["cache_types"] == []

    def test_single_cache_hit(self):
        log = [_make_record(call_type="previous_cache_hit", cache_hit=True,
                            input_tokens=0, output_tokens=0)]
        result = get_step_compression_stats(log)
        assert result["calls"] == 0
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["cache_hits"] == 1
        assert result["cache_types"] == ["previous_cache_hit"]

    def test_mixed_real_and_cache_hits(self):
        log = [
            _make_record(call_type="previous_summary", input_tokens=200, output_tokens=80),
            _make_record(call_type="previous_cache_hit", cache_hit=True,
                         input_tokens=0, output_tokens=0),
            _make_record(call_type="current_summary", input_tokens=150, output_tokens=60),
            _make_record(call_type="current_cache_hit", cache_hit=True,
                         input_tokens=0, output_tokens=0),
        ]
        result = get_step_compression_stats(log)
        assert result["calls"] == 2
        assert result["input_tokens"] == 350  # 200 + 150
        assert result["output_tokens"] == 140  # 80 + 60
        assert result["cache_hits"] == 2
        assert result["cache_types"] == ["previous_cache_hit", "current_cache_hit"]

    def test_input_output_chars_summed(self):
        log = [
            _make_record(input_chars=1000, output_chars=500),
            _make_record(input_chars=2000, output_chars=800),
        ]
        result = get_step_compression_stats(log)
        assert result["input_chars"] == 3000
        assert result["output_chars"] == 1300

    def test_cache_types_only_includes_hits(self):
        log = [
            _make_record(call_type="previous_summary", cache_hit=False),
            _make_record(call_type="current_summary", cache_hit=False),
        ]
        result = get_step_compression_stats(log)
        assert result["cache_types"] == []


# ──────────────────────────────────────────────────────────────
# get_all_compression_stats
# ──────────────────────────────────────────────────────────────

class TestGetAllCompressionStats:

    def test_empty_log_returns_zeros(self):
        result = get_all_compression_stats([])
        assert result == {
            "total_calls": 0, "total_attempts": 0,
            "total_input_tokens": 0, "total_output_tokens": 0,
            "total_cache_hits": 0,
        }

    def test_only_cache_hits(self):
        log = [
            _make_record(call_type="previous_cache_hit", cache_hit=True,
                         input_tokens=0, output_tokens=0),
            _make_record(call_type="current_cache_hit", cache_hit=True,
                         input_tokens=0, output_tokens=0),
        ]
        result = get_all_compression_stats(log)
        assert result["total_calls"] == 0
        assert result["total_attempts"] == 2
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["total_cache_hits"] == 2

    def test_only_real_calls(self):
        log = [
            _make_record(input_tokens=300, output_tokens=100),
            _make_record(input_tokens=200, output_tokens=80),
        ]
        result = get_all_compression_stats(log)
        assert result["total_calls"] == 2
        assert result["total_attempts"] == 2
        assert result["total_input_tokens"] == 500
        assert result["total_output_tokens"] == 180
        assert result["total_cache_hits"] == 0

    def test_mixed_real_and_cache(self):
        log = [
            _make_record(call_type="previous_summary", input_tokens=300, output_tokens=100),
            _make_record(call_type="previous_cache_hit", cache_hit=True,
                         input_tokens=0, output_tokens=0),
            _make_record(call_type="current_summary", input_tokens=200, output_tokens=80),
            _make_record(call_type="current_cache_hit", cache_hit=True,
                         input_tokens=0, output_tokens=0),
        ]
        result = get_all_compression_stats(log)
        assert result["total_calls"] == 2
        assert result["total_attempts"] == 4
        assert result["total_input_tokens"] == 500
        assert result["total_output_tokens"] == 180
        assert result["total_cache_hits"] == 2


# ──────────────────────────────────────────────────────────────
# export_summary
# ──────────────────────────────────────────────────────────────

class TestExportSummary:

    def test_both_caches_none(self):
        config = ContextManagerConfig()
        result = export_summary_fn(None, None, config)
        assert result["previous_summary"] is None
        assert result["current_summary"] is None
        assert result["previous_cache_info"] is None
        assert result["current_cache_info"] is None
        assert result["compression_boundary"]["previous_compressed_pairs"] == 0
        assert result["compression_boundary"]["current_compressed_steps"] == 0

    def test_both_caches_present(self):
        config = ContextManagerConfig(keep_recent_pairs=2, keep_recent_steps=3)
        prev = PreviousSummaryCache("prev summary text", 5, "fp_prev")
        curr = CurrentSummaryCache("curr summary text", 4, "fp_curr")
        result = export_summary_fn(prev, curr, config)

        assert result["previous_summary"] == "prev summary text"
        assert result["current_summary"] == "curr summary text"

        assert result["previous_cache_info"]["covered_pairs"] == 5
        assert result["previous_cache_info"]["is_fallback"] is False

        assert result["current_cache_info"]["end_steps"] == 4
        assert result["current_cache_info"]["is_fallback"] is False

        assert result["compression_boundary"]["config_keep_recent_pairs"] == 2
        assert result["compression_boundary"]["config_keep_recent_steps"] == 3
        assert result["compression_boundary"]["previous_compressed_pairs"] == 5
        assert result["compression_boundary"]["previous_retained_pairs"] == 2
        assert result["compression_boundary"]["current_compressed_steps"] == 4
        assert result["compression_boundary"]["current_retained_steps"] == 3

    def test_previous_only_current_none(self):
        config = ContextManagerConfig()
        prev = PreviousSummaryCache("prev only", 3, "fp")
        result = export_summary_fn(prev, None, config)

        assert result["previous_summary"] == "prev only"
        assert result["current_summary"] is None
        assert result["previous_cache_info"] is not None
        assert result["current_cache_info"] is None
        assert result["compression_boundary"]["previous_compressed_pairs"] == 3
        assert result["compression_boundary"]["current_compressed_steps"] == 0

    def test_current_only_previous_none(self):
        config = ContextManagerConfig()
        curr = CurrentSummaryCache("curr only", 2, "fp")
        result = export_summary_fn(None, curr, config)

        assert result["previous_summary"] is None
        assert result["current_summary"] == "curr only"
        assert result["previous_cache_info"] is None
        assert result["current_cache_info"] is not None
        assert result["compression_boundary"]["previous_compressed_pairs"] == 0
        assert result["compression_boundary"]["current_compressed_steps"] == 2

    def test_fallback_detection_previous(self):
        """summary_text containing '[CONTEXT COMPACTION' marks is_fallback=True."""
        config = ContextManagerConfig()
        prev = PreviousSummaryCache("[CONTEXT COMPACTION... truncated]", 1, "fp")
        result = export_summary_fn(prev, None, config)
        assert result["previous_cache_info"]["is_fallback"] is True

    def test_fallback_detection_current(self):
        config = ContextManagerConfig()
        curr = CurrentSummaryCache("[CONTEXT COMPACTION fallback text]", 1, "fp")
        result = export_summary_fn(None, curr, config)
        assert result["current_cache_info"]["is_fallback"] is True

    def test_boundary_uses_zero_when_cache_none(self):
        config = ContextManagerConfig(keep_recent_pairs=10, keep_recent_steps=20)
        result = export_summary_fn(None, None, config)
        assert result["compression_boundary"]["previous_compressed_pairs"] == 0
        assert result["compression_boundary"]["current_compressed_steps"] == 0
        assert result["compression_boundary"]["previous_retained_pairs"] == 10
        assert result["compression_boundary"]["current_retained_steps"] == 20


# ──────────────────────────────────────────────────────────────
# get_token_counts
# ──────────────────────────────────────────────────────────────

class TestGetTokenCounts:

    def test_both_values_present(self):
        result = get_token_counts(5000, 2000)
        assert result == {"last_uncompressed": 5000, "last_compressed": 2000}

    def test_both_none(self):
        result = get_token_counts(None, None)
        assert result == {"last_uncompressed": None, "last_compressed": None}

    def test_only_uncompressed(self):
        result = get_token_counts(3000, None)
        assert result == {"last_uncompressed": 3000, "last_compressed": None}

    def test_only_compressed(self):
        result = get_token_counts(None, 500)
        assert result == {"last_uncompressed": None, "last_compressed": 500}

    def test_zero_values(self):
        result = get_token_counts(0, 0)
        assert result == {"last_uncompressed": 0, "last_compressed": 0}


# ──────────────────────────────────────────────────────────────
# ContextManager wrapper methods
# ──────────────────────────────────────────────────────────────

class TestContextManagerStatsMethods:

    def test_get_step_compression_stats_delegates(self):
        """ContextManager.get_step_compression_stats() delegates to the pure function."""
        cm = make_cm()
        # After a compress call, _step_local_log should have records
        assert isinstance(cm.get_step_compression_stats(), dict)
        assert cm.get_step_compression_stats()["calls"] == 0

    def test_get_all_compression_stats_delegates(self):
        cm = make_cm()
        assert isinstance(cm.get_all_compression_stats(), dict)
        assert cm.get_all_compression_stats()["total_calls"] == 0

    def test_export_summary_delegates(self):
        cm = make_cm()
        result = cm.export_summary()
        assert isinstance(result, dict)
        assert "previous_summary" in result
        assert "current_summary" in result
        assert "previous_cache_info" in result
        assert "compression_boundary" in result

    def test_get_token_counts_delegates(self):
        cm = make_cm()
        # Initial state: both are None
        result = cm.get_token_counts()
        assert result == {"last_uncompressed": None, "last_compressed": None}

    def test_export_summary_reflects_cache_state(self):
        """After setting caches, export_summary should reflect them."""
        cm = make_cm()
        cm._previous_summary_cache = PreviousSummaryCache("test prev", 3, "fp1")
        cm._current_summary_cache = CurrentSummaryCache("test curr", 2, "fp2")
        result = cm.export_summary()
        assert result["previous_summary"] == "test prev"
        assert result["current_summary"] == "test curr"
        assert result["previous_cache_info"]["covered_pairs"] == 3
        assert result["current_cache_info"]["end_steps"] == 2
