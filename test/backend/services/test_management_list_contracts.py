# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Business contracts across real Agent list projection and availability helpers."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from contracts.agent import AgentUnavailableReason as Reason
from management.services.agent import management, read, versions


def agent(number, **overrides):
    value = {
        "agent_id": number, "tenant_id": "a", "name": f"agent{number}", "display_name": f"Agent {number}",
        "description": "description", "enabled": True, "model_ids": [1], "group_ids": "7",
        "created_by": "owner", "create_time": datetime(2026, 1, 1) + timedelta(days=number),
        "current_version_no": 1, "ingroup_permission": "READ_ONLY",
    }
    value.update(overrides)
    return value


@pytest.fixture
def sources(mocker):
    agents = [
        agent(1, name="duplicate", display_name="Duplicate", model_ids=[1, 2], current_version_no=99),
        agent(2, name="duplicate", display_name="Duplicate"),
        agent(3, ingroup_permission="PRIVATE"),
        agent(4, enabled=False), agent(5, agent_origin="SYSTEM"), agent(6, group_ids="8"),
    ]
    for module in [management, versions]:
        mocker.patch.object(module, "query_all_agent_info_by_tenant_id", side_effect=lambda **kw: deepcopy(agents))
        mocker.patch.object(module, "query_group_ids_by_user", return_value=[7])
        mocker.patch.object(module, "enrich_cas_usernames")
    mocker.patch.object(management, "get_server_agent_ids", return_value={1})
    mocker.patch.object(management.TagManagementDB, "list_resource_assignment_display_values_by_ids", return_value={})
    mocker.patch.object(management, "query_version_labels", return_value={1: "Release three", 2: "Release one"})
    metadata = {a["agent_id"]: [{"version_no": 3, "version_name": "Release three"},
                               {"version_no": 1, "version_name": "Release one"}] for a in agents}
    batch_versions = mocker.patch.object(versions, "query_version_lists", return_value=metadata)
    batch_snapshots = mocker.patch.object(versions, "query_agent_snapshots", side_effect=lambda selected, tenant: {
        aid: (deepcopy(next(a for a in agents if a["agent_id"] == aid)), [], []) for aid in selected
    })
    mocker.patch.object(versions, "project_authorized_resource_tags", side_effect=lambda rows, **kw: [
        {**row, "tags": []} for row in rows
    ])
    batch_tools = mocker.patch.object(read, "query_agent_tools_for_list", return_value=([], {}))
    models = {
        1: {"model_id": 1, "tenant_id": "a", "delete_flag": "N", "model_type": "llm", "display_name": "LLM"},
        2: {"model_id": 2, "tenant_id": "a", "delete_flag": "Y", "model_type": "llm"},
    }
    batch_models = mocker.patch.object(read, "get_model_records_by_ids", side_effect=lambda ids: {
        mid: models[mid] for mid in ids if mid in models
    })
    return agents, batch_versions, batch_snapshots, batch_tools, batch_models


@pytest.mark.parametrize("role,expected_ids", [("ADMIN", [1, 2, 3, 6]), ("USER", [1, 2])])
def test_draft_list_visibility_deletion_duplicates_and_metadata(mocker, sources, role, expected_ids):
    mocker.patch.object(management, "get_user_tenant_by_user_id", return_value={"user_role": role})
    result = management._list_all_agent_info_sync("a", "reader")
    assert [row["agent_id"] for row in result] == expected_ids
    assert result[0]["model_ids"] == [1]
    assert result[0]["model_names"] == ["LLM"]
    assert result[0]["is_a2a_server"] is True
    assert result[0]["is_available"] is False
    assert result[0]["unavailable_reasons"] == [Reason.MODEL_DELETED]
    assert result[1]["unavailable_reasons"] == [Reason.DUPLICATE_NAME, Reason.DUPLICATE_DISPLAY_NAME]
    assert all("version_label" not in row for row in result)
    assert all(row["tags"] == [] for row in result)
    sources[3].assert_called_once_with(expected_ids, "a")
    sources[4].assert_called_once()


def test_opt_in_label_changes_only_optional_metadata(mocker, sources):
    mocker.patch.object(management, "get_user_tenant_by_user_id", return_value={"user_role": "ADMIN"})
    original = management._list_all_agent_info_sync("a", "reader")
    labeled = management._list_all_agent_info_sync("a", "reader", include_version_label=True)
    assert labeled[0]["version_label"] == "Release three"
    assert [{k: v for k, v in row.items() if k != "version_label"} for row in labeled] == original


@pytest.mark.parametrize("role,expected_ids", [("ADMIN", [1, 2, 3, 6]), ("USER", [1, 2, 3])])
def test_published_list_preserves_fallback_and_its_distinct_visibility(mocker, sources, role, expected_ids):
    mocker.patch.object(versions, "get_user_tenant_by_user_id", return_value={"user_role": role})
    knowledge_sources = mocker.patch.object(
        versions,
        "_published_knowledge_sources",
        side_effect=lambda agent_id, _tenant_id, _version_no: {"local": agent_id == 1, "aidp": False},
    )
    result = versions._list_published_agents_sync("a", "reader")
    assert [row["agent_id"] for row in result] == expected_ids
    assert [row["knowledge_sources"] for row in result] == [
        {"local": agent_id == 1, "aidp": False} for agent_id in expected_ids
    ]
    assert knowledge_sources.call_args_list == [
        mocker.call(agent_id, "a", 3 if agent_id == 1 else 1) for agent_id in expected_ids
    ]
    assert result[0]["current_version_no"] == 3
    assert result[0]["version_name"] == "Release three"
    assert result[0]["model_ids"] == [1]
    assert result[0]["is_available"] is True
    assert result[0]["unavailable_reasons"] == []
    assert result[1]["unavailable_reasons"] == [Reason.DUPLICATE_NAME, Reason.DUPLICATE_DISPLAY_NAME]
    sources[1].assert_called_once_with(expected_ids, "a")
    sources[2].assert_called_once_with({aid: 3 if aid == 1 else 1 for aid in expected_ids}, "a")
    sources[3].assert_called_once_with(expected_ids, "a")
    sources[4].assert_called_once()


def test_list_errors_remain_visible_and_preserve_service_mapping(mocker, sources):
    mocker.patch.object(management, "get_user_tenant_by_user_id", side_effect=RuntimeError("database down"))
    with pytest.raises(ValueError, match="Failed to query all agent info: database down"):
        management._list_all_agent_info_sync("a", "reader")
