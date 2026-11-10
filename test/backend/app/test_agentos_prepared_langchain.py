# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.constants import environment
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.nexent_agent import NexentAgent


@pytest.mark.parametrize("change", [None, "request", "derived", "config", "revoked", "missing", "plugin", "path", "scope"])
@pytest.mark.asyncio
async def test_prepared_langchain_pins_plugin_and_authorized_binding(mocker, tmp_path, change):
    from infrastructure import langchain_plugins
    from management.services.agent.preparation import langchain_tool, tools
    from runtime.agentos import prepared_langchain

    mocker.patch.object(environment, "JWT_SECRET", "synthetic-langchain-key")
    mocker.patch.object(langchain_plugins, "LANGCHAIN_PLUGIN_DIRECTORY", tmp_path)
    plugin = tmp_path / "fixture.py"
    plugin.write_text(
        'from langchain_core.tools import tool\n'
        '@tool\n'
        'def fixture_double(value: int) -> int:\n'
        '    """Double the input."""\n'
        '    return 2 * value\n',
        encoding="utf-8",
    )
    row = {
        "tool_id": 11, "tool_instance_id": 12, "source": "langchain", "name": "fixture_double",
        "class_name": "fixture_double", "description": "Double", "usage": None,
        "inputs": None, "output_type": "integer", "instance_params": {},
        "params": [{"name": "opaque", "default": "never-in-transport"}],
    }
    if change in {"derived", "scope"}:
        row.pop("tool_instance_id")
        row["skill_instance_ids"] = [22]
    if change == "request":
        mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[row])
        mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "agent"})
        tool, = await tools.create_tool_config_list(
            8, "tenant-a", "user-a", version_no=3, portable_evaluation=True,
            tool_params={"agents": {"agent": {"tools": {"fixture_double": {"value": 99}}}}},
        )
    else:
        tool = langchain_plugins.build_langchain_tool(row)
    artifacts = langchain_plugins.discover_langchain_plugin_refs({"fixture_double"})
    binding = langchain_tool.export_langchain_tool(tool, [row], artifacts, 8, 3, "tenant-a")
    assert binding.tool_id == "langchain"
    assert binding.parameters["module_file"] == "fixture.py"
    assert "never-in-transport" not in binding.model_dump_json()
    assert "from langchain_core" not in binding.model_dump_json()
    direct = mocker.patch.object(prepared_langchain, "read_bound_langchain_tools", return_value=[row])
    derived = mocker.patch.object(prepared_langchain, "read_skill_derived_langchain_tools", return_value=[row])
    resource = SimpleNamespace(
        agent_id=8, version_no=3, tools=[binding],
        skill_refs=[SimpleNamespace(instance_id=22)] if change == "derived" else [],
    )
    if change == "config":
        direct.return_value = [{**row, "description": "Changed"}]
    elif change == "revoked":
        direct.return_value = []
    elif change == "missing":
        plugin.unlink()
    elif change == "plugin":
        plugin.write_text('raise AssertionError("changed plugin executed")\n', encoding="utf-8")
    elif change == "path":
        binding.parameters["module_file"] = "../outside.py"

    if change == "path":
        with pytest.raises(ValueError):
            prepared_langchain.materialize_langchain_tools(resource, ServicePrincipal("user-a", "tenant-a"))
    elif change not in {None, "request", "derived"}:
        with pytest.raises(HTTPException) as error:
            prepared_langchain.materialize_langchain_tools(resource, ServicePrincipal("user-a", "tenant-a"))
        assert error.value.status_code == (404 if change in {"revoked", "missing"} else 409)
    else:
        rebound, = prepared_langchain.materialize_langchain_tools(resource, ServicePrincipal("user-a", "tenant-a"))
        sdk_tool = NexentAgent.create_langchain_tool(None, rebound)
        assert sdk_tool.forward(value=6) == 12

    if change in {"derived", "scope"}:
        direct.assert_not_called()
        derived.assert_called_once_with(8, 3, "tenant-a", ["fixture_double"])
