import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SDK_SOURCE_ROOT = PROJECT_ROOT / "sdk"
if str(SDK_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_SOURCE_ROOT))

from nexent.core.tools.nl2agent import _context as context_module
from nexent.core.tools.nl2agent import search_local_resources_tool as local_tool_module
from nexent.core.tools.nl2agent.search_local_resources_tool import (
    get_search_local_resources_tool,
)
from nexent.core.tools.nl2agent.search_web_mcps_tool import (
    get_search_web_mcps_tool,
    normalize_mcp_candidate,
)
from nexent.core.tools.nl2agent.search_web_skills_tool import (
    get_search_web_skills_tool,
)


@pytest.fixture(autouse=True)
def reset_nl2agent_state():
    context_module._search_cache.clear()
    yield
    context_module._search_cache.clear()


def _loads(raw_result):
    return json.loads(raw_result)


@pytest.mark.parametrize(
    ("initializer", "catalog_kwargs", "query"),
    [
        (
            get_search_local_resources_tool,
            {"tool_catalog": [], "skill_catalog": []},
            "web search",
        ),
        (
            get_search_web_mcps_tool,
            {"registry_results": [], "community_results": []},
            "github",
        ),
        (
            get_search_web_skills_tool,
            {"official_skills": []},
            "code review",
        ),
    ],
)
def test_nl2agent_search_tools_require_tenant_context(initializer, catalog_kwargs, query):
    tool = initializer(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id=None,
        language="en",
        **catalog_kwargs,
    )

    assert _loads(tool(query=query)) == {"error": "NL2AGENT session context not initialized."}


def test_nl2agent_search_local_resources_returns_empty_results_for_empty_catalogs():
    tool = get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        tool_catalog=[],
        skill_catalog=[],
    )

    first = _loads(tool(query="web search"))
    assert first["agent_id"] == 202
    assert first["tools"] == []
    assert first["skills"] == []
    assert first["recommendation_batch_id"].startswith("local_")
    assert _loads(tool(query="web search"))["recommendation_batch_id"] == first[
        "recommendation_batch_id"
    ]


def test_nl2agent_search_web_mcps_returns_empty_results_for_empty_catalogs():
    tool = get_search_web_mcps_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        registry_results=[],
        community_results=[],
    )

    assert _loads(tool(query="github")) == {"agent_id": 202, "items": []}


def test_nl2agent_search_web_skills_returns_empty_results_for_empty_catalog():
    tool = get_search_web_skills_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        official_skills=[],
    )

    assert _loads(tool(query="code review")) == {"agent_id": 202, "items": []}


def test_nl2agent_search_local_resources_scores_and_ranks_catalog_candidates():
    tool = get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        tool_catalog=[
            {
                "tool_id": 1,
                "name": "Email Sender",
                "description": "Send SMTP messages and notification emails.",
            },
            {
                "tool_id": 2,
                "name": "Web Search",
                "description": "Search web pages and retrieve relevant results.",
            },
            {
                "tool_id": 3,
                "name": "Database Query",
                "description": "Run SQL queries against business databases.",
            },
        ],
        skill_catalog=[
            {
                "skill_id": 10,
                "name": "document-summary",
                "description": "Summarize PDF documents and long reports.",
            },
            {
                "skill_id": 11,
                "name": "web-research-brief",
                "description": "Research web pages and produce a concise brief.",
            },
        ],
    )

    payload = _loads(tool(query="web search"))

    assert payload["agent_id"] == 202
    assert [item["tool_id"] for item in payload["tools"]][:2] == [2, 1]
    assert payload["skills"][0]["skill_id"] == 11
    assert all("score" in item and "reason" in item for item in payload["tools"])
    assert payload["tools"][0]["score"] >= payload["tools"][1]["score"]


