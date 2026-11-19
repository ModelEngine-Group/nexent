# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent usage reads only attributed model publications with model Token semantics."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from ops.monitoring import agent_tokens
from ops.monitoring.model import ModelFact, accumulate_model


DAY = date(2026, 11, 19)
PREVIOUS = DAY - timedelta(days=1)
MIDNIGHT = datetime.combine(PREVIOUS, datetime.min.time(), timezone.utc)


def model_day(agent_id, run_id, day, usage=None, tenant="a"):
    fact = ModelFact.model_validate({
        "tenant_id": tenant, "fact_id": f"{agent_id}-{day}-{run_id}", "call_context_id": "request",
        "model_id": 7, "model_type": "llm", "agent_id": agent_id, "agent_run_id": run_id,
        "started_at": datetime.combine(day, datetime.min.time(), timezone.utc),
        "record_revision": 2, "outcome": "succeeded", **(usage or {}),
    }).document(ZoneInfo("UTC"))
    (_, row), = accumulate_model([fact])
    return row


@pytest.fixture
def publication(monkeypatch):
    rows = [
        model_day(21, "root", PREVIOUS, dict(input_tokens=10, output_tokens=2, total_tokens=12)),
        model_day(21, "root", DAY, dict(input_tokens=20, output_tokens=3, total_tokens=23)),
        model_day(22, "child", PREVIOUS, dict(input_tokens=100, output_tokens=0, total_tokens=100)),
        model_day(22, "child-missing", DAY),
        model_day(24, "token-only", DAY, dict(input_tokens=0, output_tokens=0, total_tokens=0)),
        model_day(None, "orphan", DAY, dict(total_tokens=999)),
        model_day(21, None, DAY, dict(total_tokens=999)),
    ]
    states = [{"tenant_id": "a", "statistic_date": day, "publish_id": "published",
               "source_revision": 3, "published_source_revision": 3, "source_snapshot_at": MIDNIGHT}
              for day in (PREVIOUS, DAY)]
    store = Mock()
    store.coverage_starts.return_value = {"a": MIDNIGHT}
    store.has_failed_batches.return_value = False
    service = SimpleNamespace(store=store, zone=ZoneInfo("UTC"))
    reader = Mock(side_effect=lambda *_, **__: (rows, states, [state for state in states if state["publish_id"]]))
    monkeypatch.setattr(agent_tokens, "_read_published_rows", reader)
    return service, rows, states, reader


def read(publication):
    return agent_tokens.read_agent_tokens(publication[0], tenant="a", start=PREVIOUS, end=DAY,
                                          groups=[12, 13], agent_id=None,
                                          identities={("a", 21), ("a", 22), ("a", 23)})


def test_parent_child_totals_count_only_actual_model_request_owners(publication):
    result = read(publication)
    assert result.tokens["total_tokens"] == {
        "value": "135", "known_count": 4, "eligible_count": 5, "coverage_rate": 0.8,
    }
    assert result.tokens["input_tokens"]["value"] == "130" and result.tokens["output_tokens"]["value"] == "5"
    assert result.agents["a", 21]["tokens"]["total_tokens"]["value"] == "35"
    assert result.agents["a", 22]["tokens"]["total_tokens"] == {
        "value": "100", "known_count": 1, "eligible_count": 2, "coverage_rate": 0.5,
    }
    assert result.agents["a", 22]["tokens"]["output_tokens"]["value"] == "0"
    assert result.agents["a", 23]["tokens"]["total_tokens"]["value"] == "0"
    assert result.agents["a", 24]["tokens"]["total_tokens"]["known_count"] == 1
    assert result.days[PREVIOUS]["tokens"]["total_tokens"]["value"] == "112"
    assert result.days[DAY]["tokens"]["total_tokens"]["value"] == "23"
    publication[3].assert_called_once_with(
        publication[0], tenant="a", kind="model", start=PREVIOUS, end=DAY,
        initiator_group_ids=[12, 13], agent_id=None, has_agent_run=True,
    )


