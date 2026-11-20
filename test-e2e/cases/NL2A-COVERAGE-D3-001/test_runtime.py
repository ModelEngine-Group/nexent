# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise versioned resource cards and completion through the real creator runtime."""

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import asyncio
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlparse

import pytest
from redis import Redis
from sqlalchemy import inspect, select

from management.db.models import AgentInfo
from management.db.tool.models import ToolInstance
from management.services.mcp import service as mcp_service
from model_controls.runtime import runtime_fixture
from management.services.agent import nl2agent as nl2agent_service, nl2agent_state_service
from services.nl2agent_state_service import ResourceScope
from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
from management.services.conversation import nl2agent_resource_index as storage
from management.services.agent.nl2agent_tools import ResourceInstallationOption

pytestmark = [pytest.mark.case_id("NL2A-COVERAGE-D3-001"), pytest.mark.stage("D3")]
PATH = "/api/agent/nl2agent/run"


def assessed_check(state, key, accepted):
    from services.nl2agent_resource_flow import _candidates_in_batch

    return {"requirement_id": key, "accepted": accepted, "assessments": [
        {"candidate_ref": item["candidate_ref"], "satisfies": item["candidate_ref"] in accepted,
         "reason": "The declared capability meets the requirement." if item["candidate_ref"] in accepted
                   else "The declaration does not meet the required capability or source."}
        for item in _candidates_in_batch(state["requirements"][key])
    ]}


def test_search_alternatives_runtime(monkeypatch):
    from services import nl2agent_resource_flow as flow

    catalog = [{
        "candidate_ref": f"tool:{index}", "resource_type": "tool", "source": "LOCAL_TOOL",
        "name": "search_provider", "description": "Search public web background information and return sources.",
        "names": ["search_provider"], "labels": ["search"],
        "descriptions": ["Search public web background information and return sources."],
        "interfaces": [], "inputs": {}, "installed": True, "quality": 1.0,
        "config": [], "form_kind": "TOOL_CONFIG",
    } for index, name in enumerate([
        "exa_search", "linkup_search", "tavily_search", "deepseek_search",
        "alternate_search_a", "alternate_search_b", "alternate_search_c",
    ], 701)]
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    with owned_runtime(monkeypatch) as (runtime, redis):
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()

        def verify():
            snapshot = json.loads(redis.get(_state_key(runtime)))
            offered = flow._candidates_in_batch(snapshot["requirements"]["r1"])
            assert [row["candidate_ref"] for row in snapshot["requirements"]["r1"]["installed"]] == ["tool:701", "tool:702", "tool:703"]
            check = assessed_check(snapshot, "r1", [item["candidate_ref"] for item in offered])
            # A missing assessment must not advance or alter the batch.
            from contracts.nl2agent_resources import VerificationCheck
            invalid = {**check, "assessments": check["assessments"][:-1]}
            with pytest.raises(flow.ResourceStateError, match="verification_assessments_incomplete"):
                flow.validate_checks(snapshot, snapshot["batch"]["id"], [VerificationCheck(**invalid)])
            assert json.loads(redis.get(_state_key(runtime))) == snapshot
            return (f"<code>print(nl2a_verify_requirements(verification_batch_id={snapshot['batch']['id']!r}, "
                    f"checks={[check]!r}))</code>")

        req = [{"query": "Search public web background information", "search_queries": {
            "zh": "联网搜索公开背景资料", "en": "web search public background information"}}]
        cid, events = post(runtime, "Find web search alternatives.", [
            f"<code>print(nl2a_discover_requirements(requirements={req!r}))</code>", verify,
        ])
        card = get_card(events)
        assert card["subtype"] == "installed_resource_binding"
        expected = {"tool:701", "tool:702", "tool:703"}
        assert {item["candidate_ref"] for item in card["requirements"][0]["covered_resources"]} == expected
        assert {item["candidate"]["candidate_ref"] for item in card["resources"]} == expected
        assert sum(item["recommendation"] == "recommended" for item in card["resources"]) == 1
        other_cid, other_events = post(runtime, "Find alternatives in another conversation.", [
            f"<code>print(nl2a_discover_requirements(requirements={req!r}))</code>", verify,
        ])
        other_card = get_card(other_events)
        assert other_cid != cid
        other_state = redis.get(_state_key(runtime, other_cid))
        # An older conversation writes after the newer card was issued.
        _, events = post(runtime, action(card, "return_requirements"), [], cid)
        clarification = get_card(events)
        assert clarification["subtype"] == "requirement_clarification"
        edits = [{"requirement_id": row["requirement_id"], "query": row["query"]}
                 for row in clarification["requirements"]]
        _, events = post(runtime, action(clarification, "confirm_requirements", requirements=edits), [], cid)
        assert get_card(events)["subtype"] == "installed_resource_binding"
        assert json.loads(redis.get(_state_key(runtime, cid)))["submitted_batches"] == {}
        saved = json.loads(redis.get(_state_key(runtime, cid)))["requirements"]["r1"]["candidate_assessments"]
        assert set(saved) == expected
        assert all(item["satisfies"] and item["reason"] for item in saved.values())
        assert redis.get(_state_key(runtime, other_cid)) == other_state
        _, events = post(runtime, action(other_card, "return_requirements"), [], other_cid)
        other_clarification = get_card(events)
        assert other_clarification["subtype"] == "requirement_clarification"
        _, events = post(runtime, action(other_clarification, "confirm_requirements", requirements=edits), [], other_cid)
        assert get_card(events)["subtype"] == "installed_resource_binding"
        assert runtime.draft() == before


def test_bilingual_recall_and_edited_requirement(monkeypatch):
    def declaration(ref, name, description):
        return {
            "candidate_ref": ref, "resource_type": "tool", "source": "LOCAL_TOOL", "name": name,
            "description": description, "names": [name], "labels": [], "descriptions": [description],
            "interfaces": [], "installed": True, "quality": 1.0,
        }
    catalog = [
        declaration("tool:701", "deepseek_search", "web search"),
        declaration("tool:702", "knowledge_base_search", "search internal knowledge, not public web search"),
        declaration("tool:703", "公开网页读取", "公开网页读取"),
    ]
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    requirements = [
        {"query": "联网搜索", "search_queries": {"zh": "联网搜索", "en": "web search"}},
        {"query": "Read public webpages", "search_queries": {"zh": "公开网页读取", "en": "Read public webpages"}},
        {"query": "ERP库存写入", "search_queries": {"zh": "ERP库存写入", "en": "write ERP inventory"}},
    ]
    with owned_runtime(monkeypatch) as (runtime, redis):
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()
        def verify(edited=False):
            state = json.loads(redis.get(_state_key(runtime)))
            checks = []
            expected = {"r1": [] if edited else ["tool:701"], "r2": ["tool:703"], "r3": []}
            for key in state["batch"]["requirements"]:
                row = state["requirements"][key]
                refs = [item["candidate_ref"] for item in row["installed"] + row["installable"]]
                assert len(refs) == len(set(refs))
                if key == "r1" and not edited:
                    assert {"tool:701", "tool:702"} <= set(refs)
                if key == "r2":
                    assert "tool:703" in refs
                checks.append(assessed_check(state, key, expected[key]))
            return f"<code>print(nl2a_verify_requirements(verification_batch_id={state['batch']['id']!r}, checks={checks!r}))</code>"
        cid, events = post(runtime, "Search public web and read pages; also write ERP inventory.", [
            f"<code>print(nl2a_discover_requirements(requirements={requirements!r}))</code>", verify,
        ])
        card = get_card(events)
        assert card["subtype"] == "requirement_coverage"
        rows = card["requirements"]
        assert [row["coverage_status"] for row in rows] == ["covered", "covered", "uncovered"]
        assert [item["candidate_ref"] for item in rows[0]["covered_resources"]] == ["tool:701"]
        unchanged = json.loads(redis.get(_state_key(runtime)))["requirements"]["r2"]
        legacy = json.loads(redis.get(_state_key(runtime)))
        legacy["requirements"]["r3"].pop("search_queries")
        redis.set(_state_key(runtime), json.dumps(legacy))
        edits = [{"requirement_id": row["requirement_id"], "query": row["query"]} for row in rows]
        edits[0]["query"] = "搜索实时新闻"
        def prepare():
            state = json.loads(redis.get(_state_key(runtime)))
            assert state["requirements"]["r1"]["query"] == "搜索实时新闻"
            assert "search_queries" not in state["requirements"]["r1"]
            assert "installed" not in state["requirements"]["r1"]
            assert "installed" not in state["requirements"]["r3"]
            assert state["requirements"]["r2"] == unchanged
            return (
                '<code>print(nl2a_discover_requirements(search_queries={'
                '"r1":{"zh":"搜索实时新闻","en":"search current news"},'
                '"r3":{"zh":"ERP库存写入","en":"write ERP inventory"}}))</code>'
            )
        _, events = post(runtime, action(card, "confirm_requirements", requirements=edits), [
            "<code>print(nl2a_discover_requirements())</code>", prepare, lambda: verify(True),
        ], cid)
        assert events, json.loads(redis.get(_state_key(runtime)))
        edited_card = get_card(events)
        assert edited_card["requirements"][0]["query"] == "搜索实时新闻"
        assert edited_card["requirements"][0]["coverage_status"] == "uncovered"
        assert edited_card["requirements"][1]["coverage_status"] == "covered"
        assert json.loads(redis.get(_state_key(runtime)))["requirements"]["r3"]["search_queries"] == requirements[2]["search_queries"]
        assert runtime.draft() == before


