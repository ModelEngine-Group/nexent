"""Unit tests for the Phase 4 retrieval pipeline SDK modules."""

import sys
import os
import logging
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "sdk"))

from nexent.memory.retrieval.token_counter import count_tokens, count_tokens_from_records
from nexent.memory.retrieval.normalizer import Normalizer
from nexent.memory.retrieval.score_fusion import ScoreFusion
from nexent.memory.retrieval.temporal_decay import TemporalDecayer
from nexent.memory.retrieval.mmr import MMRDeduplicator, _jaccard_similarity
from nexent.memory.retrieval.token_budget import TokenBudgetSelector
from nexent.memory.retrieval.pipeline import RetrievalPipeline, enable_debug_logging
from nexent.memory.models import (
    ExternalMemoryItem,
    MemoryLayer,
    MemorySearchResult,
    MemoryType,
    PipelineConfig,
    PipelineMemoryRecord,
    RetrievalSource,
)


# ---------------------------------------------------------------------------
# token_counter
# ---------------------------------------------------------------------------

class TestCountTokens:
    def test_basic_split(self):
        assert count_tokens("hello world") == 4  # 2 chunks + 2 overhead

    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_whitespace_only(self):
        assert count_tokens("   \n\t  ") == 0

    def test_single_word(self):
        assert count_tokens("hello") == 2

    def test_records_aggregation(self):
        records = [{"content": "foo bar"}, {"content": "baz qux"}]
        total = count_tokens_from_records(records)
        assert total == count_tokens("foo bar") + count_tokens("baz qux")


# ---------------------------------------------------------------------------
# normalizer
# ---------------------------------------------------------------------------

