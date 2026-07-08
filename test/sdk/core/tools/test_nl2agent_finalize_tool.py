import json
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SDK_SOURCE_ROOT = PROJECT_ROOT / "sdk"
if str(SDK_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_SOURCE_ROOT))


def test_nl2agent_finalize_agent_defaults_tool_ids_to_empty_list(monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", types.ModuleType("paramiko"))
    for module_name in list(sys.modules):
        if (
            module_name == "nexent"
            or module_name.startswith("nexent.core")
            or module_name == "smolagents"
            or module_name.startswith("smolagents.")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    from nexent.core.tools.nl2agent.finalize_agent_tool import (
        get_finalize_agent_tool,
        nl2agent_finalize_agent,
    )

    calls = []

    async def fake_finalize_agent(**kwargs):
        calls.append(kwargs)
        return {"agent_id": kwargs["agent_id"], "status": "draft_ready"}

    services_module = types.ModuleType("services")
    services_module.__path__ = []
    nl2agent_service_module = types.ModuleType("services.nl2agent_service")
    nl2agent_service_module.finalize_agent = fake_finalize_agent
    services_module.nl2agent_service = nl2agent_service_module

    monkeypatch.setitem(sys.modules, "services", services_module)
    monkeypatch.setitem(
        sys.modules, "services.nl2agent_service", nl2agent_service_module
    )

    get_finalize_agent_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_finalize_agent(task_description="Build a helper agent")

    assert json.loads(raw_result) == {"agent_id": 202, "status": "draft_ready"}
    assert calls[0]["agent_id"] == 202
    assert calls[0]["tool_ids"] == []
    assert calls[0]["skill_ids"] == []
    assert calls[0]["sub_agent_ids"] == []
    assert calls[0]["knowledge_base_display_names"] == []


def test_nl2agent_finalize_agent_rejects_invalid_draft_agent_id(monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", types.ModuleType("paramiko"))
    for module_name in list(sys.modules):
        if (
            module_name == "nexent"
            or module_name.startswith("nexent.core")
            or module_name == "smolagents"
            or module_name.startswith("smolagents.")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    from nexent.core.tools.nl2agent.finalize_agent_tool import (
        get_finalize_agent_tool,
        nl2agent_finalize_agent,
    )

    get_finalize_agent_tool(
        agent_id=0,
        draft_agent_id=0,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_finalize_agent(task_description="Build a helper agent")

    assert json.loads(raw_result) == {
        "error": "NL2AGENT draft agent_id not set in context."
    }