@pytest.mark.parametrize("query,pair,correct,unrelated", [
    ("生成图片", {"zh": "生成图片", "en": "generate image"},
     ("image_generator", "Generate an image from a text prompt."),
     ("analyze_image", "Analyze an existing image and return its description.")),
    ("查询列车经停站", {"zh": "查询列车经停站", "en": "query train route stops"},
     ("train_routes", "Query stops on a train route."),
     ("send_email", "Send an email to recipients with a subject and body.")),
    ("使用知识库检索工具查询已关联的活动方案、品牌介绍和往期素材",
     {"zh": "知识库检索", "en": "knowledge base search"},
     (KnowledgeBaseSearchTool.name, KnowledgeBaseSearchTool.description),
     ("generate_fishbone_diagram", "Generate a fishbone diagram chart.")),
])
def test_lexical_precision_runtime(monkeypatch, query, pair, correct, unrelated):
    from services import nl2agent_semantic_retrieval as semantic

    catalog = [{
        "candidate_ref": f"tool:{index}", "resource_type": "tool", "source": "LOCAL_TOOL",
        "name": name, "description": description, "names": [name], "descriptions": [description],
        "labels": [], "interfaces": [], "installed": True, "quality": 1.0,
    } for index, (name, description) in enumerate((correct, unrelated), 701)]
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(semantic, "resolve_model", AsyncMock(return_value=None))
    with owned_runtime(monkeypatch) as (runtime, redis):
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()

        def verify():
            state = json.loads(redis.get(_state_key(runtime)))
            row = state["requirements"]["r1"]
            assert row["query"] == query
            assert [item["candidate_ref"] for item in row["installed"]] == ["tool:701"]
            assert row["installable"] == []
            checks = [assessed_check(state, "r1", ["tool:701"])]
            return (f"<code>print(nl2a_verify_requirements(verification_batch_id={state['batch']['id']!r}, "
                    f"checks={checks!r}))</code>")

        requirements = [{"query": query, "search_queries": pair}]
        _, events = post(runtime, query, [
            f"<code>print(nl2a_discover_requirements(requirements={requirements!r}, purpose='recommend'))</code>",
            verify,
        ])
        card = get_card(events)
        assert card["requirements"][0]["query"] == query
        assert [row["candidate_ref"] for row in card["requirements"][0]["covered_resources"]] == ["tool:701"]
        assert runtime.draft() == before


def get_card(events):
    cards = [json.loads(event["content"]) for event in events if event["type"] == "nl2a"]
    assert len(cards) == 1, events
    return cards[0]


def action(card, name, **result):
    return json.dumps({
        "type": "nl2agent_card_action", "subtype": card["subtype"], "agent_id": card["agent_id"],
        "action": name,
        "result": {"card_id": card["card_id"], "state_version": card["state_version"], **result},
    })


@contextmanager
def owned_runtime(monkeypatch):
    from management.configuration import runtime as configuration

    # The owned test app has no production configuration startup lifecycle.
    config = configuration.SystemConfigurationRuntime(loader=AsyncMock(return_value={}))
    config.store_snapshot(configuration.DEFAULT_CATALOG.defaults)
    monkeypatch.setattr(configuration, "_process_runtime", config)
    with Redis.from_url(os.environ["NEXENT_TEST_NL2AGENT_REDIS_URL"], decode_responses=True) as redis:
        redis.ping()
        monkeypatch.setattr(nl2agent_state_service, "get_redis_client", lambda: redis)
        from services import nl2agent_retrieval_progress, nl2agent_semantic_retrieval
        monkeypatch.setattr(nl2agent_retrieval_progress, "get_redis_client", lambda: redis)
        runtime = None
        try:
            with runtime_fixture(monkeypatch) as runtime:
                with runtime.storage["sessions"]() as session:
                    # This journey tests resource flow, not constrained-context compaction.
                    from management.db.model.models import ModelRecord
                    for model in session.scalars(select(ModelRecord).where(ModelRecord.model_type == "llm")):
                        model.context_window_tokens = 128000
                        model.max_input_tokens = 120000
                    for agent in session.scalars(select(AgentInfo).where(AgentInfo.system_key == "nl2agent_main")):
                        agent.max_steps = 8
                yield runtime, redis
        finally:
            if runtime is not None:
                scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
                owner = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
                keys = list(redis.scan_iter(owner.legacy_key + "*"))
                if keys:
                    redis.delete(*keys)
                assert not list(redis.scan_iter(owner.legacy_key + "*"))
                assert not inspect(runtime.storage["engine"]).has_schema(runtime.storage["schema"])
                assert not runtime.provider.thread.is_alive()
                for run in runtime.runs:
                    assert run.thread_future.done()
                    mcp = urlparse(run.mcp_host[0]["url"])
                    with socket.socket() as client:
                        client.settimeout(1)
                        assert client.connect_ex((mcp.hostname, mcp.port)) != 0


def _state_key(runtime, conversation_id=None):
    if conversation_id is None:
        conversation_id = runtime.runs[-1].mcp_host[0]["headers"]["X-Nexent-NL2Agent-Conversation-ID"]
    return ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id,
                         str(conversation_id), "").key


def post(runtime, query, actions, conversation_id=None, **values):
    actions = iter(actions)
    def respond(body):
        if not body.get("stream"):
            return "Fixture turn"
        value = next(actions)
        return value() if callable(value) else value
    runtime.provider.responder = respond
    response = runtime.post(PATH, query=query, conversation_id=conversation_id, **values)
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events, (dict(response.headers), response.text)
    assert not any(item["type"] == "error" for item in events), events
    assert next(actions, None) is None
    return int(response.headers["conversation_id"]), events


