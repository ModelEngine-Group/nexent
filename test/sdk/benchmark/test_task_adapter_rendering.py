import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from nexent.core.agents.context import ContextItemInput, ContextItemType

from sdk.benchmark.agent_runner import AgentRunResult
from sdk.benchmark.generic.runtime import task_adapter
from sdk.benchmark.generic.runtime.task_adapter import render_precompact_system_prompt


def test_render_precompact_system_prompt_includes_grouped_tool_descriptions():
    items = [
        ContextItemInput(
            id="system:available_resources_header",
            type=ContextItemType.SYSTEM,
            content={"text": "### Available Resources"},
            priority=55,
        ),
        ContextItemInput(
            id="tool:search",
            type=ContextItemType.TOOL,
            content={
                "name": "search",
                "description": "Search public information.",
                "inputs": '{"query": {"type": "string"}}',
                "output_type": "string",
                "source": "local",
            },
            priority=50,
            metadata={
                "render_group": "tools",
                "language": "en",
                "is_manager": False,
            },
        ),
    ]

    rendered = render_precompact_system_prompt(items)

    assert "### Available Resources" in rendered
    assert "search" in rendered
    assert "Search public information." in rendered
    assert "query" in rendered


def _agent_run_info():
    context_item = SimpleNamespace(
        id="system:test",
        type=SimpleNamespace(value="system"),
        content={"text": "system"},
        priority=100,
        source=("benchmark",),
        metadata={"stable": True},
    )
    context_manager_config = SimpleNamespace(
        soft_input_budget_tokens=100,
        hard_input_budget_tokens=200,
        token_threshold=80,
        policy_layers=SimpleNamespace(platform={"processing_mode": "adaptive_compact"}),
    )
    return SimpleNamespace(
        agent_config=SimpleNamespace(
            name="agent",
            max_steps=5,
            tools=[SimpleNamespace(class_name="SearchTool")],
            managed_agents=[SimpleNamespace(name="helper")],
            context_items=[context_item],
            context_manager_config=context_manager_config,
        ),
        model_config_list=[
            SimpleNamespace(
                model_name="model",
                url="https://model.invalid",
                temperature=0.1,
                max_tokens=512,
                model_factory="openai",
            )
        ],
    )


def _agent_result():
    result = AgentRunResult()
    result.final_answer = "answer"
    result.step_count = 2
    result.total_input_tokens = 80
    result.total_api_input_tokens = 70
    result.total_output_tokens = 10
    result.message_type_count = {"final_answer": 1}
    result.steps = [{"step_number": "final_answer", "main_output": "answer"}]
    result.compression_calls = 1
    result.deterministic_compaction_calls = 1
    result.compression_input_tokens = 10
    result.compression_output_tokens = 2
    result.summary_cache_hits = 1
    result.summary_cache_types = ["history"]
    result.total_uncompressed_est_tokens = 120
    result.provider_cache_available_calls = 2
    result.provider_cache_hit_calls = 1
    result.provider_cached_input_tokens = 40
    result.provider_uncached_input_tokens = 30
    result.provider_cache_statuses = {"available"}
    result.provider_cache_metrics_sources = {"usage"}
    result.wall_clock_seconds = 1.25
    result.step_durations = [0.5, 0.75]
    result.peak_context_tokens = 90
    result.peak_context_step = 2
    result.processing_mode = "adaptive_compact"
    result.max_raw_context_tokens = 120
    result.over_soft_budget = True
    result.net_token_saving = 38
    return result


