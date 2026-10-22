# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Name validation parity between the creator tool and ordinary Agent edits."""

import ast
import json
import re
from types import SimpleNamespace

import pytest
from nexent.core.agents.core_agent import CoreAgent
from pydantic import ValidationError

from agents.nl2agent_agent import build_nl2agent_system_prompt
from consts.exceptions import AgentDraftEditError
from consts.model import AgentInfoRequest
from services import nl2agent_service as service
from tool_collection.mcp import nl2agent_mcp_tools as tools


@pytest.mark.parametrize("name", [
    "agent_170", "my_agent", "research_assistant", "9agent", "with-dash", "中文助手",
    "a" * 31, "a" * 61, "a" * 101, "", "  agent_170 \t",
])
def test_name_uses_backend_request_validation_without_creator_constraints(name):
    expected = AgentInfoRequest(name=name).name
    assert tools.AgentDraftFields(name=name).name == expected


@pytest.mark.parametrize("name", [123, True, [], {}, b"invalid\xff"])
def test_name_rejects_the_same_invalid_types_as_backend_request(name):
    with pytest.raises(ValidationError):
        AgentInfoRequest(name=name)
    with pytest.raises(ValidationError):
        tools.AgentDraftFields(name=name)


def test_name_schema_retains_backend_type_without_local_constraints():
    actual = tools.AgentDraftFields.model_json_schema()["properties"]["name"]
    expected = AgentInfoRequest.model_json_schema()["properties"]["name"]
    assert actual == expected
    assert tools.AgentDraftFields(description="Keep name").model_dump(exclude_unset=True) == {
        "description": "Keep name",
    }
    for fields in ({}, {"name": None}, {"unknown": "field"}):
        with pytest.raises(ValidationError):
            tools.AgentDraftFields.model_validate(fields)


@pytest.fixture
def draft_boundary(mocker):
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers={
        "Authorization": "Bearer test", tools.NL2AGENT_AGENT_ID_HEADER: "170",
    }))
    mocker.patch.object(tools, "get_current_user_id", return_value=("owner", "tenant-a"))
    authorize = mocker.patch.object(service, "require_agent_draft_edit", return_value={
        "agent_id": 170, "name": None, "display_name": "Existing draft", "description": "",
    })
    catalog = mocker.patch.object(service, "query_all_agent_info_by_tenant_id", return_value=[])
    update = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    return authorize, catalog, update


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["agent_170", "my_agent", "  agent_170 \t", "中文助手", "a" * 61])
async def test_mcp_save_forwards_backend_accepted_name_unchanged(draft_boundary, name):
    authorize, _catalog, update = draft_boundary
    result = await tools.save_agent_draft_fields(170, {"name": name})
    serialized, state = result.split("\n", 1)
    assert json.loads(serialized) == {
        "status": "success", "agent_id": 170, "created": False, "updated_fields": ["name"],
    }
    assert json.loads(state.removeprefix("<nl2a_state>").removesuffix("</nl2a_state>")) == {
        "event": "agent_draft_fields_saved", "agent_id": 170, "updated_fields": ["name"],
    }
    authorize.assert_called_once_with(agent_id=170, tenant_id="tenant-a", user_id="owner")
    update.assert_called_once_with(agent_id=170, tenant_id="tenant-a", fields={"name": name})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["duplicate", "already_set", "read_only"])
async def test_suffix_free_names_do_not_bypass_existing_draft_boundaries(draft_boundary, failure):
    authorize, catalog, update = draft_boundary
    if failure == "duplicate":
        catalog.return_value = [{"agent_id": 99, "name": "agent_170"}]
    elif failure == "already_set":
        authorize.return_value["name"] = "existing"
    else:
        authorize.side_effect = AgentDraftEditError("agent_read_only")
    result = await tools.save_agent_draft_fields(170, {"name": "agent_170"})
    payload = json.loads(result)
    assert payload["status"] == "error"
    assert payload["code"] == {
        "duplicate": "agent_name_duplicate", "already_set": "agent_name_already_set",
        "read_only": "agent_read_only",
    }[failure]
    assert payload["retryable"] is (failure == "duplicate")
    update.assert_not_called()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_naming_prompt_is_self_contained_and_keeps_meaningful_example(language):
    prompt = build_nl2agent_system_prompt(language)
    assert "普通 Agent 编辑请求" not in prompt
    assert "ordinary Agent edit request" not in prompt
    assert "以 `_assistant` 结尾" not in prompt
    assert "end with `_assistant`" not in prompt
    assert ("合法 Python 标识符" in prompt or "valid Python identifier" in prompt)
    assert ("Python 关键字" in prompt or "Python keyword" in prompt)
    assert "`class`" in prompt and "`for`" in prompt
    assert ("100 个字符" in prompt or "100 characters" in prompt)
    assert "30" not in prompt
    names = []
    for code in re.findall(r"<code>\n(.*?)\n</code>", prompt, re.DOTALL):
        for node in ast.walk(ast.parse(code)):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "fields" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key, value in zip(keyword.value.keys, keyword.value.values):
                    if ast.literal_eval(key) == "name":
                        names.append(ast.literal_eval(value))
    assert names == ["research_assistant"]
    assert AgentInfoRequest(name=names[0]).name == tools.AgentDraftFields(name=names[0]).name
    assert CoreAgent._validate_name(None, names[0]) == names[0]
    assert len(names[0]) <= 100