def test_coverage_return_and_generation(monkeypatch):
    installed = {
        "candidate_ref": "tool:9", "resource_type": "tool", "source": "LOCAL_TOOL",
        "name": "weather", "description": "weather", "names": ["weather"], "labels": [],
        "descriptions": ["weather"], "interfaces": [], "inputs": {},
        "installed": True, "quality": 1.0, "form_kind": "TOOL_CONFIG", "config": [],
    }
    repository_mcp = {
        "candidate_ref": "tenant_mcp_repository:3", "resource_type": "mcp_server",
        "source": "TENANT_MCP_REPOSITORY", "name": "12306", "description": "Train ticket availability",
        "names": ["12306"], "labels": [], "descriptions": ["Train ticket availability"], "interfaces": [],
        "installed": False, "quality": 1.0,
    }
    installed_tools = [installed]
    mcp_record = {"market_id": 3, "enabled": False, "mcp_name": "12306 local"}
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=installed_tools))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog",
                        AsyncMock(return_value=[repository_mcp]))
    monkeypatch.setattr(mcp_service, "list_visible_mcp_records", lambda *_: ([mcp_record], []))

    with owned_runtime(monkeypatch) as (runtime, redis):
        # This journey generates the first prompt, rather than replacing an existing one.
        with runtime.storage["sessions"]() as session:
            draft = session.scalars(select(AgentInfo).where(AgentInfo.agent_id == runtime.agent_id)).one()
            draft.prompt = ""
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()
        def verify():
            state = json.loads(redis.get(_state_key(runtime)))
            batch = state["batch"]
            checks = []
            accepted = {"r1": "tool:9", "r3": "tool:17" if mcp_record["enabled"] else repository_mcp["candidate_ref"]}
            if mcp_record["enabled"]:
                assert batch["requirements"] == ["r3"]
            for key in batch["requirements"]:
                row = state["requirements"][key]
                refs = [candidate["candidate_ref"] for candidate in row["installed"] + row["installable"]]
                checks.append(assessed_check(state, key, [ref for ref in refs if ref == accepted.get(key)]))
            return f"<code>print(nl2a_verify_requirements(verification_batch_id={batch['id']!r}, checks={checks!r}))</code>"

        weather_query = "Check whether local outdoor conditions meet the required wind and rain limits"
        requirements = [
            {"query": weather_query, "search_query": "weather",
             "search_queries": {"zh": "查询当地风雨条件", "en": "weather"}},
            {"query": "seismograph", "required": False, "search_queries": {"zh": "地震仪", "en": "seismograph"}},
            {"query": "12306 train ticket availability", "search_query": "12306",
             "search_queries": {"zh": "查询12306余票", "en": "12306 train ticket availability"}},
        ]
        cid, events = post(runtime, "Create an Agent that queries weather and seismographs.", [
            f"<code>print(nl2a_discover_requirements(requirements={requirements!r}, purpose='generate'))</code>",
            verify,
        ])
        coverage = get_card(events)
        assert coverage["subtype"] == "requirement_coverage"
        assert any(
            message["role"] == "user" and '<completed_action_history read_only="true">' in str(message["content"])
            and "installed_candidates" in str(message["content"])
            for request in runtime.provider.wire for message in request["messages"]
        )
        weather, gap, tickets = coverage["requirements"]
        assert [row["coverage_status"] for row in coverage["requirements"]] == ["covered", "uncovered", "installable"]
        assert tickets["installable_resources"][0]["installation_status"] == "disabled"
        assert weather["query"] == weather_query and "search_query" not in weather
        assert runtime.draft() == before

        assert gap["required"] is True
        edits = [{"requirement_id": weather["requirement_id"], "query": weather_query}]
        legacy_edit = {"requirement_id": gap["requirement_id"], "query": "seismograph", "required": False}
        mcp_edit = {"requirement_id": tickets["requirement_id"], "query": tickets["query"]}
        _, events = post(runtime, action(coverage, "confirm_requirements",
                                         requirements=[*edits, legacy_edit, mcp_edit]), [], cid)
        coverage = get_card(events)
        assert coverage["subtype"] == "requirement_coverage"
        assert coverage["requirements"][1]["required"] is True
        mcp_record["enabled"] = True
        installed_tools.append({
            **installed, "candidate_ref": "tool:17", "source": "MCP_TOOL", "name": "get_tickets",
            "description": "查询余票", "names": ["get_tickets"], "descriptions": ["查询余票"],
            "mcp_service_name": mcp_record["mcp_name"],
        })
        _, events = post(runtime, action(coverage, "confirm_requirements", requirements=[*edits, mcp_edit]), [
            "<code>print(nl2a_discover_requirements())</code>", verify,
        ], cid)
        binding = get_card(events)
        assert binding["subtype"] == "installed_resource_binding"
        assert {row["candidate"]["candidate_ref"] for row in binding["resources"]} == {"tool:9", "tool:17"}
        _, events = post(runtime, action(binding, "return_requirements"), [], cid)
        clarification = get_card(events)
        assert clarification["subtype"] == "requirement_clarification"
        assert [row["requirement_id"] for row in clarification["requirements"]] == [
            weather["requirement_id"], tickets["requirement_id"],
        ]
        assert runtime.draft() == before

        stale = runtime.post(PATH, query=action(binding, "continue", selected_resource_refs=["tool:9"]),
                             conversation_id=cid)
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "resource_card_stale"
        _, events = post(runtime, action(clarification, "confirm_requirements", requirements=edits), [], cid)
        latest = get_card(events)
        not_bound = runtime.post(PATH, query=action(latest, "continue", selected_resource_refs=["tool:9"]),
                                 conversation_id=cid)
        assert not_bound.status_code == 409 and not_bound.json()["detail"]["code"] == "binding_not_ready"
        with runtime.storage["sessions"]() as session:
            session.add(ToolInstance(
                tool_id=9, agent_id=runtime.agent_id, params={}, tenant_id=scope.tenant_id, user_id=scope.user_id,
                enabled=True, created_by=scope.user_id, updated_by=scope.user_id, version_no=0,
            ))

        _, events = post(runtime, action(latest, "continue", selected_resource_refs=["tool:9"]), [
            "<code>context = nl2a_read_generation_context(goal='complete')\n"
            f"print(nl2a_save_agent_draft_fields(agent_id={runtime.agent_id}, fields={{'prompt':'Call weather.'}}))</code>",
            f"<code>print(nl2a_save_agent_draft_fields(agent_id={runtime.agent_id}, "
            "fields={'greeting_message':'Hello','example_questions':['What is the weather?']}))</code>",
            "<code>print(nl2a_validate_agent_generation_complete())</code>",
            "<final_answer>Created.</final_answer>",
        ], cid)
        receipts = [json.loads(item["content"]) for item in events if item["type"] == "nl2a_state"]
        assert [item["event"] for item in receipts] == [
            "agent_draft_fields_saved", "agent_draft_fields_saved", "agent_generation_completed",
        ]
        assert receipts[0]["updated_fields"] == ["prompt"]
        assert receipts[1]["updated_fields"] == ["greeting_message", "example_questions"]
        with runtime.storage["sessions"]() as session:
            row = session.scalars(select(AgentInfo).where(AgentInfo.agent_id == runtime.agent_id)).one()
            assert row.prompt == "Call weather."
            assert row.greeting_message == "Hello" and row.example_questions == ["What is the weather?"]


