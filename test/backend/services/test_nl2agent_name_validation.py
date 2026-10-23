# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Name constraints aligned with backend import, runtime and storage."""

import ast
import json
import re
from types import SimpleNamespace

import pytest
from nexent.core.agents.core_agent import CoreAgent
from pydantic import ValidationError

from management.services.agent.creation import build_nl2agent_system_prompt
from contracts.errors.exceptions import AgentDraftEditError
from contracts.agent import AgentInfoRequest
from services import nl2agent_service as service
from tool_collection.mcp import nl2agent_mcp_tools as tools


@pytest.mark.parametrize("name", [
    "a", "_", "agent_170", "my_agent", "research_assistant", "中文助手",
    "a" * 30, "a" * 31, "a" * 60, "a" * 61, "a" * 100,
])
def test_name_accepts_runtime_identifiers_within_storage_limit(name):
    assert tools.AgentDraftFields(name=name).name == name
    assert CoreAgent._validate_name(None, name) == name


@pytest.mark.parametrize("name", [
    "", " ", "9agent", "with-dash", "with space", "agent\n", "  agent_170 \t",
    "class", "for", "None", "True", "a" * 101,
    123, True, [], {}, b"invalid\xff",
])
def test_name_rejects_invalid_runtime_names_and_types(name):
    with pytest.raises(ValidationError):
        tools.AgentDraftFields(name=name)


def test_name_schema_exposes_runtime_and_storage_constraints():
    actual = tools.AgentDraftFields.model_json_schema()["properties"]["name"]
    string_schema = next(item for item in actual["anyOf"] if item["type"] == "string")
    assert string_schema["minLength"] == 1
    assert string_schema["maxLength"] == 100
    assert "Python identifier" in actual["description"]
    assert "keyword" in actual["description"]
    assert "pattern" not in string_schema
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
@pytest.mark.parametrize("name", ["agent_170", "my_agent", "中文助手", "a" * 100])
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
@pytest.mark.parametrize("name", ["class", "9agent", "with-dash", " agent ", "", "a" * 101])
async def test_mcp_save_rejects_invalid_names_without_writing(draft_boundary, name):
    _authorize, _catalog, update = draft_boundary
    result = json.loads(await tools.save_agent_draft_fields(170, {"name": name}))
    assert result["status"] == "error"
    assert result["code"] == "invalid_agent_fields"
    update.assert_not_called()


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


@pytest.mark.asyncio
async def test_duplicate_name_can_be_regenerated_until_saved_then_is_immutable(draft_boundary):
    authorize, catalog, update = draft_boundary
    catalog.return_value = [{"agent_id": 99, "name": "research_assistant"}]
    failed = json.loads(await tools.save_agent_draft_fields(170, {"name": "research_assistant"}))
    assert failed["code"] == "agent_name_duplicate"
    assert failed["retryable"] is True
    assert authorize.return_value["name"] is None
    update.assert_not_called()

    def persist_name(*, agent_id, tenant_id, fields):
        assert agent_id == 170
        assert tenant_id == "tenant-a"
        authorize.return_value.update(fields)
        return 1

    update.side_effect = persist_name
    saved = await tools.save_agent_draft_fields(170, {"name": "research_helper"})
    payload, _state = saved.split("\n", 1)
    assert json.loads(payload)["status"] == "success"
    assert authorize.return_value["name"] == "research_helper"
    update.assert_called_once_with(
        agent_id=170, tenant_id="tenant-a", fields={"name": "research_helper"},
    )

    rejected = json.loads(await tools.save_agent_draft_fields(170, {"name": "another_helper"}))
    assert rejected["code"] == "agent_name_already_set"
    assert rejected["retryable"] is False
    assert authorize.return_value["name"] == "research_helper"
    assert update.call_count == 1


@pytest.mark.parametrize("language", ["zh", "en"])
def test_naming_prompt_distinguishes_failed_candidates_from_saved_names(language):
    prompt = build_nl2agent_system_prompt(language)
    heading = "### 变量名初始化" if language == "zh" else "### Variable Name Initialization"
    initialization = prompt.split(heading, 1)[1].split("\n### ", 1)[0]
    assert "agent_name_duplicate" in initialization
    assert "retryable=true" in initialization
    assert "agent_name_already_set" in initialization
    if language == "zh":
        assert "每次模型回复只执行一个保存动作" in initialization
        assert "重新生成" in initialization and "重试一次" in initialization
        assert "同一 `agent_id`" in initialization
        assert "保存成功后才禁止覆盖" in initialization
        assert "第二次失败" in initialization
        assert "执行唯一一个保存动作" not in prompt
    else:
        assert "one save action per model response" in initialization
        assert "regenerate" in initialization and "retry once" in initialization
        assert "same `agent_id`" in initialization
        assert "Only after a successful save" in initialization
        assert "second failure" in initialization
        assert "perform exactly one save action" not in prompt