@pytest.mark.parametrize("failed,dirty", [(True, False), (False, True), (False, False)])
def test_token_status_uses_model_publications_and_failed_batches(publication, failed, dirty):
    service, _, states, _ = publication
    service.store.has_failed_batches.return_value = failed
    states[1]["source_revision"] = 4 if dirty else 3
    result = read(publication)
    assert result.status == {"data_as_of": MIDNIGHT, "coverage_state": "covered", "is_stale": failed or dirty}
    assert result.days[DAY]["token_status"]["is_stale"] == (failed or dirty)
    service.store.coverage_starts.assert_called_once_with({"a"}, "model")
    service.store.has_failed_batches.assert_called_once_with("a", "model", PREVIOUS, DAY)


def test_uncovered_days_are_unknown_and_covered_zero_stays_zero(publication):
    _, rows, states, _ = publication
    rows.clear()
    states[1].update(publish_id=None, published_source_revision=None, source_snapshot_at=None)
    result = read(publication)
    assert result.status["coverage_state"] == "partial" and result.status["is_stale"]
    assert result.tokens == dict.fromkeys(("input_tokens", "output_tokens", "total_tokens"))
    assert result.days[DAY]["tokens"]["total_tokens"] is None
    assert result.days[PREVIOUS]["tokens"]["total_tokens"] == {
        "value": "0", "known_count": 0, "eligible_count": 0, "coverage_rate": None,
    }


def test_all_missing_usage_and_exact_large_counts_reuse_model_semantics(publication):
    _, rows, _, _ = publication
    rows[:] = [model_day(21, "unknown", DAY)]
    assert read(publication).tokens["total_tokens"] == {
        "value": None, "known_count": 0, "eligible_count": 1, "coverage_rate": 0,
    }
    rows[:] = [model_day(21, "large", DAY, dict(total_tokens=2**53 + 9)),
               model_day(21, "more", DAY, dict(total_tokens=2))]
    assert read(publication).tokens["total_tokens"]["value"] == str(2**53 + 11)
    rows[:] = [model_day(21, "partial-fields", DAY, dict(input_tokens=5, output_tokens=0))]
    result = read(publication)
    assert result.tokens["input_tokens"]["value"] == "5" and result.tokens["output_tokens"]["value"] == "0"
    assert result.tokens["total_tokens"]["value"] is None
    assert result.tokens["total_tokens"]["known_count"] == 0


def test_global_queries_keep_same_agent_id_in_separate_tenants(publication):
    service, rows, states, _ = publication
    rows.append(model_day(21, "peer", DAY, dict(total_tokens=7), tenant="b"))
    service.store.coverage_starts.return_value = {"a": MIDNIGHT, "b": MIDNIGHT}
    states.extend({**state, "tenant_id": "b"} for state in list(states))
    result = agent_tokens.read_agent_tokens(service, tenant=None, start=PREVIOUS, end=DAY,
                                            groups=[], agent_id=21, identities={("a", 21), ("b", 21)})
    assert result.agents["a", 21]["tokens"]["total_tokens"]["value"] == "35"
    assert result.agents["b", 21]["tokens"]["total_tokens"]["value"] == "7"
    assert result.status["coverage_state"] == "covered"


def test_global_current_tenant_without_model_coverage_remains_unknown(publication):
    result = agent_tokens.read_agent_tokens(publication[0], tenant=None, start=PREVIOUS, end=DAY,
                                            groups=[], agent_id=None, identities={("a", 21), ("b", 21)})
    assert result.status["coverage_state"] == "partial"
    assert result.agents["b", 21]["tokens"]["total_tokens"] is None
    assert result.agents["b", 21]["token_status"]["coverage_state"] == "uncovered"
    assert result.agents["a", 21]["token_status"]["coverage_state"] == "covered"