def test_linked_installation_reenters_verification(monkeypatch):
    from management.services.skill import transfer

    candidate = {
        "candidate_ref": "nexent_official_skill:weather", "resource_type": "skill",
        "source": "NEXENT_OFFICIAL_SKILL", "name": "weather", "description": "weather",
        "names": ["weather"], "labels": [], "descriptions": ["weather"], "interfaces": [],
        "inputs": {}, "installed": False, "quality": 1.0, "form_kind": "SKILL_CONFIG", "config": [],
        "installation_options": [ResourceInstallationOption(
            option_id="official", label="Install", form_kind="SKILL_CONFIG", config=[],
        )], "default_option_id": "official",
    }
    installed = []
    official = []
    monkeypatch.setattr(transfer, "get_official_skills_with_status", lambda **_: official)
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=installed))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog",
                        AsyncMock(return_value=[candidate]))
    with owned_runtime(monkeypatch) as (runtime, redis):
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()

        def verify(expected):
            state = json.loads(redis.get(_state_key(runtime)))
            batch = state["batch"]
            [requirement_id] = batch["requirements"]
            row = state["requirements"][requirement_id]
            refs = [item["candidate_ref"] for item in row["installed"] + row["installable"]]
            assert expected in refs
            checks = [assessed_check(state, requirement_id, [expected])]
            return f"<code>print(nl2a_verify_requirements(verification_batch_id={batch['id']!r}, checks={checks!r}))</code>"

        cid, events = post(runtime, "Add a weather skill.", [
            "<code>print(nl2a_discover_requirements(requirements=[{'query':'weather', 'search_queries':{'zh':'天气','en':'weather'}}], purpose='generate'))</code>",
            lambda: verify(candidate["candidate_ref"]),
        ])
        card = get_card(events)
        [row] = card["requirements"]
        assert row["requirement_id"] == "r1"
        assert row["coverage_status"] == "installable"
        link = {
            "agent_id": runtime.agent_id, "conversation_id": cid, "card_id": card["card_id"],
            "state_version": card["state_version"], "requirement_id": row["requirement_id"],
            "candidate_ref": candidate["candidate_ref"],
        }
        auth = {"Authorization": "Bearer fixture-creator"}
        url = "/api/agent/nl2agent/resource_installations"
        detail = runtime.client.post(url, json=link, headers=auth)
        assert detail.status_code == 200, detail.text
        assert detail.json()["resources"][0]["default_option_id"] == "official"

        attempt_url = "/api/agent/nl2agent/resource_installation_attempts"
        def claim():
            return runtime.client.post(attempt_url, json={**link, "operation": "claim"}, headers=auth)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = [pool.submit(claim) for _ in range(2)]
            attempts = [response.result() for response in responses]
        pending = runtime.client.post(attempt_url, json={**link, "operation": "check"}, headers=auth)
        assert all(response.status_code == 200 for response in [*attempts, pending])
        assert sorted(response.json()["status"] for response in attempts) == ["claimed", "pending"]
        assert pending.json() == {"status": "pending", "target_name": "weather"}

        installed.append({**candidate, "candidate_ref": "skill:17", "source": "INSTALLED_SKILL", "installed": True})
        official.append({"name": "weather", "status": "installed", "skill_id": 17})
        recovered = runtime.client.post(attempt_url, json={**link, "operation": "check"}, headers=auth)
        assert recovered.status_code == 200
        assert recovered.json() == {"status": "installed", "resource_type": "skill", "resource_id": 17}
        wrong_link = runtime.client.post("/api/agent/nl2agent/resource_links",
                                         json={**link, "resource_type": "skill", "resource_id": 18}, headers=auth)
        assert wrong_link.status_code == 409
        link_response = runtime.client.post("/api/agent/nl2agent/resource_links",
                                           json={**link, "resource_type": "skill", "resource_id": 17}, headers=auth)
        assert link_response.status_code == 200, link_response.text
        state = json.loads(redis.get(_state_key(runtime)))
        assert state["requirements"][row["requirement_id"]]["accepted"] == [candidate["candidate_ref"]]
        edits = [{key: row[key] for key in ("requirement_id", "query", "required")}]
        confirmation = action(card, "confirm_requirements", requirements=edits)
        runtime.provider.failure = True
        interrupted = runtime.post(PATH, query=confirmation, conversation_id=cid)
        runtime.provider.failure = False
        assert interrupted.status_code == 200
        assert any(
            json.loads(line[6:])["type"] == "error"
            for line in interrupted.text.splitlines() if line.startswith("data: ")
        )
        pending = json.loads(redis.get(_state_key(runtime)))
        assert pending["card"] is None and pending["version"] == card["state_version"] + 1
        assert pending["requirements"][row["requirement_id"]]["linked_refs"] == ["skill:17"]
        stale = runtime.post(PATH, query=confirmation, conversation_id=cid)
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "resource_card_stale"
        _, events = post(runtime, confirmation, [
            f"<code>print(nl2a_save_agent_draft_fields(agent_id={runtime.agent_id}, fields={{'prompt':'Premature'}}))</code>",
            "<code>print(nl2a_validate_agent_generation_complete())</code>",
            "<code>print(nl2a_discover_requirements())</code>", lambda: verify("skill:17"),
        ], cid, retry_message_index=2)
        assert not any(item["type"] == "nl2a_state" and
                       json.loads(item["content"]).get("event") != "resource_retrieval_progress" for item in events)
        binding = get_card(events)
        assert binding["subtype"] == "installed_resource_binding"
        assert binding["resources"][0]["candidate"]["candidate_ref"] == "skill:17"
        _, returned_events = post(runtime, action(binding, "return_requirements"), [], cid)
        returned = get_card(returned_events)
        assert returned["subtype"] == "requirement_clarification"
        manual = {key: link[key] for key in ("agent_id", "conversation_id")}
        manual.update(card_id=returned["card_id"], state_version=returned["state_version"],
                      client_key="manual-row", resource_type="skill", resource_id=17)
        manual_link = runtime.client.post("/api/agent/nl2agent/resource_links", json=manual, headers=auth)
        assert manual_link.status_code == 200, manual_link.text
        state = json.loads(redis.get(_state_key(runtime)))
        assert state["pending_links"] == {"manual-row": ["skill:17"]}
        _, manual_events = post(runtime, action(returned, "confirm_requirements", requirements=[
            {"client_key": "manual-row", "query": "Manually added weather resource", "required": True},
        ]), ["<code>print(nl2a_discover_requirements())</code>", lambda: verify("skill:17")], cid)
        manual_binding = get_card(manual_events)
        assert manual_binding["resources"][0]["candidate"]["candidate_ref"] == "skill:17"
        assert [row["requirement_id"] for row in manual_binding["requirements"]] == ["r2"]
        assert runtime.draft() == before


