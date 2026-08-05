import json
from types import SimpleNamespace

import pytest

from sdk.benchmark import agent_runner


def test_resolve_app_description_uses_language_specific_production_defaults(monkeypatch):
    monkeypatch.setattr(agent_runner, "APP_DESCRIPTION", None)

    assert agent_runner.resolve_app_description("zh") == "Nexent 是一个开源智能体SDK和平台"
    assert agent_runner.resolve_app_description("en") == "Nexent is an open-source agent SDK and platform"


def test_resolve_app_description_preserves_explicit_override(monkeypatch):
    monkeypatch.setattr(agent_runner, "APP_DESCRIPTION", "Tenant-specific description")

    assert agent_runner.resolve_app_description("zh") == "Tenant-specific description"
    assert agent_runner.resolve_app_description("en") == "Tenant-specific description"


@pytest.mark.asyncio
async def test_run_agent_with_tracking_builds_model_step_and_metrics(monkeypatch):
    async def fake_agent_run(_):
        messages = [
            ("step_count", "1"),
            ("model_output_thinking", "reason"),
            ("model_output", "answer draft"),
            ("model_output_code", "print('x')"),
            ("parse", "python_interpreter"),
            ("execution_logs", "x"),
            ("error", "tool failed"),
            (
                "token_count",
                json.dumps({
                    "estimated_context_tokens": 120,
                    "uncompressed_est_tokens": 180,
                    "context_processing_mode": "adaptive_compact",
                    "token_threshold": 150,
                    "hard_input_budget_tokens": 200,
                    "step_input_tokens": 100,
                    "step_output_tokens": 20,
                    "compression_calls": 1,
                    "compression_input_tokens": 40,
                    "compression_output_tokens": 10,
                    "compression_cache_types": ["current_cache_hit"],
                    "provider_cache_status": "available",
                    "provider_cache_metrics_source": "usage",
                    "provider_cache_hit": True,
                    "provider_cached_input_tokens": 80,
                    "provider_uncached_input_tokens": 20,
                }),
            ),
            ("final_answer", "final"),
        ]
        for message_type, content in messages:
            yield json.dumps({"type": message_type, "content": content})

    monkeypatch.setattr(agent_runner, "agent_run", fake_agent_run)
    result = await agent_runner.run_agent_with_tracking(
        SimpleNamespace(query="question")
    )

    assert result.final_answer == "final"
    assert result.step_count == 1
    assert result.total_input_tokens == 120
    assert result.total_api_input_tokens == 100
    assert result.provider_cache_hit_calls == 1
    assert result.steps[0]["thinking"] == "reason"
    assert result.steps[0]["main_output"] == "answer draft"
    assert result.steps[0]["code"] == "print('x')"
    assert result.steps[0]["tool_call"] == "python_interpreter"
    assert result.steps[0]["observation"] == "x\nError:\ntool failed"
    assert result.errors == ["tool failed"]
    assert result.steps[0]["token_usage"]["output_tokens"] == 20
    assert result.steps[0]["compression"]["calls"] == 1
    assert result.processing_mode == "adaptive_compact"
    assert result.over_soft_budget is True
    assert result.over_hard_budget is False
    assert result.max_raw_context_tokens == 180
    assert result.net_token_saving == 10
    assert result.steps[1]["step_number"] == "final_answer"


@pytest.mark.asyncio
async def test_run_agent_with_tracking_preserves_web_observer_metadata(monkeypatch):
    async def fake_agent_run(_):
        yield json.dumps({"type": "step_count", "content": "1"})
        yield json.dumps({
            "type": "tool",
            "content": "",
            "tool_name": "exa_search",
            "tool_arguments": {"query": "GAIA"},
        })
        yield json.dumps({
            "type": "search_content",
            "content": '[{"url":"https://example.com"}]',
        })
        yield json.dumps({"type": "final_answer", "content": "FINAL ANSWER: x"})

    monkeypatch.setattr(agent_runner, "agent_run", fake_agent_run)
    result = await agent_runner.run_agent_with_tracking(
        SimpleNamespace(query="question")
    )

    assert result.steps[0]["web_events"] == [
        {
            "event_type": "tool_call",
            "tool_name": "exa_search",
            "tool_arguments": {"query": "GAIA"},
        },
        {
            "event_type": "search_content",
            "content": '[{"url":"https://example.com"}]',
        },
    ]