class TestNormalizer:
    def _make_result(self, memory_id=1, content="test", score=0.8,
                     layer=MemoryLayer.AGENT, is_external=False, metadata=None):
        return MemorySearchResult(
            memory_id=memory_id, content=content, score=score,
            layer=layer, is_external=is_external,
            metadata=metadata or {"memory_type": "short_term"},
        )

    def _make_external(self, content="ext", score=0.7):
        return ExternalMemoryItem(
            id="ext_1", content=content, score=score,
            provider="mem0", metadata={},
        )

    def test_normalize_internal_agent(self):
        normalizer = Normalizer()
        records = normalizer.normalize([self._make_result(5, "agent memory")])
        assert len(records) == 1
        assert records[0].source == RetrievalSource.AGENT_SHORT_TERM
        assert records[0].is_external is False
        assert records[0].record_id == "5"
        assert records[0].score == 0.8
        assert records[0].token_count > 0

    def test_normalize_external(self):
        normalizer = Normalizer()
        records = normalizer.normalize([], external_results=[self._make_external()])
        assert len(records) == 1
        assert records[0].source == RetrievalSource.EXTERNAL
        assert records[0].is_external is True
        assert records[0].record_id == "ext_1"

    def test_normalize_mixed_sources(self):
        normalizer = Normalizer()
        records = normalizer.normalize(
            [self._make_result(1)],
            external_results=[self._make_external()],
        )
        assert len(records) == 2
        sources = {r.source for r in records}
        assert RetrievalSource.AGENT_SHORT_TERM in sources
        assert RetrievalSource.EXTERNAL in sources

    def test_normalize_empty(self):
        normalizer = Normalizer()
        assert normalizer.normalize([]) == []

    def test_normalize_external_with_scope(self):
        normalizer = Normalizer()
        item = ExternalMemoryItem(
            id="ext_2", content="content", score=0.9,
            provider="a800",
            metadata={"tenant_id": "t1", "user_id": "u1"},
        )
        records = normalizer.normalize([], external_results=[item])
        assert records[0].tenant_id == "t1"
        assert records[0].user_id == "u1"

    def test_normalize_with_created_at_for_id(self):
        """Test age_days is computed from created_at_for_id mapping."""
        from datetime import datetime, timedelta
        normalizer = Normalizer()
        # memory_id=42, created 7 days ago
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        created_map = {42: seven_days_ago}
        result = self._make_result(memory_id=42, content="recent memory", score=0.9)
        records = normalizer.normalize([result], created_at_for_id=created_map)
        assert len(records) == 1
        # 6.5-7.5 days (allowing some tolerance)
        assert 6.5 < records[0].age_days < 7.5, \
            f"Expected ~7 days, got {records[0].age_days}"

    def test_normalize_created_at_invalid_memory_id(self):
        """Test that invalid memory_id in created_at_for_id is handled gracefully."""
        from datetime import datetime
        normalizer = Normalizer()
        # memory_id is a valid int, but not in the map
        created_map = {999: datetime.utcnow()}
        result = self._make_result(memory_id=42, content="memory", score=0.8)
        records = normalizer.normalize([result], created_at_for_id=created_map)
        assert len(records) == 1
        assert records[0].age_days is None

    def test_normalize_record_id_from_external_id(self):
        """Test record_id uses external_id when memory_id is absent."""
        normalizer = Normalizer()
        result = MemorySearchResult(
            memory_id=None,
            external_id="ext_ref_99",
            content="via external_id",
            score=0.7,
            layer=MemoryLayer.AGENT,
            is_external=True,
            metadata={},
        )
        records = normalizer.normalize([result])
        assert records[0].record_id == "ext_ext_ref_99"

    def test_normalize_unknown_memory_type_falls_back_to_short_term(self):
        """Test that unknown memory_type string falls back to SHORT_TERM."""
        normalizer = Normalizer()
        result = self._make_result(
            memory_id=1, content="test",
            metadata={"memory_type": "unknown_type"},
        )
        records = normalizer.normalize([result])
        assert records[0].memory_type == MemoryType.SHORT_TERM

    def test_normalize_created_at_type_error_on_conversion(self, mocker):
        """Test that int() raising TypeError is handled gracefully."""
        normalizer = Normalizer()
        result = self._make_result(memory_id=42, content="memory", score=0.8)
        mocker.patch("nexent.memory.retrieval.normalizer.int", side_effect=TypeError("mocked"))
        records = normalizer.normalize([result], created_at_for_id={42: None})
        assert len(records) == 1
        assert records[0].age_days is None

    def test_normalize_created_at_value_error_on_conversion(self, mocker):
        """Test that int() raising ValueError is handled gracefully."""
        normalizer = Normalizer()
        result = self._make_result(memory_id=99, content="memory", score=0.8)
        mocker.patch("nexent.memory.retrieval.normalizer.int", side_effect=ValueError("mocked"))
        records = normalizer.normalize([result], created_at_for_id={99: None})
        assert len(records) == 1
        assert records[0].age_days is None


# ---------------------------------------------------------------------------
# score_fusion
# ---------------------------------------------------------------------------

class TestScoreFusion:
    def _make_record(self, source=RetrievalSource.AGENT_SHORT_TERM, score=0.8):
        return PipelineMemoryRecord(
            record_id="1", content="test", score=score,
            source=source, is_external=(source == RetrievalSource.EXTERNAL),
            tenant_id="t1", layer=MemoryLayer.AGENT,
        )

    def test_agent_short_term_weight(self):
        fuser = ScoreFusion(w_agent_short_term=1.0, w_external=0.8)
        record = self._make_record(RetrievalSource.AGENT_SHORT_TERM, 0.8)
        fused = fuser.fuse([record])
        assert fused[0].source_weight == 1.0
        assert fused[0].fused_score == 0.8

    def test_external_weight(self):
        fuser = ScoreFusion(w_agent_short_term=1.0, w_external=0.8)
        record = self._make_record(RetrievalSource.EXTERNAL, 1.0)
        fused = fuser.fuse([record])
        assert fused[0].source_weight == 0.8
        assert fused[0].fused_score == 0.8

    def test_idempotency(self):
        fuser = ScoreFusion(w_agent_short_term=1.0, w_external=0.8)
        record = self._make_record(RetrievalSource.AGENT_SHORT_TERM, 0.8)
        record.fused_score = 0.5
        fused = fuser.fuse([record])
        assert fused[0].fused_score == 0.5

    def test_unknown_source_falls_back_to_1(self):
        fuser = ScoreFusion()
        record = self._make_record(RetrievalSource.AGENT_SHORT_TERM, 0.5)
        fused = fuser.fuse([record])
        assert fused[0].source_weight == 1.0


