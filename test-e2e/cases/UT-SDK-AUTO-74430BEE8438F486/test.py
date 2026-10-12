"""W2 context-budget contract rename + dispatch boundary (SDK-UT, D1).

Covers the V2 ``context_budget_snapshot`` field rename from the legacy
``safe_input_budget_snapshot`` across serialization, parse validation, and the
trusted provider dispatch boundary. Pure in-memory tests; no network, no real
model, no production credentials.
"""
from __future__ import annotations

import inspect
import threading
from unittest.mock import MagicMock

import pytest

from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ModelConfig
from nexent.core.models.capacity_budget import (
    CONTEXT_BUDGET_RESOLVER_VERSION,
    CallerMaxTokensOverrideForbidden,
    ContextBudgetCapacityMismatch,
    ContextBudgetSnapshot,
    compute_context_budget_fingerprint,
    parse_context_budget_snapshot,
)
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver


def _snapshot_dict(**overrides):
    """Build a self-consistent V2 ContextBudgetSnapshot payload dict."""
    payload = {
        "w1_fingerprint": "w1-fp-0001",
        "provider": "openai",
        "model_name": "gpt-4o-mini",
        "requested_output_tokens": 1024,
        "output_reserve_source": "model_default",
        "effective_input_limit_tokens": 60000,
        "uncertainty_reserve_tokens": 0,
        "uncertainty_reserve_basis": "none",
        "approved_profile_reserve_tokens": None,
        "compaction_trigger_ratio": 0.8,
        "compaction_trigger_ratio_source": "code_default",
        "compaction_trigger_threshold_tokens": 48000,
        "compaction_target_ratio": 0.6,
        "compaction_target_ratio_source": "code_default",
        "compaction_target_tokens": 36000,
        "field_sources": {},
        "warnings": [],
    }
    payload.update(overrides)
    fingerprint = compute_context_budget_fingerprint(
        resolver_version=CONTEXT_BUDGET_RESOLVER_VERSION,
        w1_fingerprint=payload["w1_fingerprint"],
        provider=payload["provider"],
        model_name=payload["model_name"],
        requested_output_tokens=payload["requested_output_tokens"],
        output_reserve_source=payload["output_reserve_source"],
        uncertainty_reserve_tokens=payload["uncertainty_reserve_tokens"],
        uncertainty_reserve_basis=payload["uncertainty_reserve_basis"],
        approved_profile_reserve_tokens=payload["approved_profile_reserve_tokens"],
        effective_input_limit_tokens=payload["effective_input_limit_tokens"],
        compaction_trigger_ratio=payload["compaction_trigger_ratio"],
        compaction_trigger_ratio_source=payload["compaction_trigger_ratio_source"],
        compaction_trigger_threshold_tokens=payload["compaction_trigger_threshold_tokens"],
        compaction_target_ratio=payload["compaction_target_ratio"],
        compaction_target_ratio_source=payload["compaction_target_ratio_source"],
        compaction_target_tokens=payload["compaction_target_tokens"],
        field_sources=payload["field_sources"],
        warnings=payload["warnings"],
    )
    data = dict(payload)
    data["fingerprint"] = fingerprint
    return data


def _bare_model():
    """Construct an OpenAIModel instance without running the full client init."""
    model = OpenAIModel.__new__(OpenAIModel)
    model.client = MagicMock()
    model.model_id = "gpt-4o-mini"
    model.capacity_snapshot = None
    return model


def _make_agent_config(snapshot):
    return AgentConfig(
        name="test-agent",
        description="test description",
        tools=[],
        model_name="gpt-4o-mini",
        context_budget_snapshot=snapshot,
    )


def _make_run_info(snapshot):
    return AgentRunInfo(
        query="hello",
        model_config_list=[
            ModelConfig(
                cite_name="primary",
                model_name="gpt-4o-mini",
                url="http://localhost:8080/v1",
            )
        ],
        observer=MessageObserver(),
        agent_config=_make_agent_config(snapshot),
        stop_event=threading.Event(),
        context_budget_snapshot=snapshot,
    )


