"""Focused tests for NL2AGENT startup seed policy."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.nl2agent_seed_service import (
    NL2AGENT_VERIFICATION_CONFIG,
    SeedDependencies,
    build_seed_defaults,
    ensure_builder_ready,
    ensure_seed_defaults,
    normalize_model_ids,
    seed_default_agent,
)
from database.db_models import AgentInfo


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


def test_seed_default_agent_repairs_bindings_on_existing_builder():
    dependencies = _dependencies(
        query_all_agents=MagicMock(return_value=[{"agent_id": 101, "name": "nl2agent"}])
    )

    agent_id = seed_default_agent(dependencies, "tenant_1", "user_1")

    assert agent_id == 101
    dependencies.create_agent.assert_not_called()
    assert [
        call.kwargs["tool_info"].tool_id
        for call in dependencies.bind_tool.call_args_list
    ] == [1, 2, 3]


def test_seed_default_agent_recovers_concurrent_builder_winner():
    dependencies = _dependencies(
        query_all_agents=MagicMock(
            side_effect=[[], [{"agent_id": 202, "name": "nl2agent"}]]
        ),
        create_agent=MagicMock(side_effect=RuntimeError("unique violation")),
    )

    assert seed_default_agent(dependencies, "tenant_1", "user_1") == 202
    assert dependencies.query_all_agents.call_count == 2
    assert dependencies.bind_tool.call_count == 3


def test_builder_uniqueness_matches_incremental_and_fresh_schema():
    index = next(
        item
        for item in AgentInfo.__table__.indexes
        if item.name == "uq_nl2agent_builder_tenant_active"
    )
    assert index.unique is True
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "deploy/sql/migrations/v2.4.0_0722_add_nl2agent.sql"
    ).read_text(encoding="utf-8")
    fresh_init = (root / "deploy/sql/init.sql").read_text(encoding="utf-8")
    for sql in (migration, fresh_init):
        assert "uq_nl2agent_builder_tenant_active" in sql
        assert "name = 'nl2agent'" in sql


def test_seed_default_agent_fails_when_any_required_binding_fails():
    dependencies = _dependencies(
        bind_tool=MagicMock(side_effect=[None, RuntimeError("binding failed")])
    )

    assert seed_default_agent(dependencies, "tenant_1", "user_1") is None
    assert dependencies.bind_tool.call_count == 2


def test_builder_readiness_propagates_partial_binding_failure():
    dependencies = _dependencies(
        bind_tool=MagicMock(side_effect=RuntimeError("binding failed"))
    )

    with pytest.raises(RuntimeError, match="binding failed"):
        ensure_builder_ready(
            dependencies,
            {"agent_id": 101, "name": "nl2agent"},
            "user_1",
            "tenant_1",
        )


def test_normalize_model_ids_preserves_order_and_deduplicates():
    assert normalize_model_ids(["7", 8, 7, "invalid"]) == [7, 8]