# ---------------------------------------------------------------------------
# temporal_decay
# ---------------------------------------------------------------------------

class TestTemporalDecayer:
    def _make_short_term(self, score=0.8, age_days=7.0):
        return PipelineMemoryRecord(
            record_id="1", content="test", score=score,
            source=RetrievalSource.AGENT_SHORT_TERM, is_external=False,
            tenant_id="t1", layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            fused_score=score, age_days=age_days,
        )

    def test_decay_half_life(self):
        decayer = TemporalDecayer(half_life_days=14)
        record = self._make_short_term(score=1.0, age_days=14.0)
        decayed = decayer.apply_decay([record])
        assert 0.49 < decayed[0].fused_score < 0.51

    def test_no_decay_without_age_days(self):
        decayer = TemporalDecayer(half_life_days=14)
        record = self._make_short_term(score=0.8)
        record.age_days = None
        decayed = decayer.apply_decay([record])
        assert decayed[0].fused_score == 0.8

    def test_no_decay_for_user_long_term(self):
        decayer = TemporalDecayer(half_life_days=14)
        record = PipelineMemoryRecord(
            record_id="2", content="user long-term", score=0.9,
            source=RetrievalSource.AGENT_SHORT_TERM, is_external=False,
            tenant_id="t1", layer=MemoryLayer.USER,
            memory_type=MemoryType.LONG_TERM,
            fused_score=0.9, age_days=30.0,
        )
        decayed = decayer.apply_decay([record])
        assert decayed[0].fused_score == 0.9

    def test_no_decay_for_external(self):
        decayer = TemporalDecayer(half_life_days=14)
        record = PipelineMemoryRecord(
            record_id="ext_1", content="external", score=0.9,
            source=RetrievalSource.EXTERNAL, is_external=True,
            tenant_id="t1", layer=MemoryLayer.AGENT,
            fused_score=0.9, age_days=60.0,
        )
        decayed = decayer.apply_decay([record])
        assert decayed[0].fused_score == 0.9

    def test_invalid_half_life_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TemporalDecayer(half_life_days=0)
        with pytest.raises(ValueError, match="positive"):
            TemporalDecayer(half_life_days=-1)

    def test_decay_formula_sqrt_half(self):
        decayer = TemporalDecayer(half_life_days=14)
        record = self._make_short_term(score=1.0, age_days=7.0)
        decayed = decayer.apply_decay([record])
        assert 0.70 < decayed[0].fused_score < 0.71


# ---------------------------------------------------------------------------
# mmr
# ---------------------------------------------------------------------------