@contextmanager
def embedding_provider(dimension=2, encode=None):
    wire = []
    failure = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            wire.append(body)
            self.send_response(503 if failure else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            result = {"data": [{"index": i, "embedding": encode(text) if encode else [-1.0 if "[lexical-only]" in text else 1.0] + [0.0] * (dimension - 1)}
                               for i, text in enumerate(body["input"])]}
            self.wfile.write(json.dumps(result).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", wire, failure
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


@pytest.mark.parametrize("aidp", [False, True])
def test_knowledge_priority_runtime(monkeypatch, aidp, owned_resource_es):
    from management.services.model.resolver import create_embedding_model
    from services import nl2agent_semantic_retrieval as semantic

    name = "aidp_search" if aidp else "knowledge_base_search"
    query = "检索平台知识库中的企业资料"
    def tool(ref, tool_name, description):
        return {"candidate_ref": ref, "resource_type": "tool", "source": "LOCAL_TOOL", "name": tool_name,
                "names": [tool_name], "description": description, "descriptions": [description], "labels": [],
                "interfaces": [], "installed": True, "quality": 1.0, "config": [], "inputs": {}}
    catalog = [tool("tool:9", "datamate_search", query),
               tool("tool:17", name, "opaque native capability [lexical-only]")]
    catalog.extend(tool(f"tool:{index}", f"opaque_{index}", "Unrelated opaque capability")
                   for index in range(701, 713))
    monkeypatch.setattr(nl2agent_service, "ENABLE_AIDP_KNOWLEDGE", aidp)
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    knowledge = [{"id": "owned", "binding_value": "owned-private-index", "name": "企业资料"}]
    knowledge_provider = Mock(side_effect=lambda *args, **kwargs: knowledge)
    monkeypatch.setattr(nl2agent_service, "load_visible_knowledge", knowledge_provider)
    with owned_runtime(monkeypatch) as (runtime, redis), embedding_provider() as (url, wire, failure):
        config = {"model_id": 7, "model_name": "owned-embedding", "model_type": "embedding",
                  "base_url": url, "api_key": "fixture", "embedding_dim": 2, "model_factory": "OpenAI-API-Compatible"}
        monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config", lambda **kw: config)
        monkeypatch.setattr(semantic, "create_embedding_model", create_embedding_model)
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()
        try:
            for mode in ("text", "hybrid", "early_native", "fallback", "native_high", "explicit", "rejected", "empty", "provider_error", "bound"):
                active_query = "使用DataMate知识库检索企业资料" if mode == "explicit" else query
                monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config",
                                    lambda **kw: {} if mode not in ("hybrid", "early_native", "fallback") else config)
                catalog[1]["description"] = "检索平台知识库中的资料 [lexical-only]"
                catalog[1]["descriptions"] = [catalog[1]["description"]]
                catalog[0]["description"] = "DataMate: " + query
                catalog[0]["descriptions"] = [catalog[0]["description"]]
                if mode == "native_high":
                    catalog[1]["description"] = query
                    catalog[1]["descriptions"] = [query]
                failure[:] = [True] if mode == "fallback" else []
                if mode == "empty":
                    knowledge.clear()
                else:
                    knowledge[:] = [{"id": "owned", "binding_value": "owned-private-index", "name": "企业资料"}]
                knowledge_provider.side_effect = (ConnectionError("Knowledge provider unavailable")
                                                  if mode == "provider_error" else lambda *args, **kwargs: knowledge)
                if mode == "bound":
                    with runtime.storage["sessions"]() as session:
                        session.add(ToolInstance(tool_id=17, agent_id=runtime.agent_id,
                            params={"kds_list" if aidp else "index_names": ["owned-private-index"]},
                            tenant_id=scope.tenant_id, user_id=scope.user_id, enabled=True,
                            created_by=scope.user_id, updated_by=scope.user_id, version_no=0))
                def verify():
                    state = json.loads(redis.get(_state_key(runtime)))
                    row = state["requirements"]["r1"]
                    refs = [item["candidate_ref"] for item in row["installed"]]
                    assert len(refs) == len(set(refs))
                    if mode in ("text", "hybrid", "early_native", "fallback", "rejected", "bound"):
                        assert "tool:17" in refs
                    offset = row.get("verification_offset", 0)
                    batch_refs = refs[offset:offset + 6]
                    accepted = [ref for ref in batch_refs if ref in {"tool:9", "tool:17"}
                                and not (mode in ("rejected", "explicit") and ref == "tool:17")]
                    return (f"<code>print(nl2a_verify_requirements(verification_batch_id={state['batch']['id']!r}, "
                            f"checks={[assessed_check(state, 'r1', accepted)]!r}))</code>")
                req = [{"query": active_query, "search_queries": {"zh": active_query, "en": "corporate archive"}}]
                def actions():
                    yield f"<code>print(nl2a_discover_requirements(requirements={req!r}, purpose='bind'))</code>"
                    while json.loads(redis.get(_state_key(runtime)))["batch"] is not None:
                        yield verify
                _, events = post(runtime, active_query, actions())
                card = get_card(events)
                assert card["subtype"] == "installed_resource_binding"
                refs = [item["candidate_ref"] for item in card["requirements"][0]["covered_resources"]]
                preferred = "tool:17" if mode == "native_high" else "tool:9"
                assert refs[0] == preferred, (mode, refs)
                scores = [item["retrieval_score"] for item in card["requirements"][0]["covered_resources"]]
                assert scores == sorted(scores, reverse=True)
                resources = card["resources"]
                assert resources[0]["candidate"]["candidate_ref"] == preferred
                assert resources[0]["recommendation"] == "recommended"
                if mode == "bound":
                    native = next(item for item in resources if item["candidate"]["candidate_ref"] == "tool:17")
                    assert native["is_bound"]
                if mode in ("text", "hybrid", "early_native", "fallback", "empty", "provider_error", "bound"):
                    assert set(refs) == {"tool:9", "tool:17"}
                knowledge_provider.assert_not_called()
                safe_state = json.dumps(json.loads(redis.get(_state_key(runtime))), ensure_ascii=False)
                assert "owned-private-index" not in safe_state
                assert "owned-private-index" not in json.dumps(wire)
                assert runtime.draft() == before
            with runtime.storage["sessions"]() as session:
                instances = list(session.scalars(select(ToolInstance).where(ToolInstance.agent_id == runtime.agent_id)))
                assert len(instances) == 1 and instances[0].tool_id == 17
        finally:
            for key in redis.scan_iter("nl2agent:embedding:*"):
                redis.delete(key)
            assert not list(redis.scan_iter("nl2agent:embedding:*"))


@pytest.mark.parametrize("empty", [False, True])
def test_top3_hybrid_uncovered_runtime(monkeypatch, owned_resource_es, empty):
    """Exercise bilingual HTTP vectors, real ES, unique verification and a terminal gap."""
    import math
    from management.services.model.resolver import create_embedding_model
    from services import nl2agent_semantic_retrieval as semantic
    from services import nl2agent_resource_flow as flow

    pair = {"zh": "甲乙丙丁戊", "en": "zzzzzz"}
    vectors = {pair["zh"]: [1., 0., 0.], pair["en"]: [0., 1., 0.]}
    catalog = []
    for pool in range(2):
        for index, vector in enumerate([
            [math.sqrt(.5), math.sqrt(.5), 0.],
            [.6, 0., .8], [.59, 0., math.sqrt(1 - .59**2)], [.58, 0., math.sqrt(1 - .58**2)],
            [0., .6, .8], [0., .59, math.sqrt(1 - .59**2)], [0., .58, math.sqrt(1 - .58**2)],
            [.49, .49, math.sqrt(1 - 2 * .49**2)],
        ]):
            name = f"opaque_{pool}_{index}"
            vectors[name] = [-1., 0., 0.] if empty else vector
            ref = f"tool:{index}" if pool == 0 else f"tenant_mcp_repository:{index}"
            description = pair["zh"] if not empty and index in (0, 1) else pair["en"] if not empty and index == 4 else "opaque"
            catalog.append({"candidate_ref": ref, "resource_type": "tool" if pool == 0 else "mcp_server",
                "source": "LOCAL_TOOL" if pool == 0 else "TENANT_MCP_REPOSITORY", "name": name,
                "names": [name], "description": description, "descriptions": [description], "labels": [],
                "interfaces": [], "installed": pool == 0, "quality": 1., "config": [], "inputs": {}})
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=catalog[:8]))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=catalog[8:]))
    retrieve = semantic.retrieve
    searches = []
    async def observe(*args, **kwargs):
        searches.append(args[2])
        return await retrieve(*args, **kwargs)
    monkeypatch.setattr(semantic, "retrieve", observe)
    with owned_runtime(monkeypatch) as (runtime, redis), embedding_provider(
            dimension=3, encode=lambda text: vectors[text.split("\n")[0]]) as (url, wire, _):
        config = {"model_id": 7, "model_name": "owned-embedding", "model_type": "embedding",
                  "base_url": url, "api_key": "fixture", "embedding_dim": 3}
        monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config", lambda **kw: config)
        monkeypatch.setattr(semantic, "create_embedding_model", create_embedding_model)
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()
        checked = []
        wire_at_verification = []
        def verify():
            snapshot = json.loads(redis.get(_state_key(runtime)))
            row = snapshot["requirements"]["r1"]
            if not wire_at_verification:
                wire_at_verification.append(len(wire))
            for label, prefix in (("installed", "tool:"), ("installable", "tenant_mcp_repository:")):
                evidence = row["retrieval_evidence"][label]
                assert set(evidence["text_refs"]) == (set() if empty else {f"{prefix}{i}" for i in (0, 1, 4)})
                assert set(evidence["semantic_refs"]) == (set() if empty else {
                    f"{prefix}{i}" for i in (0, 1, 2, 4, 5)})
            offered = flow._candidates_in_batch(row)
            checked.extend(item["candidate_ref"] for item in offered)
            return (f"<code>print(nl2a_verify_requirements(verification_batch_id={snapshot['batch']['id']!r}, "
                    f"checks={[assessed_check(snapshot, 'r1', [])]!r}))</code>")
        req = [{"query": pair["zh"], "search_queries": pair}]
        def actions():
            yield f"<code>print(nl2a_discover_requirements(requirements={req!r}, purpose='recommend'))</code>"
            while json.loads(redis.get(_state_key(runtime)))["batch"] is not None:
                yield verify
        _, events = post(runtime, "Find resources", actions())
        card = get_card(events)
        assert card["requirements"][0]["coverage_status"] == "uncovered"
        state = json.loads(redis.get(_state_key(runtime)))
        assert state["batch"] is None and state["requirements"]["r1"]["accepted"] == []
        assert len(checked) == len(set(checked)) == (0 if empty else 10)
        assert searches == [{"r1": pair}]
        assert wire[0]["input"] == list(pair.values())
        assert len(wire) == wire_at_verification[0]
        assert runtime.draft() == before


