# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for the multi-model task routing service."""

from pathlib import Path

import pytest

from management.services.model import routing
from management.services.model.routing import (
    ClassificationResult,
    IntentSource,
    RiskLevel,
    RouteTier,
    classify_run,
    estimate_tokens,
    rank_candidates,
    record_tier,
    reset_rules_cache,
    route_model_selection,
    score_candidate,
)

# The shipped example rules file; pinned explicitly because sibling test
# modules may have replaced contracts.constants.environment with a stub
# whose path attribute would degrade load_rules() to empty vocabularies.
_SHIPPED_RULES_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend" / "configs" / "model_routing_rules.json"
)


@pytest.fixture(autouse=True)
def _isolated_rules(monkeypatch):
    """Pin the shipped rules path and keep the cache isolated per test."""

    import contracts.constants.environment as env_module

    monkeypatch.setattr(
        env_module, "MODEL_ROUTING_RULES_JSON_PATH", str(_SHIPPED_RULES_PATH),
        raising=False,
    )
    reset_rules_cache()
    yield
    reset_rules_cache()


@pytest.fixture
def medical_rules():
    """Load the shipped example rules (medical vocabulary)."""

    return routing.load_rules()


def _record(model_id=1, name="qwen3-30b", tier_facts=None, **overrides):
    record = {
        "model_id": model_id,
        "model_name": name,
        "display_name": name,
        "reasoning_supported": None,
        "enable_thinking": None,
        "context_window_tokens": None,
        "max_input_tokens": None,
    }
    record.update(tier_facts or {})
    record.update(overrides)
    return record


DEEP_FACTS = {"reasoning_supported": True, "context_window_tokens": 65536}
LONG_FACTS = {"reasoning_supported": False, "context_window_tokens": 262144}
QUICK_FACTS = {"reasoning_supported": False, "context_window_tokens": 32768}


