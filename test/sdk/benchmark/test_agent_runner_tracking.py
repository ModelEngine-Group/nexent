import json
from types import SimpleNamespace

import pytest

from sdk.benchmark import agent_runner


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


def _context_item(item_id, text):
    return agent_runner.ContextItemInput(
        id=item_id,
        type="system",
        content={"text": text},
    )


@pytest.fixture
def configured_model(monkeypatch):
    monkeypatch.setattr(agent_runner, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(agent_runner, "LLM_MODEL_NAME", "test-model")
    monkeypatch.setattr(agent_runner, "LLM_API_URL", "https://model.invalid")


def test_build_agent_run_info_maps_prompts_model_and_context_components(monkeypatch):
    context_items = [
        _context_item("system:header", "default header"),
        _context_item("system:duty", "default duty"),
    ]
    captured_context = {}

    def fake_build_context_inputs(**kwargs):
        captured_context.update(kwargs)
        return context_items

    monkeypatch.setattr(
        agent_runner,
        "build_context_inputs",
        fake_build_context_inputs,
    )
    monkeypatch.setattr(
        agent_runner,
        "build_prompt_templates",
        lambda **kwargs: {"final_answer": "default"},
    )
    monkeypatch.setattr(agent_runner, "LLM_API_KEY", "key")
    monkeypatch.setattr(agent_runner, "LLM_MODEL_NAME", "model")
    monkeypatch.setattr(agent_runner, "LLM_API_URL", "https://model.invalid")
    tool = agent_runner.ToolConfig(
        class_name="SearchTool",
        name="search",
        description="search",
        inputs="{}",
        output_type="string",
    )

    run_info = agent_runner.build_agent_run_info(
        query="question",
        history=[],
        duty_prompt="duty",
        constraint_prompt="constraint",
        few_shots_prompt="few shots",
        tools=[tool],
        max_steps=7,
        temperature=0,
        language="en",
        user_id="benchmark-user",
        max_tokens=512,
        model_factory="openai",
        prompt_components={
            "basic_information": {"content": "custom header"},
            "duty_prompt": "custom duty",
            "final_answer_contract": {"content": {"suffix": "FINAL ANSWER"}},
        },
    )

    assert run_info.query == "question"
    assert run_info.model_config_list[0].model_name == "model"
    assert run_info.model_config_list[0].max_tokens == 512
    assert run_info.model_config_list[0].model_factory == "openai"
    assert run_info.agent_config.max_steps == 7
    assert run_info.agent_config.context_items[0].content == {
        "text": "custom header"
    }
    assert run_info.agent_config.context_items[1].content == {
        "text": "custom duty"
    }
    assert run_info.agent_config.prompt_templates["final_answer"] == {
        "suffix": "FINAL ANSWER"
    }
    assert captured_context["tools"] == {"search": tool}


def test_build_agent_run_info_uses_fallback_context_when_segments_are_empty(
    monkeypatch,
    configured_model,
):
    monkeypatch.setattr(
        agent_runner,
        "build_context_inputs",
        lambda **kwargs: [_context_item("system:header", "default")],
    )
    monkeypatch.setattr(
        agent_runner,
        "build_prompt_templates",
        lambda **kwargs: {},
    )

    run_info = agent_runner.build_agent_run_info(
        query="question",
        history=[],
        fallback_prompt="complete custom prompt",
    )

    assert len(run_info.agent_config.context_items) == 1
    assert run_info.agent_config.context_items[0].id == "system:fallback"
    assert run_info.agent_config.context_items[0].content == {
        "text": "complete custom prompt"
    }


def test_build_agent_run_info_with_custom_prompt_uses_single_context_item(
    monkeypatch,
    configured_model,
):
    monkeypatch.setattr(
        agent_runner,
        "build_prompt_templates",
        lambda **kwargs: {"final_answer": "default"},
    )

    run_info = agent_runner.build_agent_run_info_with_custom_prompt(
        query="question",
        system_prompt="custom system",
        history=[],
        max_steps=4,
        model_factory="openai",
    )

    assert run_info.agent_config.max_steps == 4
    assert run_info.agent_config.context_items[0].id == "system:custom"
    assert run_info.agent_config.context_items[0].content == {
        "text": "custom system"
    }
    assert run_info.model_config_list[0].model_factory == "openai"


def test_build_tools_from_yaml_filters_disabled_and_unsupported_tools(
    monkeypatch,
    capsys,
):
    metadata = {"llm_model": object()}
    monkeypatch.setattr(
        agent_runner,
        "_build_analyze_tool_metadata",
        lambda class_name: metadata,
    )
    tools = agent_runner.build_tools_from_yaml(
        [
            {
                "tool_class": "SearchTool",
                "tool_name": "search",
                "tool_description": "search",
                "tool_inputs": "{}",
                "tool_output_type": "string",
                "tool_params": {"limit": 3},
            },
            {
                "tool_class": "AnalyzeTextFileTool",
                "tool_name": "analyze",
                "tool_inputs": "{}",
            },
            {
                "tool_class": "StoreMemoryTool",
                "tool_name": "memory",
            },
            {
                "tool_class": "DisabledTool",
                "tool_name": "disabled",
                "enabled": False,
            },
        ]
    )

    assert [tool.name for tool in tools] == ["search", "analyze"]
    assert tools[0].params == {"limit": 3}
    assert tools[1].metadata == metadata
    assert "Skipped 1 tools" in capsys.readouterr().out


def test_analyze_tool_metadata_selects_text_or_vlm_dependencies(monkeypatch):
    storage = object()
    llm = object()
    vlm = object()
    monkeypatch.setattr(agent_runner, "_build_storage_client", lambda: storage)
    monkeypatch.setattr(agent_runner, "_build_llm_model", lambda: llm)
    monkeypatch.setattr(agent_runner, "_build_vlm_model", lambda: vlm)
    monkeypatch.setenv("DATA_PROCESS_SERVICE", "http://data-process")

    assert agent_runner._build_analyze_tool_metadata("AnalyzeTextFileTool") == {
        "storage_client": storage,
        "llm_model": llm,
        "data_process_service_url": "http://data-process",
    }
    assert agent_runner._build_analyze_tool_metadata("AnalyzeImageTool") == {
        "storage_client": storage,
        "vlm_model": vlm,
    }


def test_optional_runtime_dependency_builders_return_none_without_configuration(
    monkeypatch,
):
    for name in (
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "VLM_API_URL",
        "VLM_API_KEY",
        "VLM_MODEL_NAME",
        "LLM_API_URL",
        "LLM_API_KEY",
        "LLM_MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    assert agent_runner._build_storage_client() is None
    assert agent_runner._build_vlm_model() is None
    assert agent_runner._build_llm_model() is None


def test_message_parsers_and_result_repr_handle_invalid_chunks():
    assert agent_runner.process_agent_message("plain text") == ("", "plain text")
    assert agent_runner._parse_agent_message("[]") == ("", "[]", {})
    assert agent_runner._parse_agent_message("plain text") == (
        "",
        "plain text",
        {},
    )
    result = agent_runner.AgentRunResult()
    result.final_answer = "answer"
    result.step_count = 2
    assert "final_answer_len=6" in repr(result)