@pytest.mark.parametrize(
    ("system_prompt", "item"),
    [
        ("", {"input": {"question": "plain question"}}),
        (
            "custom system",
            SimpleNamespace(
                input={"question": "file question", "file_name": "input.pdf"}
            ),
        ),
    ],
)
def test_make_nexent_task_maps_agent_run_to_benchmark_output(
    monkeypatch,
    system_prompt,
    item,
):
    run_info = _agent_run_info()
    builder_calls = []

    def fake_builder(**kwargs):
        builder_calls.append(kwargs)
        return run_info

    monkeypatch.setattr(task_adapter, "build_agent_run_info", fake_builder)
    monkeypatch.setattr(
        task_adapter,
        "build_agent_run_info_with_custom_prompt",
        fake_builder,
    )

    async def fake_run_agent_with_tracking(agent_run_info):
        assert agent_run_info is run_info
        return _agent_result()

    monkeypatch.setattr(
        task_adapter,
        "run_agent_with_tracking",
        fake_run_agent_with_tracking,
    )
    monkeypatch.setattr(
        task_adapter,
        "render_precompact_system_prompt",
        lambda context_items: "rendered system",
    )

    from sdk.benchmark.generic.provenance import parity_snapshot as parity_module
    from sdk.benchmark.generic.tools import web_evidence as web_evidence_module

    monkeypatch.setattr(
        parity_module,
        "build_agent_run_info_parity_snapshot",
        lambda *args, **kwargs: {"snapshot": "stable"},
    )
    try:
        legacy_parity_module = importlib.import_module("provenance.parity_snapshot")
    except ImportError:
        legacy_parity_module = None
    if legacy_parity_module is not None:
        monkeypatch.setattr(
            legacy_parity_module,
            "build_agent_run_info_parity_snapshot",
            lambda *args, **kwargs: {"snapshot": "stable"},
        )
    monkeypatch.setattr(
        web_evidence_module,
        "build_web_evidence",
        lambda *args, **kwargs: {"exa_search_calls": 1},
    )
    try:
        legacy_web_evidence_module = importlib.import_module("tools.web_evidence")
    except ImportError:
        legacy_web_evidence_module = None
    if legacy_web_evidence_module is not None:
        monkeypatch.setattr(
            legacy_web_evidence_module,
            "build_web_evidence",
            lambda *args, **kwargs: {"exa_search_calls": 1},
        )

    task = task_adapter.make_nexent_task(
        system_prompt=system_prompt,
        max_steps=5,
        user_id="benchmark-user",
        prompt_template_version="v1",
        resource_support={"file": True},
    )
    output = task(item=item)

    assert output["final_answer"] == "answer"
    assert output["system_prompt"] == "rendered system"
    assert output["parity_snapshot"] == {"snapshot": "stable"}
    assert output["provider_cache"]["status"] == "available"
    assert output["provider_cache"]["provider_prefix_hit_rate"] == 0.5
    assert output["budget_evidence"] == {
        "over_soft_budget": True,
        "over_hard_budget": False,
        "compression_triggered": True,
        "peak_context_tokens": 90,
        "peak_context_step": 2,
        "max_raw_context_tokens": 120,
        "processing_mode": "adaptive_compact",
        "soft_budget_tokens": 100,
        "hard_budget_tokens": 200,
        "total_input_tokens": 80,
        "total_uncompressed_est_tokens": 120,
    }
    assert output["agent_config"]["context_processing_mode"] == "adaptive_compact"
    assert output["agent_config"]["user_id"] == "benchmark-user"
    assert output["token_saving"]["net_token_saving"] == 38
    if system_prompt:
        assert "S3 URL: s3:/nexent/gaia/input.pdf" in builder_calls[0]["query"]
        assert builder_calls[0]["system_prompt"] == system_prompt
    else:
        assert builder_calls[0]["query"] == "plain question"


def test_make_nexent_task_returns_structured_error_for_missing_question():
    task = task_adapter.make_nexent_task()

    assert task(item={"input": {}}) == {
        "final_answer": "",
        "step_count": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "errors": ["No question found in input"],
    }


@pytest.mark.parametrize(
    ("available_calls", "statuses", "expected_status"),
    [
        (0, {"unavailable"}, "unavailable"),
        (0, set(), "unsupported"),
        (1, {"available"}, "available"),
    ],
)
def test_provider_cache_result_uses_only_provider_reported_status(
    available_calls,
    statuses,
    expected_status,
):
    result = _agent_result()
    result.provider_cache_available_calls = available_calls
    result.provider_cache_statuses = statuses

    provider_cache = task_adapter._provider_cache_result(result)

    assert provider_cache["status"] == expected_status
    assert provider_cache["provider_prefix_hit_rate"] == (
        1.0 if available_calls else None
    )


def test_run_evaluator_aggregates_metrics_and_token_statistics(monkeypatch):
    experiment_module = ModuleType("langfuse.experiment")

    class Evaluation:
        def __init__(self, name, value, comment=None):
            self.name = name
            self.value = value
            self.comment = comment

    experiment_module.Evaluation = Evaluation
    monkeypatch.setitem(sys.modules, "langfuse.experiment", experiment_module)

    aggregate = task_adapter.make_run_evaluators(["exact_match"])[0]
    item_results = [
        SimpleNamespace(
            evaluations=[SimpleNamespace(name="exact_match", value=1.0)],
            output={"total_input_tokens": 10, "total_output_tokens": 4, "step_count": 2},
        ),
        SimpleNamespace(
            evaluations=[
                SimpleNamespace(name="exact_match", value=0.0),
                SimpleNamespace(name="exact_match", value="ignored"),
            ],
            output={"total_input_tokens": 30, "total_output_tokens": 6, "step_count": 4},
        ),
    ]

    evaluations = aggregate(item_results=item_results)
    values = {evaluation.name: evaluation.value for evaluation in evaluations}

    assert values == {
        "avg_exact_match": 0.5,
        "avg_input_tokens": 20.0,
        "avg_output_tokens": 5.0,
        "avg_steps": 3.0,
    }
    assert aggregate(item_results=[]) == []
