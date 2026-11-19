# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Value equivalence of request-local availability and model projections."""

from copy import deepcopy

import pytest

from management.services.agent import read


def _encoded_profile_row(profile, model_id):
    """Full model_record_t projection exactly as the outlet persistence path writes it."""
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
    from nexent.core.model_service.registry import model_service_references

    data = profile.model_dump(mode="json")
    data["outlet_id"] = data["connection"]["credential_ref"]["model_id"] = model_id
    return encode_resolved_model_profile(profile.__class__.model_validate(data),
                                         registered_references=model_service_references())


@pytest.fixture
def profile():
    from management.services.model.profiles import build_outlet_draft
    from test.backend.services.test_model_profile_service import draft_request

    value, _ = build_outlet_draft(draft_request(parameter_values={"enable_thinking": True,
        "reasoning_budget_tokens": 64, "temperature": 0.8, "max_output_tokens": 2048}), "a")
    return value


@pytest.fixture
def records():
    models = {
        1: {"model_id": 1, "tenant_id": "a", "delete_flag": "N", "model_type": "llm", "display_name": "LLM"},
        2: {"model_id": 2, "tenant_id": "a", "delete_flag": "Y", "model_type": "llm"},
        3: {"model_id": 3, "tenant_id": "b", "delete_flag": "N", "model_type": "llm"},
        4: {"model_id": 4, "tenant_id": "a", "delete_flag": "N", "model_type": "embedding"},
    }
    definition = {
        "tool_id": 10, "delete_flag": "N", "is_available": True,
        "params": [{"name": "selected_model_id", "default": 1}],
    }
    return models, definition


@pytest.mark.parametrize("model_ids", [[], [1], [2], [3], [4], [999], [2, 1, 1, 3, 4]])
@pytest.mark.parametrize("selected", [None, 1, 2, "2", 3, 999])
@pytest.mark.parametrize("available,delete_flag", [(True, "N"), (False, "N"), (False, "Y")])
def test_batch_projection_matches_standalone_rules(mocker, records, model_ids, selected, available, delete_flag):
    models, definition = records
    definition.update(is_available=available, delete_flag=delete_flag)
    instance = {"agent_id": 8, "tool_id": 10, "params": {"selected_model_id": selected}}
    batch_tools = mocker.patch.object(read, "query_agent_tools_for_list", return_value=([instance], {10: definition}))
    batch_models = mocker.patch.object(read, "get_model_records_by_ids", side_effect=lambda ids: {
        mid: deepcopy(models[mid]) for mid in ids if mid in models
    })
    agent = {"agent_id": 8, "model_ids": model_ids}
    context = read.load_agent_list_context([agent], "a")
    batch_tools.assert_called_once_with([8], "a")
    batch_models.assert_called_once()
    tools = deepcopy(context.tools[8])
    mocker.patch.object(read, "get_valid_model_ids", side_effect=lambda ids, tenant: [
        mid for mid in ids if models.get(mid, {}).get("delete_flag") == "N"
    ])
    mocker.patch.object(read, "resolve_model_record", side_effect=lambda mid, tenant, cache: (
        models.get(mid) if models.get(mid, {}).get("tenant_id") == tenant
        and models.get(mid, {}).get("delete_flag") == "N" else None
    ))
    mocker.patch.object(read, "search_tools_for_sub_agent", return_value=tools)
    mocker.patch.object(read, "check_tool_is_available", return_value=[available] if delete_flag == "N" else [])
    mocker.patch.object(read, "get_model_by_model_id_ignore_delete", side_effect=lambda mid, tenant: (
        models.get(int(mid)) if models.get(int(mid), {}).get("tenant_id") == tenant else None
    ))
    legacy_projection = read.project_agent_models(deepcopy(agent), "a", {})
    legacy_availability = read.check_agent_availability(8, "a", agent, {})
    # The batch path must not issue any single-record reads.
    for name in ["get_valid_model_ids", "search_tools_for_sub_agent", "check_tool_is_available",
                 "get_model_by_model_id_ignore_delete"]:
        mocker.patch.object(read, name, side_effect=AssertionError("Unexpected individual lookup"))
    assert read.project_agent_models(deepcopy(agent), "a", {}, read_context=context) == legacy_projection
    assert read.check_agent_availability(8, "a", agent, {}, read_context=context) == legacy_availability
    assert definition["params"][0]["default"] == 1


def test_batch_model_cache_contains_missing_and_cross_tenant_ids(mocker, records):
    models, _ = records
    mocker.patch.object(read, "query_agent_tools_for_list", return_value=([], {}))
    mocker.patch.object(read, "get_model_records_by_ids", return_value=models)
    context = read.load_agent_list_context([{"agent_id": 1, "model_ids": [1, 2, 3, 999]}], "a")
    assert context.model_cache() == {1: models[1], 2: None, 3: None, 999: None}


def test_empty_batch_and_repository_error(mocker):
    tools = mocker.patch.object(read, "query_agent_tools_for_list", return_value=([], {}))
    models = mocker.patch.object(read, "get_model_records_by_ids", return_value={})
    assert read.load_agent_list_context([], "a").model_cache() == {}
    tools.assert_called_once_with([], "a")
    models.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        read.load_agent_list_context([{"agent_id": 1}], "a")


def _override_page_context(mocker, full_row):
    """List-path page: 8-column batch rows in the cache, one agent with an override entry."""
    slim = {1: {"model_id": 1, "tenant_id": "a", "delete_flag": "N", "model_type": "llm",
                "display_name": "LLM", "model_name": "llm-model", "profile_schema_version": 1,
                "connect_status": "available"}}
    mocker.patch.object(read, "query_agent_tools_for_list", return_value=([], {}))
    mocker.patch.object(read, "get_model_records_by_ids", return_value=slim)
    full_fetch = mocker.patch("management.services.model.resolver.get_model_by_model_id",
                              return_value=full_row)
    agent = {"agent_id": 8, "model_ids": [1],
             "model_params_override": {"1": {"temperature": 0, "extra_params": {"enable_thinking": False}}}}
    return agent, read.load_agent_list_context([agent], "a"), full_fetch


def test_list_projection_decodes_override_entries_from_full_rows(mocker, profile):
    agent, context, full_fetch = _override_page_context(mocker, _encoded_profile_row(profile, 1))
    view = read.project_agent_models(deepcopy(agent), "a", context.model_cache(), read_context=context).fields
    full_fetch.assert_called_once_with(1, "a")
    assert view["model_params_override"]["1"] == {"parameter_values": {"temperature": 0, "enable_thinking": False}}
    assert view["model_ids"] == [1] and view["model_name"] == "LLM"


def test_list_projection_survives_one_broken_profile_row(mocker, profile):
    from nexent.core.model_service.compatibility.agent_parameters import read_agent_parameter_entry

    broken_row = _encoded_profile_row(profile, 1)
    del broken_row["resolved_profile"]
    agent, context, _ = _override_page_context(mocker, broken_row)
    view = read.project_agent_models(deepcopy(agent), "a", context.model_cache(), read_context=context).fields
    assert view["model_params_override"]["1"] == read_agent_parameter_entry(agent["model_params_override"]["1"])
    assert view["model_ids"] == [1]
