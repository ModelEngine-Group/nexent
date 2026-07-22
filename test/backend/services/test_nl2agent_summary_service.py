"""Unit tests for pure NL2AGENT model and resource projections."""

import pytest

from consts.exceptions import AgentRunException, Nl2AgentValidationError
from services.nl2agent_summary_service import (
    raise_for_invalid_resource_references,
    resolve_model_summaries,
    resolve_online_resource_provenance,
    resolve_resource_summaries,
    validate_available_llm_ids,
)


def test_validate_available_llm_ids_returns_display_ready_records():
    records = [
        {
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "available",
            "model_name": "Primary",
        }
    ]

    assert validate_available_llm_ids(records, [7]) == {
        7: {**records[0], "display_name": "Primary"}
    }


def test_validate_available_llm_ids_explains_finalize_recovery():
    records = [
        {
            "model_id": 7,
            "model_type": "llm",
            "connect_status": "unavailable",
            "display_name": "Primary",
        }
    ]

    with pytest.raises(
        Nl2AgentValidationError, match="Reopen the model-selection card"
    ):
        validate_available_llm_ids(records, [7], finalizing=True)


def test_resolve_model_summaries_reports_primary_runtime_mismatch():
    summaries, invalid = resolve_model_summaries(
        {"business_logic_model_id": 7, "model_ids": [8]},
        [
            {
                "model_id": model_id,
                "model_type": "llm",
                "connect_status": "available",
                "display_name": f"Model {model_id}",
            }
            for model_id in (7, 8)
        ],
    )

    assert [item["model_id"] for item in summaries] == [7, 8]
    assert invalid == [
        {
            "reference_type": "model",
            "reference_id": 7,
            "reason": "primary_not_in_runtime_models",
        }
    ]


def test_resolve_resource_summaries_preserves_origin_and_reports_dangling_ids():
    tools, skills, invalid = resolve_resource_summaries(
        [{"tool_id": 1}, {"tool_id": 2}],
        [{"skill_id": 3}],
        [{"tool_id": 1, "origin_name": "Remote Search", "source": "mcp"}],
        [{"skill_id": 3, "name": "Writer", "source": "official"}],
        online_tool_ids={1},
        online_skill_ids={3},
    )

    assert tools == [
        {
            "tool_id": 1,
            "name": "Remote Search",
            "source": "mcp",
            "origin": "online",
            "parameter_schema": [],
            "configuration": {},
        }
    ]
    assert skills == [
        {
            "skill_id": 3,
            "name": "Writer",
            "source": "official",
            "origin": "online",
        }
    ]
    assert invalid == [
        {"reference_type": "tool", "reference_id": 2, "reason": "not_found"}
    ]


def test_resource_origin_uses_workflow_provenance_instead_of_source_labels():
    tools, skills, invalid = resolve_resource_summaries(
        [{"tool_id": 1}, {"tool_id": 2}],
        [{"skill_id": 3}, {"skill_id": 4}],
        [
            {"tool_id": 1, "name": "Installed MCP", "source": "custom"},
            {"tool_id": 2, "name": "Existing MCP", "source": "mcp"},
        ],
        [
            {"skill_id": 3, "name": "在线技能", "source": "官方"},
            {"skill_id": 4, "name": "Local Official", "source": "official"},
        ],
        online_tool_ids={1},
        online_skill_names={"在线技能"},
    )

    assert invalid == []
    assert [item["origin"] for item in tools] == ["online", "local"]
    assert [item["origin"] for item in skills] == ["online", "local"]


def test_resolve_online_resource_provenance_uses_bound_tenant_resources():
    tool_ids, skill_ids, skill_names = resolve_online_resource_provenance(
        {
            "mcp_workflows": {
                "mcp": {"status": "tools_bound", "bound_tool_ids": [10, 11]},
                "skipped": {"status": "binding_skipped", "bound_tool_ids": [12]},
            },
            "online_installations": {
                "skill": {
                    "status": "completed",
                    "result": {
                        "skill_id": 20,
                        "installed_ids": [21],
                        "installed_names": ["Writer"],
                        "_source_skill_id": 999,
                    },
                }
            },
        }
    )

    assert tool_ids == {10, 11}
    assert skill_ids == {20, 21}
    assert skill_names == {"writer"}


def test_resolve_resource_summaries_redacts_persisted_tool_secrets():
    tools, _, invalid = resolve_resource_summaries(
        [
            {
                "tool_id": 1,
                "params": {"api_key": "never-return-this", "limit": 25},
                "tenant_id": "tenant_1",
            }
        ],
        [],
        [
            {
                "tool_id": 1,
                "origin_name": "Local Search",
                "source": "local",
                "params": [
                    {"name": "api_key", "isSecret": True, "default": "unsafe"},
                    {"name": "limit", "type": "integer", "default": 10},
                ],
            }
        ],
        [],
    )

    assert invalid == []
    assert tools == [
        {
            "tool_id": 1,
            "name": "Local Search",
            "source": "local",
            "origin": "local",
            "parameter_schema": [
                {"name": "api_key", "isSecret": True, "default": None},
                {"name": "limit", "type": "integer", "default": 10},
            ],
            "configuration": {
                "api_key": {"value": None, "configured": True, "secret": True},
                "limit": {"value": 25, "configured": True, "secret": False},
            },
        }
    ]
    assert "never-return-this" not in str(tools)
    assert "tenant_1" not in str(tools)


def test_invalid_resource_references_block_publication():
    with pytest.raises(AgentRunException, match=r"tool 2 \(not_found\)"):
        raise_for_invalid_resource_references(
            [{"reference_type": "tool", "reference_id": 2, "reason": "not_found"}]
        )