def test_nl2agent_search_web_mcps_scores_registry_and_community_catalogs():
    tool = get_search_web_mcps_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        registry_results=[
            {
                "name": "GitHub Repository MCP",
                "description": "Manage issues, pull requests, and repository automation.",
                "url": "https://example.com/github",
                "transport": "stdio",
            }
        ],
        community_results=[
            {
                "name": "Calendar MCP",
                "description": "Read and update calendar events.",
                "url": "https://example.com/calendar",
                "transport": "sse",
            }
        ],
    )

    payload = _loads(tool(query="github repository"))

    assert payload["agent_id"] == 202
    assert all(item["agent_id"] == 202 for item in payload["items"])
    assert payload["items"][0]["name"] == "GitHub Repository MCP"
    assert payload["items"][0]["source"] == "registry"
    assert payload["items"][0]["score"] >= payload["items"][1]["score"]


def test_registry_mcp_normalization_preserves_declared_configuration_without_secret_defaults():
    item = normalize_mcp_candidate("registry", {
        "server": {
            "name": "github",
            "remotes": [{
                "url": "https://{region}.example/${tenant}/mcp",
                "type": "streamable-http",
                "variables": [
                    {"name": "region", "isRequired": True, "value": "us"},
                    {"name": "tenant", "isRequired": True},
                ],
                "headers": [{
                    "name": "Authorization",
                    "isRequired": True,
                    "isSecret": True,
                    "value": "stored-secret",
                }],
            }],
            "packages": [{
                "registryType": "npm",
                "identifier": "@example/github-mcp",
                "runtimeHint": "npx",
                "transport": {"type": "stdio"},
                "runtimeArguments": [{"type": "positional", "value": "-y"}],
                "packageArguments": [{
                    "type": "named", "name": "--mode", "valueHint": "safe", "isRequired": True,
                }],
                "environmentVariables": [{
                    "name": "GITHUB_TOKEN", "isRequired": True, "isSecret": True,
                    "value": "stored-secret",
                }],
            }],
        }
    })

    remote = item["install_options"][0]
    assert remote["server_url_template"] == "https://{region}.example/${tenant}/mcp"
    assert remote["transport"] == "streamable-http"
    assert next(field for field in remote["fields"] if field["name"] == "region")["default"] == "us"
    assert next(field for field in remote["fields"] if field["name"] == "Authorization")["default"] is None

    package = item["install_options"][1]
    assert package["package_identifier"] == "@example/github-mcp"
    assert package["runtime_hint"] == "npx"
    assert next(field for field in package["fields"] if field["name"] == "GITHUB_TOKEN")["default"] is None
    assert next(field for field in package["fields"] if field["name"] == "--mode")["placeholder"] == "safe"


def test_community_mcp_normalization_applies_overrides_and_nested_registry_metadata():
    item = normalize_mcp_candidate("community", {
        "communityId": 55,
        "name": "community-github",
        "serverUrl": "https://{workspace}.community.example/mcp",
        "transportType": "sse",
        "registryJson": {
            "server": {
                "name": "registry-name",
                "remotes": [{
                    "url": "https://registry.example/mcp",
                    "variables": [{"name": "workspace", "isRequired": True}],
                }],
            }
        },
    })

    assert item["recommendation_id"] == "community:55"
    option = item["install_options"][0]
    assert option["option_id"] == "community-remote"
    assert option["server_url_template"] == "https://{workspace}.community.example/mcp"
    assert option["transport"] == "sse"
    assert [field["name"] for field in option["fields"]] == ["workspace"]


