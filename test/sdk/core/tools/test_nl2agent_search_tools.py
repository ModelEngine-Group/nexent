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
from nexent.core.tools.nl2agent._context import (
    _score_candidates,
    canonical_search_query,
    normalize_search_keywords,
    online_recommendation_batch_id,
)
from nexent.core.tools.nl2agent.search_local_resources_tool import (
    get_search_local_resources_tool as _get_search_local_resources_tool,
)
from nexent.core.tools.nl2agent.search_web_mcps_tool import (
    get_search_web_mcps_tool as _get_search_web_mcps_tool,
    normalize_mcp_candidate,
)
from nexent.core.tools.nl2agent.search_web_skills_tool import (
    get_search_web_skills_tool as _get_search_web_skills_tool,
)


def get_search_local_resources_tool(**kwargs):
    kwargs.setdefault("requirements_confirmed", True)
    return _get_search_local_resources_tool(**kwargs)


def get_search_web_mcps_tool(**kwargs):
    kwargs.setdefault("requirements_confirmed", True)
    return _get_search_web_mcps_tool(**kwargs)


def get_search_web_skills_tool(**kwargs):
    kwargs.setdefault("requirements_confirmed", True)
    return _get_search_web_skills_tool(**kwargs)


@pytest.fixture(autouse=True)
def reset_nl2agent_state():
    context_module._search_cache.clear()
    yield
    context_module._search_cache.clear()


def _loads(raw_result):
    return json.loads(raw_result)


def test_search_keyword_normalization_handles_mixed_text_and_equivalent_order():
    assert normalize_search_keywords("通过 DOCX，大纲生成 + PPT；docx") == [
        "docx",
        "大纲生成",
        "ppt",
    ]
    assert canonical_search_query("PPT, DOCX") == canonical_search_query(" docx ppt ")


def test_online_batch_ids_are_stable_and_session_scoped():
    first = online_recommendation_batch_id(
        202, "mcp", "DOCX, ppt", ["registry:b", "registry:a"]
    )
    equivalent = online_recommendation_batch_id(
        202, "mcp", "ppt docx", ["registry:a", "registry:b"]
    )

    assert first == equivalent
    assert first != online_recommendation_batch_id(
        303, "mcp", "ppt docx", ["registry:a", "registry:b"]
    )
    assert first != online_recommendation_batch_id(
        202, "skill", "ppt docx", ["registry:a", "registry:b"]
    )


def test_candidate_scoring_uses_keyword_or_matching_and_filters_weak_results():
    candidates = [
        {"name": "DOCX PPT Builder", "description": "Generate presentation slides."},
        {"name": "DOCX Reader", "description": "Extract document text."},
        {"name": "Calendar", "description": "Schedule meetings."},
    ]

    scored = _score_candidates(candidates, "docx, ppt", "name")

    assert [item["name"] for item in scored] == ["DOCX PPT Builder", "DOCX Reader"]
    assert scored[0]["score"] > scored[1]["score"]
    assert scored[0]["reason"] == "Matched keywords: docx, ppt"
    assert _score_candidates(candidates, "quantum", "name") == []


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


@pytest.mark.parametrize(
    ("initializer", "catalog_kwargs"),
    [
        (_get_search_local_resources_tool, {"tool_catalog": [], "skill_catalog": []}),
        (_get_search_web_mcps_tool, {"registry_results": [], "community_results": []}),
        (_get_search_web_skills_tool, {"official_skills": []}),
    ],
)
def test_nl2agent_search_tools_require_confirmed_requirements(
    initializer, catalog_kwargs
):
    tool = initializer(
        draft_agent_id=202,
        tenant_id="tenant_1",
        requirements_confirmed=False,
        **catalog_kwargs,
    )

    assert _loads(tool(query="document")) == {
        "error": "NL2AGENT requirements are not confirmed for this draft."
    }


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
    assert _loads(tool(query="SEARCH, WEB"))["recommendation_batch_id"] == first[
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

    result = _loads(tool(query="github"))
    assert result["agent_id"] == 202
    assert result["items"] == []
    assert result["recommendation_batch_id"].startswith("online_")


def test_nl2agent_search_web_skills_returns_empty_results_for_empty_catalog():
    tool = get_search_web_skills_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        official_skills=[],
    )

    result = _loads(tool(query="code review"))
    assert result["agent_id"] == 202
    assert result["items"] == []
    assert result["recommendation_batch_id"].startswith("online_")


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
    assert [item["tool_id"] for item in payload["tools"]] == [2]
    assert payload["skills"][0]["skill_id"] == 11
    assert all("score" in item and "reason" in item for item in payload["tools"])
    assert len(payload["tools"]) + len(payload["skills"]) <= 5


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
    assert len(payload["items"]) == 1


def test_mcp_search_deduplicates_registry_and_community_names_with_registry_precedence():
    tool = get_search_web_mcps_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        registry_results=[
            {"name": "Document Reader", "description": "Read DOCX files."},
        ],
        community_results=[
            {"communityId": 9, "name": " document reader ", "description": "Duplicate."},
        ],
    )

    payload = _loads(tool(query="document reader"))

    assert len(payload["items"]) == 1
    assert payload["items"][0]["source"] == "registry"