@pytest.mark.case_id("UT-SDK-AUTO-74430BEE8438F486")
@pytest.mark.stage("D1")
def test_w2_context_budget_snapshot_rename_and_dispatch_boundary():
    snapshot_dict = _snapshot_dict()
    parsed = parse_context_budget_snapshot(snapshot_dict)
    assert isinstance(parsed, ContextBudgetSnapshot)
    assert parsed.effective_input_limit_tokens == 60000
    assert parsed.compaction_trigger_threshold_tokens == 48000
    assert parsed.compaction_target_tokens == 36000
    assert parsed.fingerprint == snapshot_dict["fingerprint"]

    assert {
        "effective_input_limit_tokens",
        "compaction_trigger_threshold_tokens",
        "compaction_target_tokens",
    } <= set(ContextBudgetSnapshot.model_fields)
    for legacy in (
        "soft_budget",
        "hard_budget",
        "soft_input_budget_tokens",
        "hard_input_budget_tokens",
        "soft_limit_ratio",
    ):
        assert legacy not in ContextBudgetSnapshot.model_fields

    agent_config = _make_agent_config(snapshot_dict)
    dumped_config = agent_config.model_dump()
    assert "context_budget_snapshot" in dumped_config
    assert "safe_input_budget_snapshot" not in dumped_config
    assert "safe_input_budget_snapshot" not in AgentConfig.model_fields
    dumped_snapshot = dumped_config["context_budget_snapshot"]
    assert isinstance(dumped_snapshot, dict)
    assert dumped_snapshot["fingerprint"] == snapshot_dict["fingerprint"]
    assert dumped_snapshot["effective_input_limit_tokens"] == 60000
    assert "soft_input_budget_tokens" not in dumped_snapshot

    run_info = _make_run_info(snapshot_dict)
    dumped_run = run_info.model_dump()
    assert "context_budget_snapshot" in dumped_run
    assert "safe_input_budget_snapshot" not in dumped_run
    for process_local in (
        "cancellation_scope",
        "thread_manager",
        "thread_execution_id",
        "thread_future",
    ):
        assert process_local not in dumped_run
    assert dumped_run["context_budget_snapshot"]["fingerprint"] == snapshot_dict["fingerprint"]

    assert "context_budget_snapshot" in inspect.signature(OpenAIModel.__init__).parameters
    assert "safe_input_budget_snapshot" not in inspect.signature(OpenAIModel.__init__).parameters

    model = _bare_model()
    model.context_budget_snapshot = snapshot_dict
    assert isinstance(model.context_budget_snapshot, ContextBudgetSnapshot)
    assert model.context_budget_snapshot.requested_output_tokens == 1024
    second = _snapshot_dict(requested_output_tokens=4096)
    model.context_budget_snapshot = second
    assert model.context_budget_snapshot.requested_output_tokens == 4096

    with pytest.raises(TypeError):
        OpenAIModel._coerce_context_budget_snapshot("not-a-snapshot")
    with pytest.raises(TypeError):
        OpenAIModel._coerce_context_budget_snapshot(12345)

    dispatch_snapshot = _snapshot_dict(requested_output_tokens=2048)

    model = _bare_model()
    with pytest.raises(CallerMaxTokensOverrideForbidden) as exc_info:
        model._dispatch_chat_completion(
            context_budget_snapshot=dispatch_snapshot,
            max_tokens=100,
        )
    assert exc_info.value.snapshot_value == 2048
    assert exc_info.value.caller_value == 100

    model = _bare_model()
    model._dispatch_chat_completion(context_budget_snapshot=dispatch_snapshot)
    create_kwargs = model.client.chat.completions.create.call_args.kwargs
    assert create_kwargs["max_tokens"] == 2048

    model = _bare_model()
    model._dispatch_chat_completion(
        context_budget_snapshot=dispatch_snapshot,
        max_tokens=2048,
    )
    assert model.client.chat.completions.create.call_args.kwargs["max_tokens"] == 2048

    mismatch_snapshot = _snapshot_dict(
        w1_fingerprint="w1-fp-A",
        provider="openai",
        model_name="gpt-4o-mini",
    )
    model = _bare_model()
    with pytest.raises(ContextBudgetCapacityMismatch) as exc_info:
        model._dispatch_chat_completion(
            context_budget_snapshot=mismatch_snapshot,
            capacity_snapshot={
                "capacity_fingerprint": "w1-fp-B",
                "provider": "openai",
                "model_name": "gpt-4o-mini",
            },
        )
    assert exc_info.value.field == "w1_fingerprint"
    assert exc_info.value.expected == "w1-fp-B"
    assert exc_info.value.actual == "w1-fp-A"

    model = _bare_model()
    with pytest.raises(ContextBudgetCapacityMismatch) as exc_info:
        model._dispatch_chat_completion(
            context_budget_snapshot=mismatch_snapshot,
            capacity_snapshot={
                "capacity_fingerprint": "w1-fp-A",
                "provider": "anthropic",
                "model_name": "gpt-4o-mini",
            },
        )
    assert exc_info.value.field == "provider"

    model = _bare_model()
    with pytest.raises(ContextBudgetCapacityMismatch) as exc_info:
        model._dispatch_chat_completion(
            context_budget_snapshot=mismatch_snapshot,
            capacity_snapshot={
                "capacity_fingerprint": "w1-fp-A",
                "provider": "openai",
                "model_name": "gpt-4o",
            },
        )
    assert exc_info.value.field == "model_name"

    model = _bare_model()
    model._dispatch_chat_completion(
        context_budget_snapshot=mismatch_snapshot,
        capacity_snapshot={},
    )
    model = _bare_model()
    model._dispatch_chat_completion(
        context_budget_snapshot=mismatch_snapshot,
        capacity_snapshot={"unrelated": "value"},
    )
    model = _bare_model()
    model._dispatch_chat_completion(context_budget_snapshot=mismatch_snapshot)

    trace_snapshot = _snapshot_dict()
    attrs = OpenAIModel._context_budget_trace_attributes(trace_snapshot)
    assert attrs["w2.budget_fingerprint"] == trace_snapshot["fingerprint"]
    assert attrs["w2.w1_fingerprint"] == trace_snapshot["w1_fingerprint"]
    assert attrs["context.effective_input_limit_tokens"] == trace_snapshot["effective_input_limit_tokens"]
    assert attrs["context.compaction_trigger_threshold_tokens"] == trace_snapshot["compaction_trigger_threshold_tokens"]
    assert attrs["context.compaction_target_tokens"] == trace_snapshot["compaction_target_tokens"]
    assert attrs["w2.requested_output_tokens"] == trace_snapshot["requested_output_tokens"]
    assert OpenAIModel._context_budget_trace_attributes(None) == {}
