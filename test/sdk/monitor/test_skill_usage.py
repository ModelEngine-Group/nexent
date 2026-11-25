# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.monitor import skill_usage


def context(**overrides):
    values = {
        "tenant_id": "tenant", "monitoring_run_id": "run", "monitoring_root_run_id": "root",
        "agent_id": 7, "monitoring_group_ids": (2, 1),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_for_skill_builds_stable_fact_from_agent_context(monkeypatch):
    sink = Mock()
    monkeypatch.setattr(skill_usage, "get_fact_sink", lambda: sink)
    monkeypatch.setattr(skill_usage, "get_agent_monitoring_context", lambda: context())

    observation = skill_usage.SkillUsageObservation.for_skill(53, "summarize", "guide_read")
    observation.trigger()

    sink.assert_called_once()
    payload = sink.call_args.args[0]
    assert payload["fact_kind"] == "skill"
    assert payload["skill_id"] == "53"
    assert payload["skill_name"] == "summarize"
    assert payload["trigger_kind"] == "guide_read"
    assert payload["root_run_id"] == "root"
    assert payload["initiator_group_ids"] == (2, 1)


@pytest.mark.parametrize("missing", [
    {"sink": None, "context": context()},
    {"sink": Mock(), "context": None},
    {"sink": Mock(), "context": context(tenant_id=None)},
    {"sink": Mock(), "context": context(monitoring_run_id=None)},
    {"sink": Mock(), "context": context(), "skill_id": None},
])
def test_for_skill_returns_noop_without_required_context(monkeypatch, missing):
    monkeypatch.setattr(skill_usage, "get_fact_sink", lambda: missing["sink"])
    monkeypatch.setattr(skill_usage, "get_agent_monitoring_context", lambda: missing["context"])
    observation = skill_usage.SkillUsageObservation.for_skill(missing.get("skill_id", 7), "summarize", "guide_read")
    observation.trigger()
    if missing["sink"] is not None:
        missing["sink"].assert_not_called()


def test_trigger_deduplicates_and_releases_fact_after_sink_failure(monkeypatch):
    sink = Mock(side_effect=[RuntimeError("offline"), None])
    monkeypatch.setattr(skill_usage, "get_fact_sink", lambda: sink)
    monkeypatch.setattr(skill_usage, "get_agent_monitoring_context", lambda: context())
    skill_usage._run_dedup_state.set(None)

    first = skill_usage.SkillUsageObservation.for_skill(53, "summarize", "script_started")
    first.trigger()
    first.trigger()
    second = skill_usage.SkillUsageObservation.for_skill(53, "summarize", "script_started")
    second.trigger()

    assert sink.call_count == 2


def test_trigger_is_idempotent_for_same_run_and_fact():
    sink = Mock()
    monkeypatch_context = context()
    observation = skill_usage.SkillUsageObservation({
        "fact_id": "fact", "agent_run_id": monkeypatch_context.monitoring_run_id,
    }, sink)
    observation.trigger()
    observation.trigger()
    assert sink.call_count == 1


def test_trigger_drops_duplicate_fact_and_evicts_oldest_when_cache_is_full(monkeypatch):
    sink = Mock()
    monkeypatch.setattr(skill_usage, "_MAX_SEEN_FACTS", 1)
    skill_usage._run_dedup_state.set(None)
    first = skill_usage.SkillUsageObservation({"fact_id": "first", "agent_run_id": "run"}, sink)
    duplicate = skill_usage.SkillUsageObservation({"fact_id": "first", "agent_run_id": "run"}, sink)
    second = skill_usage.SkillUsageObservation({"fact_id": "second", "agent_run_id": "run"}, sink)
    first.trigger()
    duplicate.trigger()
    second.trigger()
    assert sink.call_count == 2


def test_convenience_entry_point_delegates_to_observation(monkeypatch):
    observation = Mock()
    monkeypatch.setattr(skill_usage.SkillUsageObservation, "for_skill", Mock(return_value=observation))
    skill_usage.observe_skill_usage(53, "summarize", "script_started")
    skill_usage.SkillUsageObservation.for_skill.assert_called_once_with(53, "summarize", "script_started")
    observation.trigger.assert_called_once_with()
