from types import SimpleNamespace

import pytest

from backend.services import tool_configuration_service as service


def _tool(tool_id: int, name: str, params=None):
    return {
        "tool_id": tool_id,
        "name": name,
        "description": name,
        "source": "local",
        "params": params or [],
        "inputs": "{}",
        "is_available": True,
        "create_time": "",
        "usage": "",
    }


@pytest.mark.asyncio
async def test_managed_aidp_is_not_user_selectable_and_hides_backend_params(mocker):
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    mocker.patch.object(
        service,
        "query_all_tools",
        return_value=[
            _tool(1, "knowledge_base_search"),
            _tool(
                2,
                "aidp_search",
                [
                    {"name": "server_url"},
                    {"name": "api_key"},
                    {"name": "tenant_id"},
                    {"name": "kds_name_to_id_map"},
                    {"name": "observer"},
                    {"name": "kds_list"},
                    {"name": "top_k"},
                ],
            ),
            _tool(3, "ind_aidp_search"),
            _tool(4, "store_memory"),
        ],
    )
    mocker.patch.object(service, "get_local_tools_description_zh", return_value={})
    mocker.patch.object(service, "get_user_email_map", return_value={})

    result = await service.list_all_tools("tenant-1")

    by_name = {tool["name"]: tool for tool in result}
    assert set(by_name) == {
        "knowledge_base_search",
        "aidp_search",
        "ind_aidp_search",
    }
    assert by_name["knowledge_base_search"]["is_user_selectable"] is False
    assert by_name["aidp_search"]["is_user_selectable"] is False
    assert by_name["ind_aidp_search"]["is_user_selectable"] is True
    assert [param["name"] for param in by_name["aidp_search"]["params"]] == [
        "kds_list",
        "top_k",
    ]


@pytest.mark.asyncio
async def test_aidp_system_tool_is_not_returned_when_capability_is_disabled(mocker):
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", False)
    mocker.patch.object(
        service,
        "query_all_tools",
        return_value=[
            _tool(1, "knowledge_base_search"),
            _tool(2, "aidp_search"),
            _tool(3, "ind_aidp_search"),
        ],
    )
    mocker.patch.object(service, "get_local_tools_description_zh", return_value={})
    mocker.patch.object(service, "get_user_email_map", return_value={})

    result = await service.list_all_tools("tenant-1")

    assert [tool["name"] for tool in result] == [
        "knowledge_base_search",
        "ind_aidp_search",
    ]


def test_kds_parser_accepts_supported_history_formats():
    assert service._parse_kds_list(["a", " a ", "b", "a"]) == ["a", "b"]
    assert service._parse_kds_list('["a", "b"]') == ["a", "b"]
    assert service._parse_kds_list("a, b,a") == ["a", "b"]
    assert service._parse_kds_list("{malformed-json") == []


class _ToolInfo:
    agent_id = 1
    tool_id = 2
    name = "aidp_search"
    version_no = 0
    enabled = True

    def __init__(self, kds_ids):
        self.params = {"kds_list": kds_ids}


def _mock_aidp_update(mocker, accessible_ids):
    mocker.patch.object(service, "ENABLE_AIDP_KNOWLEDGE", True)
    mocker.patch.object(service, "require_agent_draft_edit")
    mocker.patch.object(
        service,
        "query_all_tools",
        return_value=[_tool(2, "aidp_search")],
    )
    mocker.patch.object(
        service,
        "query_tool_instances_by_id",
        return_value={"params": {"kds_list": "[]"}},
    )
    mocker.patch.object(
        service,
        "_resolve_aidp_snapshot",
        return_value=SimpleNamespace(accessible_id_set=set(accessible_ids)),
    )
    return mocker.patch.object(
        service,
        "create_or_update_tool_by_tool_info",
        return_value={"id": 1},
    )


def test_aidp_save_serializes_kds_ids_as_json_string(mocker):
    mock_create = _mock_aidp_update(mocker, {"kds-1", "kds-2"})
    tool_info = _ToolInfo(["kds-1", "kds-2"])

    service.update_tool_info_impl(tool_info, "tenant-1", "user-1")

    saved = mock_create.call_args.args[0]
    assert saved.params["kds_list"] == '["kds-1", "kds-2"]'


@pytest.mark.parametrize(
    ("kds_ids", "error"),
    [
        ([], "at least one"),
        ([f"kds-{index}" for index in range(11)], "more than 10"),
        (["forged-kds"], "cannot configure"),
    ],
)
def test_aidp_save_rejects_empty_excessive_or_unauthorized_scope(
    mocker, kds_ids, error
):
    mock_create = _mock_aidp_update(mocker, set())

    with pytest.raises(service.ValidationError, match=error):
        service.update_tool_info_impl(
            _ToolInfo(kds_ids), "tenant-1", "user-1"
        )

    mock_create.assert_not_called()