@pytest.mark.asyncio
async def test_passthrough_does_not_report_compression_savings(monkeypatch):
    async def fake_agent_run(_):
        yield json.dumps({"type": "step_count", "content": "1"})
        yield json.dumps({
            "type": "token_count",
            "content": json.dumps({
                "estimated_context_tokens": 100,
                "step_input_tokens": 90,
                "step_output_tokens": 10,
                "uncompressed_est_tokens": 180,
                "context_processing_mode": "passthrough",
                "token_threshold": 150,
                "hard_input_budget_tokens": 200,
            }),
        })
        yield json.dumps({"type": "final_answer", "content": "final"})

    monkeypatch.setattr(agent_runner, "agent_run", fake_agent_run)
    result = await agent_runner.run_agent_with_tracking(
        SimpleNamespace(query="question")
    )

    assert result.over_soft_budget is True
    assert result.net_token_saving == 0


@pytest.mark.asyncio
async def test_configured_soft_budget_and_deterministic_compaction_are_tracked(
    monkeypatch,
):
    async def fake_agent_run(_):
        yield json.dumps({"type": "step_count", "content": "1"})
        yield json.dumps({
            "type": "token_count",
            "content": json.dumps({
                "estimated_context_tokens": 14700,
                "step_input_tokens": 14650,
                "step_output_tokens": 10,
                "uncompressed_est_tokens": 18800,
                "context_processing_mode": "adaptive_compact",
                # The SDK stream historically exposed token_threshold=10000
                # even when an explicit soft budget was configured.
                "token_threshold": 10000,
                "hard_input_budget_tokens": 18404,
                "compression_calls": 0,
            }),
        })
        yield json.dumps({"type": "final_answer", "content": "FINAL ANSWER: Claus"})

    run_info = SimpleNamespace(
        query="question",
        agent_config=SimpleNamespace(
            context_manager_config=SimpleNamespace(
                processing_mode="adaptive_compact",
                token_threshold=10000,
                soft_input_budget_tokens=14723,
                hard_input_budget_tokens=18404,
            )
        ),
    )
    monkeypatch.setattr(agent_runner, "agent_run", fake_agent_run)
    result = await agent_runner.run_agent_with_tracking(run_info)

    assert result.soft_budget_tokens == 14723
    assert result.over_soft_budget is True
    assert result.deterministic_compaction_calls == 1
    assert result.net_token_saving == 4100


@pytest.mark.asyncio
async def test_adaptive_mode_without_compaction_does_not_report_savings(monkeypatch):
    async def fake_agent_run(_):
        yield json.dumps({"type": "step_count", "content": "1"})
        yield json.dumps({
            "type": "token_count",
            "content": json.dumps({
                "estimated_context_tokens": 13400,
                "step_input_tokens": 13300,
                "step_output_tokens": 10,
                "uncompressed_est_tokens": 13400,
                "context_processing_mode": "adaptive_compact",
                "soft_input_budget_tokens": 14723,
                "hard_input_budget_tokens": 18404,
                "compression_calls": 0,
            }),
        })
        yield json.dumps({"type": "final_answer", "content": "FINAL ANSWER: Claus"})

    monkeypatch.setattr(agent_runner, "agent_run", fake_agent_run)
    result = await agent_runner.run_agent_with_tracking(
        SimpleNamespace(query="question")
    )

    assert result.over_soft_budget is False
    assert result.deterministic_compaction_calls == 0
    assert result.net_token_saving == 0


@pytest.mark.asyncio
async def test_hard_budget_error_updates_budget_evidence(monkeypatch):
    async def fake_agent_run(_):
        yield json.dumps({"type": "step_count", "content": "1"})
        yield json.dumps({
            "type": "error",
            "content": (
                "Context input remains over the model hard budget after "
                "compaction: 13302 > 11000 tokens"
            ),
        })

    monkeypatch.setattr(agent_runner, "agent_run", fake_agent_run)
    result = await agent_runner.run_agent_with_tracking(
        SimpleNamespace(query="question")
    )

    assert result.over_hard_budget is True
    assert result.hard_budget_tokens == 11000
    assert result.peak_context_tokens == 13302
def test_builtin_skill_tools_are_passively_injected_with_runtime_scope():
    configured = SimpleNamespace(name="search")

    tools = agent_runner.inject_production_managed_tools(
        [configured],
        agent_id=8,
        tenant_id="tenant-a",
        version_no=2,
        local_skills_dir="/skills",
    )

    assert [tool.name for tool in tools] == [
        "search",
        "parallel_executor",
        "run_skill_script",
        "read_skill_md",
        "read_skill_config",
        "write_skill_file",
    ]
    injected = tools[2]
    assert injected.source == "builtin"
    assert injected.metadata["agent_id"] == 8
    assert injected.metadata["tenant_id"] == "tenant-a"
    assert injected.metadata["version_no"] == 2
    assert injected.params["local_skills_dir"] == "/skills"