def test_incomplete_community_options_require_explicit_configuration():
    remote = normalize_mcp_candidate("community", {
        "communityId": 1, "name": "remote", "transportType": "url",
    })["install_options"][0]
    assert remote["fields"][0]["name"] == "server_url"
    assert remote["fields"][0]["required"] is True

    container = normalize_mcp_candidate("community", {
        "communityId": 2, "name": "container", "transportType": "container",
    })["install_options"][0]
    assert {field["name"] for field in container["fields"]} == {"port", "config_json"}

    configured_container = normalize_mcp_candidate("community", {
        "communityId": 3,
        "name": "configured-container",
        "transportType": "container",
        "configJson": {
            "mcpServers": {
                "configured-container": {
                    "command": "npx",
                    "args": ["package"],
                    "env": {"API_TOKEN": None, "REGION": "eu"},
                }
            }
        },
    })["install_options"][0]
    token = next(field for field in configured_container["fields"] if field["name"] == "API_TOKEN")
    region = next(field for field in configured_container["fields"] if field["name"] == "REGION")
    assert token["required"] is True and token["secret"] is True and token["default"] is None
    assert region["default"] == "eu"


def test_nl2agent_search_web_skills_scores_skill_name_candidates():
    tool = get_search_web_skills_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        official_skills=[
            {
                "skill_id": 12,
                "skill_name": "code-review",
                "name": "Code Review",
                "description": "Review pull requests and source changes.",
                "tags": ["code", "review"],
            },
            {
                "skill_id": 13,
                "skill_name": "invoice-reader",
                "name": "Invoice Reader",
                "description": "Extract totals from invoices.",
                "tags": ["finance"],
            },
        ],
    )

    payload = _loads(tool(query="code review"))

    assert payload["agent_id"] == 202
    assert payload["items"][0]["skill_id"] == 12
    assert payload["items"][0]["score"] >= payload["items"][1]["score"]


def test_nl2agent_search_local_resources_cache_hit_returns_without_rescoring(monkeypatch):
    score_calls = []

    def fake_score_candidates(candidates, query, name_field, score_field="score"):
        score_calls.append((query, name_field))
        return [{**candidate, score_field: 1.0, "reason": "matched"} for candidate in candidates]

    monkeypatch.setattr(local_tool_module, "_score_candidates", fake_score_candidates)
    tool = get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        tool_catalog=[{"tool_id": 1, "name": "Web Search", "description": "Search the web."}],
        skill_catalog=[{"skill_id": 7, "name": "web-research", "description": "Research web pages."}],
    )

    first = tool(query="web search")
    second = tool(query="  Web Search  ")

    assert first == second
    assert len(score_calls) == 2


def test_constructing_all_search_tools_preserves_each_tool_context():
    local_tool = get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        tenant_id="tenant_1",
        tool_catalog=[{"tool_id": 1, "name": "Document Reader", "description": "Read DOC files."}],
        skill_catalog=[{"skill_id": 7, "name": "ppt-builder", "description": "Generate PPT slides."}],
    )
    mcp_tool = get_search_web_mcps_tool(
        agent_id=101,
        draft_agent_id=202,
        tenant_id="tenant_1",
        registry_results=[{"name": "GitHub MCP", "description": "Repository tools."}],
        community_results=[],
    )
    skill_tool = get_search_web_skills_tool(
        agent_id=101,
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=[{"skill_id": 9, "skill_name": "code-review", "description": "Review code."}],
    )

    assert _loads(local_tool(query="document"))["tools"][0]["tool_id"] == 1
    assert _loads(mcp_tool(query="github"))["items"][0]["name"] == "GitHub MCP"
    assert _loads(skill_tool(query="code review"))["items"][0]["skill_id"] == 9


def test_search_tool_instances_are_isolated_between_sessions():
    first = get_search_local_resources_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        tool_catalog=[{"tool_id": 1, "name": "First Tool", "description": "alpha"}],
        skill_catalog=[],
    )
    second = get_search_local_resources_tool(
        draft_agent_id=303,
        tenant_id="tenant_1",
        tool_catalog=[{"tool_id": 2, "name": "Second Tool", "description": "beta"}],
        skill_catalog=[],
    )

    assert _loads(first(query="alpha"))["tools"][0]["tool_id"] == 1
    assert _loads(second(query="beta"))["tools"][0]["tool_id"] == 2
    assert first.context is not second.context