def test_semantic_recall_runtime(monkeypatch, owned_resource_es):
    from services import nl2agent_semantic_retrieval as semantic
    from services import nl2agent_retrieval_progress as progress
    from management.services.model.resolver import create_embedding_model
    catalog = [{"candidate_ref": "tool:701", "resource_type": "tool", "source": "LOCAL_TOOL",
                "name": "deepseek_search", "names": ["deepseek_search"], "description": "检索公开网页",
                "descriptions": ["Search public webpages"], "labels": ["search"], "interfaces": [],
                "installed": True, "quality": 1.0, "config": [{"value": "must-not-embed"}]}]
    catalog[0]["description"] += " [lexical-only]"
    for index in range(702, 721):
        catalog.append({**catalog[0], "candidate_ref": f"tool:{index}", "name": f"opaque_{index}",
                        "names": [f"opaque_{index}"], "description": "Unrelated opaque capability",
                        "descriptions": [], "labels": []})
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=catalog))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    with owned_runtime(monkeypatch) as (runtime, redis), embedding_provider() as (url, wire, failure):
        config = {"model_id": 7, "model_name": "owned-embedding", "model_type": "embedding",
                  "base_url": url, "api_key": "fixture", "embedding_dim": 2, "model_factory": "OpenAI-API-Compatible"}
        monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config", lambda **kw: config)
        monkeypatch.setattr(semantic, "create_embedding_model", create_embedding_model)
        monkeypatch.setattr(progress, "get_redis_client", lambda: redis)
        from services.nl2agent_state_service import ResourceScope
        scope = ResourceScope(runtime.storage["tenant"], runtime.storage["owner"], runtime.agent_id, "", "")
        before = runtime.draft()
        def verify():
            state = json.loads(redis.get(_state_key(runtime)))
            if state["batch"] is None:
                return "<final_answer>Recommended.</final_answer>"
            row = state["requirements"]["r1"]
            refs = [item["candidate_ref"] for item in row["installed"]]
            assert refs[0] == "tool:701" and len(refs) == len(set(refs))
            if row["retrieval_method"] == "hybrid":
                assert "tool:702" in refs
            else:
                assert "tool:702" not in refs
            accepted = [] if row.get("verification_offset", 0) else ["tool:701"]
            return f"<code>print(nl2a_verify_requirements(verification_batch_id={state['batch']['id']!r}, checks={[assessed_check(state, 'r1', accepted)]!r}))</code>"
        expression = "DeepSeek search public webpages"
        requirement = {"query": "使用DeepSeek检索公开网页", "search_queries": {"zh": expression, "en": expression}}
        try:
            original_keys = set()
            es, prefix = owned_resource_es
            for index in range(7):
                if index == 2:
                    catalog[0]["config"] = [{"value": "rotated-private-config"}]
                    config["api_key"] = "rotated-fixture"
                    config["display_name"] = "Renamed display"
                if index == 3:
                    catalog[0]["description"] += " Updated capability."
                if index == 4:
                    config["model_id"] = 8
                    config["model_name"] = "owned-embedding-v2"
                if index == 5:
                    failure.append(True)
                if index == 6:
                    config.clear()
                before_wire = len(wire)
                actions = [f"<code>print(nl2a_discover_requirements(requirements={[requirement]!r}, purpose='recommend'))</code>", verify]
                _, events = post(runtime, "Recommend web search tools", actions)
                assert get_card(events)["requirements"][0]["coverage_status"] == "covered"
                stages = [json.loads(event["content"])["stage"] for event in events
                          if event["type"] == "nl2a_state" and json.loads(event["content"]).get("event") == "resource_retrieval_progress"]
                assert "verifying_capabilities" in stages
                progress_events = [json.loads(event["content"]) for event in events if event["type"] == "nl2a_state"
                                   and json.loads(event["content"]).get("event") == "resource_retrieval_progress"]
                assert all(event["agent_id"] == runtime.agent_id and event["run_id"] for event in progress_events)
                sequences = [event["sequence"] for event in progress_events]
                assert sequences == sorted(set(sequences))
                assert all(set(event) <= {"event", "agent_id", "run_id", "sequence", "stage", "completed", "total"}
                           for event in progress_events)
                assert "must-not-embed" not in json.dumps(wire)
                assert ("fallback_to_text" in stages) == (index == 5)
                calls = wire[before_wire:]
                if index == 0:
                    assert len(calls) == 4
                    assert sum(len(call["input"]) for call in calls[1:]) == 20
                    original_keys = set(es.indices.get(index=prefix + "-*"))
                    assert len(original_keys) == 1
                    assert es.count(index=next(iter(original_keys)))["count"] == 20
                if index in (1, 2):
                    assert len(calls) == 1 and calls[0]["input"] == [expression]
                    assert set(es.indices.get(index=prefix + "-*")) == original_keys
                    assert es.count(index=next(iter(original_keys)))["count"] == 20
                if index == 3:
                    assert len(calls) == 2 and calls[1]["input"] == [semantic._text(catalog[0])]
                    assert es.count(index=next(iter(original_keys)))["count"] == 20
                if index == 4:
                    assert len(calls) == 4
                    assert all(call["model"] == "owned-embedding-v2" for call in calls)
                    generations = list(es.indices.get(index=prefix + "-*"))
                    assert len(generations) == 2
                    assert sum(es.count(index=name)["count"] for name in generations) == 40
                if index == 6:
                    assert calls == []
                    assert "preparing_embeddings" not in stages
                assert not list(redis.scan_iter("nl2agent:embedding:*"))
            assert runtime.draft() == before
        finally:
            for key in redis.scan_iter("nl2agent:embedding:*"):
                redis.delete(key)
            assert not list(redis.scan_iter("nl2agent:embedding:*"))


