"""Focused tests for NL2AGENT startup seed policy."""

from unittest.mock import MagicMock

from services.nl2agent_seed_service import (
    NL2AGENT_VERIFICATION_CONFIG,
    SeedDependencies,
    build_seed_defaults,
    ensure_seed_defaults,
    normalize_model_ids,
    seed_default_agent,
)


def _dependencies(**overrides):
    values = {
        "get_seed_config": MagicMock(
            return_value={
                "agent_info": {"display_name": "Builder"},
                "prompt_segments": {"duty_prompt": "Build agents"},
            }
        ),
        "get_model_records": MagicMock(
            return_value=[
                {
                    "model_id": 7,
                    "model_type": "llm",
                    "connect_status": "available",
                },
                {
                    "model_id": 8,
                    "model_type": "embedding",
                    "connect_status": "available",
                },
            ]
        ),
        "update_agent": MagicMock(),
        "seed_builtin_tools": MagicMock(return_value=[1, 2, 3]),
        "query_all_agents": MagicMock(return_value=[]),
        "create_agent": MagicMock(return_value={"agent_id": 101}),
        "bind_tool": MagicMock(),
        "agent_name": "nl2agent",
        "language": "en",
    }
    values.update(overrides)
    return SeedDependencies(**values)


def test_build_seed_defaults_filters_models_and_uses_config_fields():
    defaults = build_seed_defaults(_dependencies(), "tenant_1")

    assert defaults["name"] == "nl2agent"
    assert defaults["display_name"] == "Builder"
    assert defaults["duty_prompt"] == "Build agents"
    assert defaults["model_ids"] == [7]
    assert defaults["business_logic_model_id"] == 7
    assert defaults["verification_config"] == NL2AGENT_VERIFICATION_CONFIG


def test_ensure_seed_defaults_updates_only_when_agent_drifted():
    dependencies = _dependencies()

    ensure_seed_defaults(
        dependencies,
        {"agent_id": 101, "name": "legacy", "model_ids": []},
        "user_1",
        "tenant_1",
    )

    request = dependencies.update_agent.call_args.kwargs["agent_info"]
    assert request.name == "nl2agent"
    assert request.model_ids == [7]


def test_seed_default_agent_creates_builder_and_binds_builtin_tools():
    dependencies = _dependencies()

    agent_id = seed_default_agent(dependencies, "tenant_1", "user_1")

    assert agent_id == 101
    assert dependencies.bind_tool.call_count == 3
    assert [
        call.kwargs["tool_info"].tool_id
        for call in dependencies.bind_tool.call_args_list
    ] == [1, 2, 3]


def test_normalize_model_ids_preserves_order_and_deduplicates():
    assert normalize_model_ids(["7", 8, 7, "invalid"]) == [7, 8]