def test_mcp_search_cache_survives_tool_rebuild_for_equivalent_keyword_sets():
    first = get_search_web_mcps_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        registry_results=[{"name": "DOCX Parser", "description": "Read documents."}],
        community_results=[],
    )
    rebuilt = get_search_web_mcps_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        registry_results=[{"name": "PPT Generator", "description": "Build slides."}],
        community_results=[],
    )

    first_result = first(query="docx ppt")
    rebuilt_result = rebuilt(query="PPT, DOCX")

    assert rebuilt_result == first_result


def test_mcp_search_cache_is_isolated_by_tenant_and_draft():
    first = get_search_web_mcps_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        registry_results=[{"name": "First Document MCP", "description": "Read documents."}],
        community_results=[],
    )
    second = get_search_web_mcps_tool(
        draft_agent_id=303,
        tenant_id="tenant_2",
        registry_results=[{"name": "Second Document MCP", "description": "Read documents."}],
        community_results=[],
    )

    first_payload = _loads(first(query="document"))
    second_payload = _loads(second(query="document"))

    assert first_payload["items"][0]["name"] == "First Document MCP"
    assert second_payload["items"][0]["name"] == "Second Document MCP"


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
                "status": "installable",
            },
            {
                "skill_id": 13,
                "skill_name": "invoice-reader",
                "name": "Invoice Reader",
                "description": "Extract totals from invoices.",
                "tags": ["finance"],
                "status": "installable",
            },
        ],
    )

    payload = _loads(tool(query="code review"))

    assert payload["agent_id"] == 202
    assert payload["items"][0]["skill_id"] == 12
    assert len(payload["items"]) == 1


def test_web_skill_search_accepts_backend_name_field_and_searches_metadata():
    tool = get_search_web_skills_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=[
            {
                "skill_id": 20,
                "name": "presentation-builder",
                "description": "Create polished slide decks.",
                "tags": ["ppt", "design"],
                "status": "installable",
            },
            {
                "skill_id": 21,
                "name": "invoice-reader",
                "description": "Extract finance totals.",
                "tags": ["accounting"],
                "status": "installable",
            },
        ],
    )

    assert _loads(tool(query="presentation"))["items"][0]["skill_id"] == 20
    assert _loads(tool(query="slide"))["items"][0]["skill_id"] == 20
    assert _loads(tool(query="ppt"))["items"][0]["skill_id"] == 20


def test_web_skill_search_defensively_filters_non_installable_statuses():
    tool = get_search_web_skills_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=[
            {"skill_id": 1, "name": "document-ready", "status": "installable"},
            {"skill_id": 2, "name": "document-installed", "status": "installed"},
            {
                "skill_id": 3,
                "name": "document-missing",
                "status": "resource_missing",
            },
            {"skill_id": 4, "name": "document-unknown"},
        ],
    )

    payload = _loads(tool(query="document"))

    assert [item["skill_id"] for item in payload["items"]] == [1]


def test_web_skill_cache_changes_when_catalog_fingerprint_changes():
    first_tool = get_search_web_skills_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=[
            {"skill_id": 1, "name": "first-document-skill", "status": "installable"}
        ],
    )
    second_tool = get_search_web_skills_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=[
            {"skill_id": 2, "name": "second-document-skill", "status": "installable"}
        ],
    )

    first = _loads(first_tool(query="document"))
    second = _loads(second_tool(query="DOCUMENT"))

    assert [item["skill_id"] for item in first["items"]] == [1]
    assert [item["skill_id"] for item in second["items"]] == [2]


def test_local_search_limits_tools_and_skills_to_five_combined():
    tool = get_search_local_resources_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        tool_catalog=[
            {"tool_id": index, "name": f"Document Tool {index}", "description": "Document processing."}
            for index in range(1, 5)
        ],
        skill_catalog=[
            {"skill_id": index, "name": f"Document Skill {index}", "description": "Document processing."}
            for index in range(10, 14)
        ],
    )

    payload = _loads(tool(query="document"))

    assert len(payload["tools"]) + len(payload["skills"]) == 5


def test_web_skill_search_deduplicates_ids_and_normalized_names():
    tool = get_search_web_skills_tool(
        draft_agent_id=202,
        tenant_id="tenant_1",
        official_skills=[
            {
                "skill_id": 1,
                "skill_name": "docx-reader",
                "description": "Read DOCX.",
                "status": "installable",
            },
            {
                "skill_id": 1,
                "skill_name": "docx-reader-copy",
                "description": "Duplicate ID.",
                "status": "installable",
            },
            {
                "skill_id": 2,
                "skill_name": "DOCX Reader",
                "description": "Duplicate name.",
                "status": "installable",
            },
        ],
    )

    payload = _loads(tool(query="docx reader"))

    assert len(payload["items"]) == 1


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
        official_skills=[{
            "skill_id": 9,
            "skill_name": "code-review",
            "description": "Review code.",
            "status": "installable",
        }],
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
