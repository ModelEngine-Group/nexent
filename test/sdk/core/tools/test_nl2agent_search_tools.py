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


def test_nl2agent_install_web_skill_passes_skill_name(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.install_web_skill_tool import (
        get_install_web_skill_tool,
        nl2agent_install_web_skill,
    )

    calls = []

    async def fake_install_web_skill(**kwargs):
        calls.append(kwargs)
        return {
            "skill_id": 0,
            "skill_name": "search-web-tavily",
            "installed": True,
            "installed_ids": [],
            "installed_names": ["search-web-tavily"],
        }

    _install_fake_nl2agent_service(
        monkeypatch, install_web_skill=fake_install_web_skill
    )

    get_install_web_skill_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    raw_result = nl2agent_install_web_skill(
        skill_id=0, skill_name="search-web-tavily"
    )

    assert json.loads(raw_result) == {
        "skill_id": 0,
        "skill_name": "search-web-tavily",
        "installed": True,
        "installed_ids": [],
        "installed_names": ["search-web-tavily"],
    }
    assert calls[0]["skill_id"] == 0
    assert calls[0]["skill_name"] == "search-web-tavily"
    assert calls[0]["tenant_id"] == "tenant_1"
    assert calls[0]["user_id"] == "user_1"


def test_nl2agent_search_local_resources_caches_repeat_query(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_local_resources_tool import (
        get_search_local_resources_tool,
        nl2agent_search_local_resources,
    )

    calls = []

    async def fake_recommend_local_resources(**kwargs):
        calls.append(kwargs)
        return {"tools": [{"tool_id": 1, "name": "Search"}], "skills": []}

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

    first = nl2agent_search_local_resources(query="web search")
    # Same query modulo whitespace/case normalization: served from cache.
    second = nl2agent_search_local_resources(query="  Web Search  ")
    # A different query bypasses the cache.
    third = nl2agent_search_local_resources(query="database query")

    assert first == second
    assert json.loads(third)["tools"] == [{"tool_id": 1, "name": "Search"}]
    assert len(calls) == 2


def test_nl2agent_search_web_mcps_cache_survives_context_reset(monkeypatch):
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

    context_kwargs = dict(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )
    get_search_web_mcps_tool(**context_kwargs)
    first = nl2agent_search_web_mcps(query="github")

    # A new chat message rebuilds the agent and re-runs the tool initializer;
    # the cache must survive that context reset to deduplicate across turns.
    get_search_web_mcps_tool(**context_kwargs)
    second = nl2agent_search_web_mcps(query="github")

    assert first == second
    assert len(calls) == 1


def test_nl2agent_search_web_skills_caches_repeat_query(monkeypatch):
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

    first = nl2agent_search_web_skills(query="code review")
    second = nl2agent_search_web_skills(query="code review")

    assert first == second
    assert len(calls) == 1


def test_nl2agent_search_local_resources_does_not_cache_errors(monkeypatch):
    _reset_nl2agent_modules(monkeypatch)

    from nexent.core.tools.nl2agent.search_local_resources_tool import (
        get_search_local_resources_tool,
        nl2agent_search_local_resources,
    )

    attempts = []

    async def flaky_recommend_local_resources(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("backend down")
        return {"tools": [], "skills": []}

    _install_fake_nl2agent_service(
        monkeypatch, recommend_local_resources=flaky_recommend_local_resources
    )

    get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        model_id=7,
        language="en",
    )

    first = nl2agent_search_local_resources(query="web search")
    second = nl2agent_search_local_resources(query="web search")

    assert json.loads(first) == {"error": "backend down"}
    assert json.loads(second) == {"agent_id": 202, "tools": [], "skills": []}
    assert len(attempts) == 2