def _es_document(tenant, ref, text):
    return storage.projection(tenant, {
        "candidate_ref": ref, "source": "MCP_TOOL", "resource_type": "tool",
        "config": {"token": "must-not-index"},
    }, text, "fixture", 3)


def test_es_authorized_resources_and_revision_conflicts(owned_resource_es, monkeypatch):
    client, _ = owned_resource_es
    # Every call uses a bounded client, including create/mget/refresh/search.
    with storage.ResourceIndex("fixture", 2, 3, lambda: 8.) as index:
        a = _es_document("tenant", "tool:a-private", "A private")
        b = _es_document("tenant", "tool:b-private", "B private")
        shared = _es_document("tenant", "tool:shared", "Shared")
        foreign = _es_document("other", "tool:foreign", "Foreign")
        for row, vector in [(a, [1., 0.]), (b, [1., 0.]), (shared, [.8, .6]), (foreign, [1., 0.])]:
            index.put(row, vector, {"found": False})
        before = client.count(index=index.name)["count"]
        assert before == 4
        assert index.search("tenant", [a, shared], [1., 0.], 2) == [
            (pytest.approx(1.), a["candidate_ref"]), (pytest.approx(.8), shared["candidate_ref"])]
        assert {ref for _, ref in index.search("tenant", [b, shared], [1., 0.], 2)} == {
            b["candidate_ref"], shared["candidate_ref"]}
        assert index.search("tenant", [], [1., 0.], 2) == []
        assert "must-not-index" not in str(client.search(index=index.name, query={"match_all": {}}).body)
        changed = _es_document("tenant", "tool:shared", "Changed capability")
        first = index.snapshots("tenant", [shared])[shared["candidate_ref"]]
        second = index.snapshots("tenant", [shared])[shared["candidate_ref"]]
        index.put(changed, [0., 1.], first)
        assert client.count(index=index.name)["count"] == before
        with pytest.raises(ValueError, match="changed"):
            index.put(shared, [1., 0.], second)
        # Old content cannot participate even though its resource identity is visible.
        with pytest.raises(ValueError, match="incomplete|changed"):
            index.search("tenant", [shared], [1., 0.], 1)
        assert index.search("tenant", [changed], [1., 0.], 1) == [(pytest.approx(0.), shared["candidate_ref"])]
        monkeypatch.setattr(storage, "FILTER_BATCH_SIZE", 1)
        assert index.search("tenant", [a, b, changed], [1., 0.], 2) == [
            (pytest.approx(1.), a["candidate_ref"]), (pytest.approx(1.), b["candidate_ref"])]
        index.delete("tenant", a["candidate_ref"])
        assert client.count(index=index.name)["count"] == before - 1


def test_es_backend_user_scope_before_search(monkeypatch, owned_resource_es):
    from elasticsearch import AsyncElasticsearch
    from management.services.model.resolver import create_embedding_model
    from services import nl2agent_semantic_retrieval as semantic
    from management.services.skill.service import SkillService
    from management.services.tool import configuration

    requests = []
    original_search = AsyncElasticsearch.search
    async def observed_search(client, *args, **kwargs):
        requests.append(kwargs)
        return await original_search(client, *args, **kwargs)
    monkeypatch.setattr(AsyncElasticsearch, "search", observed_search)
    tools = [{"tool_id": i, "name": f"search_{name}", "source": "mcp", "is_available": True,
              "usage": name, "description": f"{name} public capability", "params": [], "inputs": {}}
             for i, name in enumerate(("shared", "a", "b"), 1)]
    monkeypatch.setattr(configuration, "list_all_tools", AsyncMock(return_value=tools))
    monkeypatch.setattr(SkillService, "list_visible_skills", lambda *a, **kw: [])
    monkeypatch.setattr(mcp_service, "get_mcp_records_by_tenant", lambda **kw: [
        {"mcp_name": "shared", "enabled": True, "group_ids": None},
        {"mcp_name": "a", "enabled": True, "group_ids": "", "created_by": "a"},
        {"mcp_name": "b", "enabled": True, "group_ids": "", "created_by": "b"},
    ])
    monkeypatch.setattr(mcp_service, "query_group_ids_by_user", lambda _: [])
    with owned_runtime(monkeypatch) as (runtime, _), embedding_provider() as (url, wire, _):
        config = {"model_id": 7, "model_name": "owned-embedding", "model_type": "embedding",
                  "base_url": url, "api_key": "fixture", "embedding_dim": 2}
        monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config", lambda **kw: config)
        monkeypatch.setattr(semantic, "create_embedding_model", create_embedding_model)
        async def search(user):
            catalog = await nl2agent_service._load_installed_resource_catalog(
                tenant_id=runtime.storage["tenant"], user_id=user)
            model = await semantic.resolve_model(runtime.storage["tenant"])
            return await semantic.retrieve(runtime.storage["tenant"], model,
                {"r1": "search"}, catalog, [], None)
        a = asyncio.run(search("a"))
        boundary = len(requests)
        b = asyncio.run(search("b"))
        assert {row["candidate_ref"] for _, row in a["r1"]["installed"]} == {"tool:1", "tool:2"}
        assert {row["candidate_ref"] for _, row in b["r1"]["installed"]} == {"tool:1", "tool:3"}
        assert len(requests) > boundary
        for request in requests[boundary:]:
            filters = request["query"]["script_score"]["query"]["bool"]["filter"]
            assert {"terms": {"candidate_ref": ["tool:1", "tool:3"]}} in filters
            assert {"term": {"tenant_id": runtime.storage["tenant"]}} in filters
        before = len(requests)
        def unavailable(_):
            raise RuntimeError("Permission source unavailable")
        monkeypatch.setattr(mcp_service, "query_group_ids_by_user", unavailable)
        with pytest.raises(RuntimeError, match="Permission source unavailable"):
            asyncio.run(search("b"))
        assert len(requests) == before


def _concurrent_catalog():
    return [{"candidate_ref": f"tool:{i}", "resource_type": "tool", "source": "LOCAL_TOOL",
             "name": f"tool_{i}", "names": [f"tool_{i}"], "description": "Public web search",
             "descriptions": [], "labels": [], "installed": i < 12,
             "config": [{"value": "must-not-embed"}]} for i in range(24)]