class TestRulesLoading:
    def test_missing_file_degrades_to_empty_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "contracts.constants.environment.MODEL_ROUTING_RULES_JSON_PATH",
            str(tmp_path / "nonexistent.json"),
        )
        rules = routing.load_rules()
        assert rules["task_tags"] == {}
        assert rules["risk"]["high_terms"] == []

    def test_shipped_rules_file_loads(self):
        rules = routing.load_rules()
        assert rules["task_tags"], "shipped rules file must carry task tags"
        assert rules["risk"]["high_terms"]

    def test_malformed_file_degrades(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(
            "contracts.constants.environment.MODEL_ROUTING_RULES_JSON_PATH", str(bad)
        )
        rules = routing.load_rules()
        assert rules == routing._DEFAULT_RULES

    def test_reset_reloads_from_disk(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "contracts.constants.environment.MODEL_ROUTING_RULES_JSON_PATH",
            str(tmp_path / "nonexistent.json"),
        )
        routing.load_rules()
        assert routing.load_rules()["task_tags"] == {}
        reset_rules_cache()
        rules = routing.load_rules()
        # Back to the shipped file (its path is the real environment value).
        from contracts.constants.environment import MODEL_ROUTING_RULES_JSON_PATH as real

        monkeypatch.undo()
        reset_rules_cache()
        if str(real) != str(tmp_path / "nonexistent.json"):
            assert routing.load_rules()["task_tags"]


class TestEstimateTokens:
    def test_empty_text(self):
        assert estimate_tokens("", rules=routing._DEFAULT_RULES) == 0

    def test_cjk_counts_one_per_char(self):
        assert estimate_tokens("你好世界", rules=routing._DEFAULT_RULES) == 4

    def test_ascii_counts_words(self):
        # 8 ascii chars -> ceil(8/4) = 2
        assert estimate_tokens("abcdefgh", rules=routing._DEFAULT_RULES) == 2

    def test_history_and_attachments_add_overhead(self):
        rules = dict(routing._DEFAULT_RULES)
        value = estimate_tokens(
            "你好", history_length=3, has_attachments=True, rules=rules
        )
        assert value == 2 + 3 * 200 + 800


class TestClassifyRun:
    def test_explicit_task_tag_wins(self, medical_rules):
        result = classify_run("随便一句话", agent_meta={"task_tag": "mdt"})
        assert result.tier is RouteTier.DEEP_REASONING
        assert result.source is IntentSource.EXPLICIT_TAG
        assert "task_tag:mdt" in result.matched_rules

    def test_unknown_task_tag_falls_through_to_rules(self, medical_rules):
        result = classify_run("房颤患者的鉴别诊断思路", agent_meta={"task_tag": "unknown_tag"})
        assert result.source is IntentSource.RULE
        assert result.tier is RouteTier.DEEP_REASONING

    def test_high_risk_with_analysis_escalates_and_requires_review(self, medical_rules):
        result = classify_run("请分析这个患者的化疗方案选择")
        assert result.tier is RouteTier.DEEP_REASONING
        assert result.risk is RiskLevel.HIGH
        assert result.review_required is True
        assert "risk:escalate_deep" in result.matched_rules

    def test_high_risk_without_analysis_stays_routine_tier(self, medical_rules):
        result = classify_run("化疗的翻译是什么")
        assert result.risk is RiskLevel.HIGH
        assert result.tier is RouteTier.QUICK_QA
        assert result.review_required is False

    def test_long_query_by_size(self, medical_rules):
        result = classify_run("病" * 48000)
        assert result.tier is RouteTier.LONG_CONTEXT
        assert "long_context:size" in result.matched_rules

    def test_long_context_keyword_beats_deep_keyword(self, medical_rules):
        result = classify_run("帮我归纳这份病历并分析病因")
        assert result.tier is RouteTier.LONG_CONTEXT

    def test_deep_reasoning_keyword(self, medical_rules):
        result = classify_run("多学科会诊的步骤是什么")
        assert result.tier is RouteTier.DEEP_REASONING

    def test_quick_qa_keyword(self, medical_rules):
        result = classify_run("CRP的正常值是多少")
        assert result.tier is RouteTier.QUICK_QA

    def test_short_query_defaults_to_quick(self, medical_rules):
        result = classify_run("你好")
        assert result.tier is RouteTier.QUICK_QA
        assert result.source is IntentSource.RULE

    def test_no_signal_yields_default_source(self, medical_rules):
        # >120 chars without any keyword -> DEFAULT source; contract says
        # the caller keeps the pre-routing selection in that case.
        result = classify_run("今天天气不错" + "，窗外有光" * 25)
        assert result.source is IntentSource.DEFAULT
        assert result.tier is RouteTier.QUICK_QA

    def test_empty_vocabularies_fall_to_default(self):
        rules = dict(routing._DEFAULT_RULES)
        rules["quick_qa"] = {"char_limit": 0, "terms": []}
        result = classify_run("任何内容都无所谓", rules=rules)
        assert result.source is IntentSource.DEFAULT

    def test_empty_query_is_safe(self, medical_rules):
        result = classify_run("")
        assert result.source is IntentSource.DEFAULT

    def test_invalid_task_tag_mapping_is_ignored(self):
        rules = dict(routing._DEFAULT_RULES)
        rules["task_tags"] = {"broken": "not_a_tier"}
        result = classify_run("内容", agent_meta={"task_tag": "broken"}, rules=rules)
        assert result.source is not IntentSource.EXPLICIT_TAG


def _result(tier):
    return ClassificationResult(
        tier=tier,
        source=IntentSource.RULE,
        risk=RiskLevel.ROUTINE,
        review_required=False,
        est_tokens=1000,
    )


class TestRecordTier:
    def test_reasoning_flag(self):
        assert record_tier(_record(tier_facts=DEEP_FACTS)) is RouteTier.DEEP_REASONING

    def test_capacity_prefers_input_limit(self):
        record = _record(tier_facts={"max_input_tokens": 32000, "context_window_tokens": 200000})
        # Input limit < 48000 wins over window -> not long tier.
        assert record_tier(record) is RouteTier.QUICK_QA

    def test_capacity(self):
        assert record_tier(_record(tier_facts=LONG_FACTS)) is RouteTier.LONG_CONTEXT

    def test_name_fallback(self):
        assert record_tier(_record(name="deepseek-r1")) is RouteTier.DEEP_REASONING
        assert record_tier(_record(name="qwen-long")) is RouteTier.LONG_CONTEXT
        assert record_tier(_record(name="qwen3-30b")) is RouteTier.QUICK_QA

    def test_reasoning_flag_overrides_capacity(self):
        assert record_tier(_record(tier_facts={
            "reasoning_supported": True, "context_window_tokens": 1000000
        })) is RouteTier.DEEP_REASONING


class TestScoreAndRank:
    def test_wrong_tier_ineligible(self):
        record = _record(tier_facts=LONG_FACTS)
        assert score_candidate(record, _result(RouteTier.DEEP_REASONING)) == -1.0

    def test_capacity_headroom_prefers_larger(self):
        tight = _record(model_id=1, name="tight", tier_facts={
            "reasoning_supported": False, "context_window_tokens": 60000
        })
        large = _record(model_id=2, name="roomy", tier_facts={
            "reasoning_supported": False, "context_window_tokens": 200000
        })
        result = ClassificationResult(
            tier=RouteTier.LONG_CONTEXT, source=IntentSource.RULE,
            risk=RiskLevel.ROUTINE, review_required=False, est_tokens=50000,
        )
        assert score_candidate(large, result) > score_candidate(tight, result)

    def test_insufficient_capacity_rejected(self):
        record = _record(tier_facts={"reasoning_supported": False, "context_window_tokens": 4096})
        result = ClassificationResult(
            tier=RouteTier.LONG_CONTEXT, source=IntentSource.RULE,
            risk=RiskLevel.ROUTINE, review_required=False, est_tokens=100000,
        )
        assert score_candidate(record, result) == -1.0

    def test_rank_orders_desc_and_no_fallback(self):
        records = [
            _record(model_id=1, name="a", tier_facts=QUICK_FACTS),
            _record(model_id=2, name="b", tier_facts={
                "reasoning_supported": False, "context_window_tokens": 100000
            }),
        ]
        ranked, fallback_from = rank_candidates(records, _result(RouteTier.LONG_CONTEXT))
        assert ranked[0][0]["model_id"] == 2
        assert fallback_from is None

    def test_rank_relaxes_and_records_fallback_from(self):
        records = [_record(model_id=1, name="only-long", tier_facts=LONG_FACTS)]
        ranked, fallback_from = rank_candidates(records, _result(RouteTier.QUICK_QA))
        assert ranked and ranked[0][0]["model_id"] == 1
        assert fallback_from is RouteTier.QUICK_QA

    def test_rank_exhausted_returns_empty_with_none(self):
        records = [_record(model_id=1, name="only-quick", tier_facts=QUICK_FACTS)]
        ranked, fallback_from = rank_candidates(records, _result(RouteTier.DEEP_REASONING))
        assert ranked == []
        assert fallback_from is None


class TestRouteModelSelection:
    def test_returns_record_and_decision(self, medical_rules):
        records = [
            _record(model_id=11, name="fast", tier_facts=QUICK_FACTS),
            _record(model_id=12, name="thinker", tier_facts=DEEP_FACTS),
        ]
        selection = route_model_selection(records, "请分析这个患者的鉴别诊断")
        assert selection is not None
        record, decision = selection
        assert record["model_id"] == 12
        assert decision.tier is RouteTier.DEEP_REASONING
        assert decision.selected_model_id == 12
        audit = decision.to_audit_dict()
        assert audit["tier"] == "deep_reasoning"
        assert len(audit["candidates"]) == 1

    def test_no_records_returns_none(self):
        assert route_model_selection([], "query") is None

    def test_default_source_keeps_existing_selection(self, medical_rules):
        # No vocabulary hit -> DEFAULT source -> None (caller keeps the
        # pre-routing model). This is the backward-compatibility contract.
        records = [
            _record(model_id=5, name="m", tier_facts=QUICK_FACTS),
            _record(model_id=6, name="n", tier_facts=DEEP_FACTS),
        ]
        assert route_model_selection(records, "今天天气不错" + "，窗外有光" * 25) is None

    def test_short_query_routes_to_quick(self, medical_rules):
        records = [
            _record(model_id=5, name="m", tier_facts=QUICK_FACTS),
            _record(model_id=6, name="n", tier_facts=DEEP_FACTS),
        ]
        selection = route_model_selection(records, "你好")
        assert selection is not None
        record, decision = selection
        assert record["model_id"] == 5
        assert decision.fallback_from is None

    def test_fallback_from_is_audited(self, medical_rules):
        records = [_record(model_id=5, name="m", tier_facts=QUICK_FACTS)]
        selection = route_model_selection(records, "请分析鉴别诊断思路")
        # No deep model: quick candidates cannot serve deep tier and deep
        # has no relaxation target -> None (keep existing selection).
        assert selection is None

    def test_quick_to_long_relaxation_audited(self, medical_rules):
        records = [_record(model_id=5, name="m", tier_facts=LONG_FACTS)]
        selection = route_model_selection(records, "你好")
        assert selection is not None
        _, decision = selection
        assert decision.tier is RouteTier.QUICK_QA
        assert decision.fallback_from is RouteTier.QUICK_QA
        assert "relax:quick_qa" in decision.matched_rules

    def test_does_not_mutate_input_records(self, medical_rules):
        records = [_record(model_id=7, name="m", tier_facts=QUICK_FACTS)]
        route_model_selection(records, "你好")
        assert "_routing_decision" not in records[0]


@pytest.mark.parametrize("tag,expected", [
    ("quality_check", RouteTier.QUICK_QA),
    ("mdt", RouteTier.DEEP_REASONING),
    ("summary", RouteTier.LONG_CONTEXT),
    ("quick_qa", RouteTier.QUICK_QA),
])
def test_task_tag_mapping(tag, expected, medical_rules):
    result = classify_run("内容", agent_meta={"task_tag": tag})
    assert result.tier is expected