class TestJaccardSimilarity:
    def test_identical_strings(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_disjoint_strings(self):
        assert _jaccard_similarity("cat", "dog") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("hello world", "hello there")
        assert 0.0 < sim < 1.0

    def test_empty_string(self):
        assert _jaccard_similarity("", "hello") == 0.0
        assert _jaccard_similarity("hello", "") == 0.0
        assert _jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello WORLD", "hello world") == 1.0


class TestMMRDeduplicator:
    def _make_record(self, record_id, content, fused_score, layer=MemoryLayer.AGENT):
        return PipelineMemoryRecord(
            record_id=record_id, content=content, score=fused_score,
            fused_score=fused_score,
            source=RetrievalSource.AGENT_SHORT_TERM,
            is_external=False, tenant_id="t1", layer=layer,
        )

    def test_empty_input(self):
        assert MMRDeduplicator().dedupe([]) == []

    def test_returns_top_k(self):
        mmr = MMRDeduplicator(mmr_lambda=0.7, mmr_final_k=2)
        records = [
            self._make_record("1", "content one", 0.9),
            self._make_record("2", "content two", 0.8),
            self._make_record("3", "content three", 0.7),
        ]
        result = mmr.dedupe(records, query="test")
        assert len(result) == 2
        assert result[0].fused_score >= result[1].fused_score

    def test_prunes_near_duplicates(self):
        mmr = MMRDeduplicator(
            mmr_lambda=0.7, mmr_final_k=5,
            mmr_duplicate_threshold=0.92,
        )
        records = [
            self._make_record("1", "hello world the quick brown fox jumps over", 0.95),
            self._make_record("2", "hello world the quick brown fox jumps over", 0.8),
            self._make_record("3", "completely different content", 0.7),
        ]
        result = mmr.dedupe(records, query="test")
        assert len(result) <= 2
        assert "1" in {r.record_id for r in result}

    def test_lambda_one_pure_relevance(self):
        mmr = MMRDeduplicator(mmr_lambda=1.0, mmr_final_k=2)
        records = [
            self._make_record("1", "unrelated", 0.3),
            self._make_record("2", "highly relevant content", 0.9),
            self._make_record("3", "moderately relevant", 0.7),
        ]
        result = mmr.dedupe(records, query="test")
        assert result[0].record_id == "2"
        assert len(result) == 2

    def test_invalid_lambda_raises(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            MMRDeduplicator(mmr_lambda=1.5)
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            MMRDeduplicator(mmr_lambda=-0.1)

    def test_invalid_final_k_raises(self):
        with pytest.raises(ValueError, match="positive"):
            MMRDeduplicator(mmr_final_k=0)

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            MMRDeduplicator(mmr_duplicate_threshold=1.5)


# ---------------------------------------------------------------------------
# token_budget
# ---------------------------------------------------------------------------

class TestTokenBudgetSelector:
    def _make_record(self, record_id, token_count, fused_score):
        return PipelineMemoryRecord(
            record_id=record_id, content="x " * token_count,
            score=fused_score, fused_score=fused_score,
            source=RetrievalSource.AGENT_SHORT_TERM,
            is_external=False, tenant_id="t1", layer=MemoryLayer.AGENT,
            token_count=token_count,
        )

    def test_empty_input(self):
        assert TokenBudgetSelector(token_budget=1000).select([]) == []

    def test_zero_budget(self):
        selector = TokenBudgetSelector(token_budget=0)
        assert selector.select([self._make_record("1", 10, 0.9)]) == []

    def test_records_sorted_by_score(self):
        selector = TokenBudgetSelector(token_budget=1000)
        records = [
            self._make_record("1", 50, 0.3),
            self._make_record("2", 50, 0.9),
            self._make_record("3", 50, 0.6),
        ]
        result = selector.select(records)
        assert result[0].record_id == "2"

    def test_budget_exceeded_early_stop(self):
        selector = TokenBudgetSelector(token_budget=80)
        records = [
            self._make_record("1", 50, 0.9),
            self._make_record("2", 50, 0.8),
        ]
        result = selector.select(records)
        assert len(result) == 1
        assert result[0].record_id == "1"

    def test_invalid_budget_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            TokenBudgetSelector(token_budget=-1)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------

class TestRetrievalPipeline:
    def _make_result(self, memory_id, content, score=0.8,
                     layer=MemoryLayer.AGENT, is_external=False, metadata=None):
        return MemorySearchResult(
            memory_id=memory_id, content=content, score=score,
            layer=layer, is_external=is_external,
            metadata=metadata or {"memory_type": "short_term"},
        )

    def _make_external(self, content="ext", score=0.7):
        return ExternalMemoryItem(
            id="ext_1", content=content, score=score,
            provider="mem0", metadata={},
        )

    def test_split_by_layer(self):
        pipeline = RetrievalPipeline()
        results = [
            self._make_result(1, "tenant memory", layer=MemoryLayer.TENANT),
            self._make_result(2, "user memory", layer=MemoryLayer.USER),
            self._make_result(3, "agent memory", layer=MemoryLayer.AGENT),
        ]
        pr = pipeline.run(results, query="test")
        assert len(pr.tenant_long_term) == 1
        assert len(pr.user_long_term) == 1
        assert len(pr.agent_short_term) == 1

    def test_tenant_user_passed_through_verbatim(self):
        pipeline = RetrievalPipeline()
        pr = pipeline.run([
            self._make_result(1, "tenant mem", layer=MemoryLayer.TENANT),
            self._make_result(2, "user mem", layer=MemoryLayer.USER),
        ], query="test")
        assert pr.tenant_long_term[0].content == "tenant mem"
        assert pr.user_long_term[0].content == "user mem"

    def test_external_results_integrated(self):
        pipeline = RetrievalPipeline()
        pr = pipeline.run(
            [self._make_result(1, "agent mem", layer=MemoryLayer.AGENT)],
            query="test",
            external_results=[self._make_external("external mem")],
        )
        assert len(pr.agent_short_term) == 2

    def test_empty_results(self):
        pipeline = RetrievalPipeline()
        pr = pipeline.run([], query="test")
        assert pr.tenant_long_term == []
        assert pr.user_long_term == []
        assert pr.agent_short_term == []

    def test_default_config(self):
        pipeline = RetrievalPipeline()
        assert pipeline._mmr_final_k == 5
        assert pipeline._token_budget == 2000

    def test_into_memory_search_context(self):
        pipeline = RetrievalPipeline()
        pr = pipeline.run([
            self._make_result(1, "tenant mem", layer=MemoryLayer.TENANT),
            self._make_result(2, "user mem", layer=MemoryLayer.USER),
            self._make_result(3, "agent mem", layer=MemoryLayer.AGENT),
        ], query="test")
        ctx = pr.into_memory_search_context()
        assert len(ctx.tenant_long_term) == 1
        assert len(ctx.user_long_term) == 1


# ---------------------------------------------------------------------------
# PipelineConfig
# ---------------------------------------------------------------------------

class TestPipelineConfig:
    def test_defaults(self):
        cfg = PipelineConfig()
        assert cfg.mmr_lambda == 0.7
        assert cfg.mmr_candidate_top_k == 30
        assert cfg.mmr_final_top_k == 5
        assert cfg.mmr_duplicate_threshold == 0.92
        assert cfg.half_life_days == 14
        assert cfg.w_agent_short_term == 1.0
        assert cfg.w_external == 0.8
        assert cfg.token_budget == 2000

    def test_custom_values(self):
        cfg = PipelineConfig(mmr_lambda=0.5, token_budget=500)
        assert cfg.mmr_lambda == 0.5
        assert cfg.token_budget == 500


# ---------------------------------------------------------------------------
# enable_debug_logging
# ---------------------------------------------------------------------------

class TestEnableDebugLogging:
    def test_sets_debug_level(self):
        logger = enable_debug_logging()
        assert logger.name == "memory_retrieval"
        assert logger.level == logging.DEBUG

    def test_pipeline_emits_debug_records(self, caplog):
        caplog.set_level(logging.DEBUG, logger="memory_retrieval")
        pipeline = RetrievalPipeline()
        results = [
            MemorySearchResult(
                memory_id=1, content="agent memory", score=0.8,
                layer=MemoryLayer.AGENT, is_external=False,
                metadata={"memory_type": "short_term"},
            ),
        ]
        with caplog.at_level(logging.DEBUG, logger="memory_retrieval"):
            pipeline.run(results, query="test")

        # Pipeline must emit stage markers and per-record lines
        messages = [r.message for r in caplog.records if r.name == "memory_retrieval.pipeline"]
        joined = "\n".join(messages)
        assert "[pipeline] start:" in joined
        assert "STEP=normalize" in joined
        assert "STEP=fusion" in joined
        assert "STEP=mmr" in joined
        assert "STEP=budget" in joined
        assert "[pipeline] done:" in joined