def test_es_search_concurrency_runtime(monkeypatch, owned_resource_es, record_property):
    from contextvars import ContextVar
    import math
    import time
    from elasticsearch import AsyncElasticsearch
    from services import nl2agent_semantic_retrieval as semantic
    from management.services.model.resolver import create_embedding_model

    owner = ContextVar("recommendation-owner", default="warm")
    catalog = _concurrent_catalog()
    scopes = {i: [row for j, row in enumerate(catalog) if j == 0 or j % 3 == i] for i in range(3)}
    active = peak = 0
    per_owner = {i: 0 for i in scopes}
    owner_peaks = dict(per_owner)
    requests = []
    original_search = AsyncElasticsearch.search

    async def observed_search(client, *args, **kwargs):
        nonlocal active, peak
        who = owner.get()
        if who == "warm":
            return await original_search(client, *args, **kwargs)
        filters = kwargs["query"]["script_score"]["query"]["bool"]["filter"]
        refs = filters[3]["terms"]["candidate_ref"]
        assert set(refs) <= {row["candidate_ref"] for row in scopes[who]}
        assert len(refs) <= 3
        assert filters[4]["terms"]["resource_revision"] == [
            semantic.resource_revision(next(row for row in scopes[who] if row["candidate_ref"] == ref))
            for ref in refs]
        assert filters[0] == {"term": {"tenant_id": tenant}}
        requests.append((who, kwargs))
        active += 1
        peak = max(peak, active)
        per_owner[who] += 1
        owner_peaks[who] = max(owner_peaks[who], per_owner[who])
        try:
            # Delay only at the protocol boundary; all requests still reach real ES.
            await asyncio.sleep(.02)
            return await original_search(client, *args, **kwargs)
        finally:
            active -= 1
            per_owner[who] -= 1

    monkeypatch.setattr(AsyncElasticsearch, "search", observed_search)
    monkeypatch.setattr(storage, "FILTER_BATCH_SIZE", 3)
    monkeypatch.setattr(semantic, "FILTER_BATCH_SIZE", 3)
    with owned_runtime(monkeypatch) as (runtime, _), embedding_provider(dimension=1024) as (url, wire, _):
        tenant = runtime.storage["tenant"]
        before = runtime.draft()
        config = {"model_id": 7, "model_name": "owned-embedding", "model_type": "embedding",
                  "base_url": url, "api_key": "fixture", "embedding_dim": 1024}
        monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config", lambda **kw: config)
        monkeypatch.setattr(semantic, "create_embedding_model", create_embedding_model)

        async def run():
            model = await semantic.resolve_model(tenant)
            await semantic.retrieve(tenant, model, {"warm": "warm"}, catalog, [], None)
            boundary = len(wire)
            queries = {f"r{i}": f"tool_0 search {i}" for i in range(8)}
            queries["duplicate"] = queries["r0"]

            samples = []
            async def recommend(who):
                token = owner.set(who)
                started = time.perf_counter()
                try:
                    rows = scopes[who]
                    return await semantic.retrieve(tenant, model, queries,
                        [row for row in rows if row["installed"]],
                        [row for row in rows if not row["installed"]], None)
                finally:
                    samples.append((time.perf_counter() - started) * 1000)
                    owner.reset(token)

            for _ in range(10):
                results = await asyncio.gather(*(recommend(who) for who in scopes))
            assert active == 0 and peak == 8
            assert all(value <= 8 for value in owner_peaks.values())
            assert max(owner_peaks.values()) == 8
            assert all(value == 0 for value in per_owner.values())
            for who, result in enumerate(results):
                assert result["r0"] == result["duplicate"]
                for groups in result.values():
                    for label in groups:
                        expected = sorted(row["candidate_ref"] for row in scopes[who]
                                          if row["installed"] == (label == "installed"))[:3]
                        assert [row["candidate_ref"] for _, row in groups[label]] == expected
                # Four authorized filter chunks per unique query; names cannot add searches.
                assert sum(key == who for key, _ in requests) == 8 * 4 * 10
            assert len(wire[boundary:]) == 30
            assert all(len(body["input"]) == 8 for body in wire[boundary:])
            ordered = sorted(samples)
            record_property("warm_1024d_recommendations", len(ordered))
            record_property("warm_1024d_p95_ms", ordered[math.ceil(.95 * len(ordered)) - 1])
            record_property("warm_1024d_max_ms", max(ordered))
            record_property("observed_process_peak", peak)
            record_property("observed_recommendation_peaks", json.dumps(owner_peaks))
            # Exercise simultaneous cold preparation and CAS writes in a new model generation.
            config["model_name"] = "owned-embedding-cold"
            model = await semantic.resolve_model(tenant)
            cold = await asyncio.gather(*(recommend(who) for who in scopes))
            assert all(result["r0"] == result["duplicate"] for result in cold)
            assert active == 0 and peak == 8
            assert all(duration < semantic.RETRIEVAL_TIMEOUT * 1000 for duration in samples)
            record_property("cold_1024d_recommendation_ms", json.dumps(samples[-3:]))

        asyncio.run(run())
        assert runtime.draft() == before
        assert "must-not-embed" not in json.dumps(wire)


def test_es_search_cancellation_cleanup(monkeypatch, owned_resource_es):
    from elasticsearch import AsyncElasticsearch
    from services import nl2agent_semantic_retrieval as semantic
    from management.services.model.resolver import create_embedding_model

    catalog = _concurrent_catalog()[:4]
    clients = []
    original_factory = storage.create_async_client
    original_search = AsyncElasticsearch.search
    active = started = 0
    mode = "pass"

    def factory():
        client = original_factory()
        close = client.close
        closed = []
        async def tracked_close():
            try:
                await close()
            finally:
                closed.append(True)
        client.close = tracked_close
        clients.append(closed)
        return client

    async def observed_search(client, *args, **kwargs):
        nonlocal active, started
        started += 1
        active += 1
        try:
            if mode == "block":
                entered.set()
                await asyncio.Event().wait()
            if mode == "error":
                await asyncio.sleep(.02)
                raise OSError("Controlled ES transport failure")
            return await original_search(client, *args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(storage, "create_async_client", factory)
    monkeypatch.setattr(AsyncElasticsearch, "search", observed_search)
    with owned_runtime(monkeypatch) as (runtime, _), embedding_provider() as (url, _, _):
        tenant = runtime.storage["tenant"]
        before = runtime.draft()
        config = {"model_id": 7, "model_name": "owned-embedding", "model_type": "embedding",
                  "base_url": url, "api_key": "fixture", "embedding_dim": 2}
        monkeypatch.setattr(semantic.tenant_config_manager, "get_model_config", lambda **kw: config)
        monkeypatch.setattr(semantic, "create_embedding_model", create_embedding_model)

        async def run():
            nonlocal mode, started, entered
            model = await semantic.resolve_model(tenant)
            async def recommend():
                return await semantic.retrieve(tenant, model,
                    {f"r{i}": f"search {i}" for i in range(8)}, catalog, [], None)
            await recommend()
            gate = storage._PROCESS_SEARCH_GATE
            for cancel in (True, False):
                assert all(gate.acquire(blocking=False) for _ in range(8))
                baseline = started
                entered_map = asyncio.Event()
                original_map = semantic.map_search_jobs
                async def observed_map(*args):
                    entered_map.set()
                    return await original_map(*args)
                with monkeypatch.context() as patch:
                    patch.setattr(semantic, "map_search_jobs", observed_map)
                    patch.setattr(semantic, "RETRIEVAL_TIMEOUT", .3 if not cancel else 2.)
                    task = asyncio.create_task(recommend())
                    try:
                        await asyncio.wait_for(entered_map.wait(), 1.)
                        if cancel:
                            task.cancel()
                        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
                            await task
                    finally:
                        for _ in range(8):
                            gate.release()
                await asyncio.sleep(.02)
                assert started == baseline and active == 0
                assert all(len(closed) == 1 for closed in clients)

            for interruption in ("cancel", "timeout", "error"):
                mode = "error" if interruption == "error" else "block"
                entered = asyncio.Event()
                with monkeypatch.context() as patch:
                    patch.setattr(semantic, "RETRIEVAL_TIMEOUT", .3 if interruption == "timeout" else 2.)
                    task = asyncio.create_task(recommend())
                    if interruption == "cancel":
                        await asyncio.wait_for(entered.wait(), 1.)
                        task.cancel()
                    expected = {"cancel": asyncio.CancelledError, "timeout": TimeoutError, "error": OSError}
                    with pytest.raises(expected[interruption]):
                        await task
                assert active == 0
                assert all(len(closed) == 1 for closed in clients)
                assert all(gate.acquire(blocking=False) for _ in range(8))
                for _ in range(8):
                    gate.release()
            mode = "pass"
            assert await recommend()
            assert active == 0 and all(len(closed) == 1 for closed in clients)

        entered = None
        asyncio.run(run())
        assert runtime.draft() == before
