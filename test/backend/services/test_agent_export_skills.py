# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression coverage for selected skills in portable agent exports."""

import io
import json
import zipfile

import pytest

from management.services.agent import transfer


@pytest.fixture
def export_context(mocker):
    mocker.patch.object(transfer, "get_current_user_info", return_value=("user", "tenant", "USER"))
    mocker.patch.object(transfer, "is_system_agent", return_value=False)
    mocker.patch.object(transfer, "search_agent_info_by_agent_id", return_value={
        "tenant_id": "tenant", "name": "agent", "display_name": "Agent",
        "description": "Test", "max_steps": 5, "provide_run_summary": True,
        "enabled": True, "model_ids": [],
    })
    mocker.patch.object(transfer, "create_tool_config_list", return_value=[])
    mocker.patch.object(transfer, "query_sub_agents_id_list", return_value=[])
    mocker.patch.object(transfer, "query_sub_agent_relations", return_value=[])
    instances = mocker.patch.object(transfer.skill_db, "query_skill_instances_by_agent_id", return_value=[])
    lookup = mocker.patch.object(transfer.skill_db, "get_skill_by_id", side_effect=lambda sid, _tenant: {
        "name": {1: "selected", 2: "removed"}[sid],
    })
    service = mocker.patch.object(transfer, "SkillService").return_value
    service.export_skills_by_names.side_effect = lambda names, _tenant: [
        {"skill_name": name, "skill_zip_base64": "c2tpbGw="} for name in names
    ]
    return instances, lookup, service


@pytest.mark.asyncio
@pytest.mark.parametrize("version_no", [0, 3])
@pytest.mark.parametrize("instances, expected", [
    ([], []),
    ([{"skill_id": 2, "enabled": False}], []),
    ([{"skill_id": 1, "enabled": True}, {"skill_id": 2, "enabled": False}], ["selected"]),
    ([{"skill_id": 1}], ["selected"]),
])
async def test_export_json_uses_selected_skills(export_context, instances, expected, version_no):
    query, lookup, _service = export_context
    query.return_value = instances

    result = await transfer.export_agent_by_agent_id(1, "tenant", "user", version_no=version_no)

    assert result.skill_names == expected
    query.assert_called_once_with(agent_id=1, tenant_id="tenant", version_no=version_no)
    assert [item.args[0] for item in lookup.call_args_list] == ([1] if expected else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("keep_selected", [False, True])
async def test_export_download_excludes_removed_skill(export_context, keep_selected):
    query, lookup, service = export_context
    query.return_value = [{"skill_id": 2, "enabled": False}]
    if keep_selected:
        query.return_value.append({"skill_id": 1, "enabled": True})

    result = await transfer.export_agent_with_skills_impl(1, "Bearer test")

    if keep_selected:
        assert result["_zip"] is True
        with zipfile.ZipFile(io.BytesIO(result["data"])) as archive:
            assert set(archive.namelist()) == {"agent.json", "skills/selected.zip"}
            assert json.loads(archive.read("agent.json"))["agent_info"]["1"]["skill_names"] == ["selected"]
        service.export_skills_by_names.assert_called_once_with(["selected"], "tenant")
    else:
        assert "_zip" not in result
        assert result["agent_info"]["1"]["skill_names"] == []
        service.export_skills_by_names.assert_not_called()
    assert all(item.args[0] != 2 for item in lookup.call_args_list)


def test_tree_selection_preserves_child_version_and_deduplication(export_context, mocker):
    query, lookup, _service = export_context
    query.side_effect = lambda **kw: {
        (1, 0): [{"skill_id": 2, "enabled": False}],
        (2, 4): [{"skill_id": 2, "enabled": True}, {"skill_id": 1, "enabled": True}],
        (3, 0): [{"skill_id": 1, "enabled": True}, {"skill_id": 2, "enabled": False}],
    }[(kw["agent_id"], kw["version_no"])]
    relations = mocker.patch.object(transfer, "query_sub_agent_relations", side_effect=lambda **kw: {
        1: [{"selected_agent_id": 2, "selected_agent_version_no": 4},
            {"selected_agent_id": 3, "selected_agent_version_no": 0}],
        2: [{"selected_agent_id": 1, "selected_agent_version_no": 0}],
        3: [],
    }[kw["main_agent_id"]])
    mocker.patch.object(transfer, "resolve_sub_agent_version_no", side_effect=lambda _aid, version, _tenant: version)

    assert transfer._collect_skill_names_from_tree(1, "tenant", 0) == ["removed", "selected"]
    assert [(item.kwargs["agent_id"], item.kwargs["version_no"]) for item in query.call_args_list] == [
        (1, 0), (2, 4), (3, 0),
    ]
    assert [item.args[0] for item in lookup.call_args_list] == [2, 1, 1]
    assert relations.call_count == 3


@pytest.mark.parametrize("version_no, expected", [(0, []), (4, ["selected"])])
def test_draft_removal_does_not_change_published_selection(export_context, version_no, expected):
    query, _lookup, _service = export_context
    query.side_effect = lambda **kw: [{"skill_id": 1, "enabled": kw["version_no"] == 4}]
    assert transfer._collect_skill_names_from_tree(1, "tenant", version_no) == expected


@pytest.mark.asyncio
async def test_missing_skill_catalog_entry_is_omitted(export_context):
    query, lookup, _service = export_context
    query.return_value = [{"skill_id": 1, "enabled": True}]
    lookup.side_effect = None
    lookup.return_value = None
    assert transfer._collect_skill_names_from_tree(1, "tenant", 0) == []
    assert (await transfer.export_agent_by_agent_id(1, "tenant", "user")).skill_names == []


@pytest.mark.asyncio
async def test_skill_read_failure_retains_existing_error_boundaries(export_context):
    query, _lookup, _service = export_context
    query.side_effect = RuntimeError("skill store unavailable")
    with pytest.raises(RuntimeError, match="skill store unavailable"):
        transfer._collect_skill_names_from_tree(1, "tenant", 0)
    assert (await transfer.export_agent_by_agent_id(1, "tenant", "user")).skill_names == []


@pytest.mark.asyncio
async def test_system_export_rejected_before_skill_reads(export_context, mocker):
    query, _lookup, _service = export_context
    mocker.patch.object(transfer, "is_system_agent", return_value=True)
    with pytest.raises(transfer.ForbiddenError, match="cannot be exported"):
        await transfer.export_agent_with_skills_impl(1, "Bearer test")
    query.assert_not_called()
