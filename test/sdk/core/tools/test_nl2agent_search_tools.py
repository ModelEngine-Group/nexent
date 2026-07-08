import json
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SDK_SOURCE_ROOT = PROJECT_ROOT / "sdk"
if str(SDK_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_SOURCE_ROOT))


def _reset_nl2agent_modules(monkeypatch):
    for module_name in list(sys.modules):
        if (
            module_name == "nexent"
            or module_name.startswith("nexent.core")
            or module_name == "smolagents"
            or module_name.startswith("smolagents.")
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)


def _install_fake_nl2agent_service(monkeypatch, **handlers):
    services_module = types.ModuleType("services")
    services_module.__path__ = []
    nl2agent_service_module = types.ModuleType("services.nl2agent_service")
    for name, handler in handlers.items():
        setattr(nl2agent_service_module, name, handler)
    services_module.nl2agent_service = nl2agent_service_module

    monkeypatch.setitem(sys.modules, "services", services_module)
    monkeypatch.setitem(
        sys.modules, "services.nl2agent_service", nl2agent_service_module
    )


def test_nl2agent_search_local_resources_returns_card_payload_with_draft_agent_id(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_local_resources_tool import (
        get_search_local_resources_tool,
        nl2agent_search_local_resources,
    )

    calls = []

    async def fake_recommend_local_resources(**kwargs):
        calls.append(kwargs)
        return {
            "tools": [{"tool_id": 1, "name": "Search"}],
            "skills": [{"skill_id": 7, "name": "Summarize"}],
        }

    _install_fake_nl2agent_service(
        monkeypatch, recommend_local_resources=fake_recommend_local_resources
    )

    get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_search_local_resources(query="search and summarize")

    assert json.loads(raw_result) == {
        "agent_id": 202,
        "tools": [{"tool_id": 1, "name": "Search"}],
        "skills": [{"skill_id": 7, "name": "Summarize"}],
    }
    assert calls[0]["agent_id"] == 202
    assert calls[0]["tenant_id"] == "tenant_1"
    assert calls[0]["model_id"] == 7


def test_nl2agent_search_local_resources_rejects_invalid_draft_agent_id(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_local_resources_tool import (
        get_search_local_resources_tool,
        nl2agent_search_local_resources,
    )

    get_search_local_resources_tool(
        agent_id=0,
        draft_agent_id=0,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_search_local_resources(query="search")

    assert json.loads(raw_result) == {
        "error": "NL2AGENT draft agent_id not set in context."
    }


def test_nl2agent_search_web_mcps_returns_card_payload_with_draft_agent_id(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_web_mcps_tool import (
        get_search_web_mcps_tool,
        nl2agent_search_web_mcps,
    )

    calls = []

    async def fake_search_web_mcps(**kwargs):
        calls.append(kwargs)
        return [{"name": "GitHub MCP", "source": "community"}]

    _install_fake_nl2agent_service(monkeypatch, search_web_mcps=fake_search_web_mcps)

    get_search_web_mcps_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_search_web_mcps(query="repository automation")

    assert json.loads(raw_result) == {
        "agent_id": 202,
        "items": [{"name": "GitHub MCP", "source": "community"}],
    }
    assert calls[0]["tenant_id"] == "tenant_1"
    assert calls[0]["model_id"] == 7


def test_nl2agent_search_web_mcps_rejects_invalid_draft_agent_id(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_web_mcps_tool import (
        get_search_web_mcps_tool,
        nl2agent_search_web_mcps,
    )

    get_search_web_mcps_tool(
        agent_id=0,
        draft_agent_id=0,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_search_web_mcps(query="repository automation")

    assert json.loads(raw_result) == {
        "error": "NL2AGENT draft agent_id not set in context."
    }


def test_nl2agent_search_web_skills_returns_card_payload_with_draft_agent_id(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_web_skills_tool import (
        get_search_web_skills_tool,
        nl2agent_search_web_skills,
    )

    calls = []

    async def fake_search_web_skills(**kwargs):
        calls.append(kwargs)
        return [{"skill_id": 12, "name": "doc-review"}]

    _install_fake_nl2agent_service(
        monkeypatch, search_web_skills=fake_search_web_skills
    )

    get_search_web_skills_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_search_web_skills(query="review documents")

    assert json.loads(raw_result) == {
        "agent_id": 202,
        "items": [{"skill_id": 12, "name": "doc-review"}],
    }
    assert calls[0]["tenant_id"] == "tenant_1"
    assert calls[0]["model_id"] == 7


def test_nl2agent_search_web_skills_rejects_invalid_draft_agent_id(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_web_skills_tool import (
        get_search_web_skills_tool,
        nl2agent_search_web_skills,
    )

    get_search_web_skills_tool(
        agent_id=0,
        draft_agent_id=0,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_search_web_skills(query="review documents")

    assert json.loads(raw_result) == {
        "error": "NL2AGENT draft agent_id not set in context."
    }
