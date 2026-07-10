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
    nl2agent_search_local_resources,
)
from nexent.core.tools.nl2agent.search_web_mcps_tool import (
    get_search_web_mcps_tool,
    nl2agent_search_web_mcps,
)
from nexent.core.tools.nl2agent.search_web_skills_tool import (
    get_search_web_skills_tool,
    nl2agent_search_web_skills,
)


@pytest.fixture(autouse=True)
def reset_nl2agent_state():
    context_module._context = None
    context_module._search_cache.clear()
    yield
    context_module._context = None
    context_module._search_cache.clear()


def _loads(raw_result):
    return json.loads(raw_result)


@pytest.mark.parametrize(
    ("initializer", "tool_func", "catalog_kwargs", "query"),
    [
        (
            get_search_local_resources_tool,
            nl2agent_search_local_resources,
            {"tool_catalog": [], "skill_catalog": []},
            "web search",
        ),
        (
            get_search_web_mcps_tool,
            nl2agent_search_web_mcps,
            {"registry_results": [], "community_results": []},
            "github",
        ),
        (
            get_search_web_skills_tool,
            nl2agent_search_web_skills,
            {"official_skills": []},
            "code review",
        ),
    ],
)
def test_nl2agent_search_tools_require_tenant_context(initializer, tool_func, catalog_kwargs, query):
    initializer(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id=None,
        language="en",
        **catalog_kwargs,
    )

    assert _loads(tool_func(query=query)) == {"error": "NL2AGENT session context not initialized."}


def test_nl2agent_search_local_resources_returns_empty_results_for_empty_catalogs():
    get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        tool_catalog=[],
        skill_catalog=[],
    )

    assert _loads(nl2agent_search_local_resources(query="web search")) == {
        "agent_id": 202,
        "tools": [],
        "skills": [],
    }


def test_nl2agent_search_web_mcps_returns_empty_results_for_empty_catalogs():
    get_search_web_mcps_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        registry_results=[],
        community_results=[],
    )

    assert _loads(nl2agent_search_web_mcps(query="github")) == {"agent_id": 202, "items": []}


def test_nl2agent_search_web_skills_returns_empty_results_for_empty_catalog():
    get_search_web_skills_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        official_skills=[],
    )

    assert _loads(nl2agent_search_web_skills(query="code review")) == {"agent_id": 202, "items": []}


def test_nl2agent_search_local_resources_scores_and_ranks_catalog_candidates():
    get_search_local_resources_tool(
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

    payload = _loads(nl2agent_search_local_resources(query="web search"))

    assert payload["agent_id"] == 202
    assert [item["tool_id"] for item in payload["tools"]][:2] == [2, 1]
    assert payload["skills"][0]["skill_id"] == 11
    assert all("score" in item and "reason" in item for item in payload["tools"])
    assert payload["tools"][0]["score"] >= payload["tools"][1]["score"]


def test_nl2agent_search_web_mcps_scores_registry_and_community_catalogs():
    get_search_web_mcps_tool(
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

    payload = _loads(nl2agent_search_web_mcps(query="github repository"))

    assert payload["agent_id"] == 202
    assert payload["items"][0]["name"] == "GitHub Repository MCP"
    assert payload["items"][0]["source"] == "registry"
    assert payload["items"][0]["score"] >= payload["items"][1]["score"]


def test_nl2agent_search_web_skills_scores_skill_name_candidates():
    get_search_web_skills_tool(
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

    payload = _loads(nl2agent_search_web_skills(query="code review"))

    assert payload["agent_id"] == 202
    assert payload["items"][0]["skill_id"] == 12
    assert payload["items"][0]["score"] >= payload["items"][1]["score"]


def test_nl2agent_search_local_resources_cache_hit_returns_without_rescoring(monkeypatch):
    score_calls = []

    def fake_score_candidates(candidates, query, name_field, score_field="score"):
        score_calls.append((query, name_field))
        return [{**candidate, score_field: 1.0, "reason": "matched"} for candidate in candidates]

    monkeypatch.setattr(local_tool_module, "_score_candidates", fake_score_candidates)
    get_search_local_resources_tool(
        agent_id=101,
        draft_agent_id=202,
        user_id="user_1",
        tenant_id="tenant_1",
        language="en",
        tool_catalog=[{"tool_id": 1, "name": "Web Search", "description": "Search the web."}],
        skill_catalog=[{"skill_id": 7, "name": "web-research", "description": "Research web pages."}],
    )

    first = nl2agent_search_local_resources(query="web search")
    second = nl2agent_search_local_resources(query="  Web Search  ")

    assert first == second
    assert len(score_calls) == 2
