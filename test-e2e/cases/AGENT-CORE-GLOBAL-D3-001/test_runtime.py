# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Global application policy through the real Jiuwen loop and ModelService HTTP."""

import asyncio
import json
import sys
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "backend"), str(ROOT / "test-e2e/infra/automation")]

from jiuwen_bridge_runtime import run_worker, stop_infrastructure
from management.services.agent import core_policy
from nexent.core.agents.contracts.config import AgentConfig

pytestmark = [pytest.mark.case_id("AGENT-CORE-GLOBAL-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()


@pytest.mark.parametrize("protocol", ["native", "text"])
@pytest.mark.parametrize("mode", ["chat", "artifact"])
def test_global_core_real_protocol(monkeypatch, protocol, mode):
    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", "jiuwen")
    before = []

    def configure(info):
        info.agent_config.agent_core = "smolagents"
        info.agent_config.enable_protocol_repair_retry = True
        info.agent_config.response_mode = mode
        if mode == "artifact":
            info.agent_config.tools = []
            info.agent_config.output_protocol = "final_envelope"
        child = AgentConfig(name="child", description="child", tools=[], model_name="child-model", agent_core="smolagents")
        info.agent_config.worker_agents = [child]
        before.append(info.agent_config.model_copy(deep=True))
        info.agent_config = core_policy.apply_agent_core_policy(info.agent_config.model_copy(deep=True))
        assert info.agent_config.worker_agents[0].agent_core == "jiuwen"
        assert info.agent_config.worker_agents[0].model_name == "child-model"
        assert before[0].agent_core == "smolagents" and before[0].worker_agents[0].agent_core == "smolagents"
        # This fixture proves root execution and child compilation, not child invocation.
        info.agent_config.worker_agents = []
        # The controlled outlet declares no sampling overrides. Represent omission explicitly.
        info.model_config_list = [m.model_copy(update={"temperature": None, "top_p": None}) for m in info.model_config_list]
        core_policy.prepare_creator_core(info, tenant_id="spike-tenant", user_id="fixture-user")

    info, state, output = asyncio.run(run_worker(monkeypatch, protocol, "artifact" if mode == "artifact" else "normal", configure_run=configure))
    assert info.agent_config.agent_core == "jiuwen"
    assert info.attempt_outcome == "completed", output[-2:]
    assert sum(item.get("type") == "final_answer" for item in output) == 1
    assert state["tool_calls"] == ([] if mode == "artifact" else [(2, 3)])
    assert len(state["requests"]) == (1 if mode == "artifact" else 2)
    if mode == "artifact":
        assert all(not request.get("tools") for request in state["requests"])
        result = next(item["content"] for item in output if item.get("type") == "final_answer")
        assert "<code>print(1)</code>" in result and '<file path="scripts/example.py">\nprint(1)\n</file>' in result
        from management.services.skill.stream_parser import SkillStreamParser
        parser = SkillStreamParser()
        events = [event for chunk in output for event in parser.process(chunk)] + parser.flush()
        assert "<code>print(1)</code>" in "".join(event.get("content", "") for event in events if event["type"] == "skill_body")
        assert "".join(event.get("content", "") for event in events if event["type"] == "file_content").strip() == "print(1)"
        _assert_creator_history(monkeypatch, info, output)
    else:
        assert "SPIKE_FINAL_RESULT_5" in json.dumps(output)


def _assert_creator_history(monkeypatch, info, output):
    from unittest.mock import AsyncMock
    from sqlalchemy import update
    from jiuwen_output_runtime import context_database
    from contracts.agent import NL2SkillRunRequest
    from management.db.client import get_db_session
    from management.db.models import ConversationMessageUnit
    from management.db.conversation.repository import create_conversation, get_conversation_history
    from management.services.conversation.creation_history import persist_creation_stream
    from management.services.conversation.service import get_conversation_history_service
    from services import nl2skill_service

    async def replay(*args, **kwargs):
        for event in output:
            yield json.dumps(event)

    monkeypatch.setattr(nl2skill_service, "build_nl2skill_run_info", AsyncMock(return_value=info))
    monkeypatch.setattr(nl2skill_service, "agent_run", replay)

    async def persist(cid):
        stream = await nl2skill_service.create_nl2skill_stream(NL2SkillRunRequest(query="Create"), "spike-tenant", "en")
        return [json.loads(event.removeprefix("data: ")) async for event in persist_creation_stream(
            stream, conversation_id=cid, assistant_index=1, user_id="owner", tenant_id="spike-tenant")]

    with context_database(monkeypatch):
        cid = create_conversation("Creator history", "owner", workbench_config={
            "schema_version": 4, "mode": "skill_create", "agent_mounts": [], "skill_mounts": []})["conversation_id"]
        live = asyncio.run(persist(cid))
        assert live[-1]["type"] == "done" and not any(e["type"] == "error" for e in live)
        expected = "".join(e["content"] for e in live if e["type"] == "skill_body")
        assert expected and all(e.get("runtime_mode") != "native_agent" for e in live)

        def check():
            public = get_conversation_history_service(cid, "owner")[0]["message"][0]
            assert public["status"] == "completed"
            files = [json.loads(u["content"]) for u in public["message"] if u["type"] == "skill_body"]
            assert "".join(f["content"] for f in files) == expected
            assert all("runtime_mode" not in f for f in files)
            return get_conversation_history(cid, "owner")

        check()
        # Reproduce the old persisted wrapper, not a fake successful runtime.
        with get_db_session() as session:
            rows = session.query(ConversationMessageUnit).filter_by(conversation_id=cid, unit_type="skill_body").all()
            for row in rows:
                event = json.loads(row.unit_content)
                event.update(schema_version=1, runtime_mode="native_agent", turn_id="legacy-turn", agent_core="jiuwen")
                session.execute(update(ConversationMessageUnit).where(ConversationMessageUnit.unit_id == row.unit_id)
                                .values(unit_content=json.dumps(event)))
        before = get_conversation_history(cid, "owner")
        assert check() == before


@pytest.mark.parametrize("protocol", ["native", "text"])
def test_global_creator_card_completes_at_interactive_boundary(monkeypatch, protocol):
    from services.nl2agent_service import _Nl2AgentBoundaryObserver
    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", "jiuwen")

    def configure(info):
        info.observer = _Nl2AgentBoundaryObserver(lang="en", stop_event=info.stop_event)
        info.agent_config.response_mode = "python_workflow"
        core_policy.apply_agent_core_policy(info.agent_config)
        info.model_config_list = [m.model_copy(update={"temperature": None, "top_p": None}) for m in info.model_config_list]
        core_policy.prepare_creator_core(info, tenant_id="spike-tenant", user_id="fixture-user")

    info, state, output = asyncio.run(run_worker(monkeypatch, protocol, "creator", configure_run=configure))
    assert info.attempt_outcome == "completed", output[-2:]
    assert info.run_result.end_reason == "awaiting_input"
    assert info.run_result.error is None and info.run_result.final_content == ""
    cards = [json.loads(item["content"]) for item in output if item.get("type") == "nl2a"]
    assert len(cards) == 1 and cards[0]["agent_id"] == 42
    assert len(state["requests"]) == 1 and state["tool_calls"] == []


@contextmanager
def creator_mcp(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with (tmp_path / "mcp.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("mcp_fixture.py")), str(port)],
                                   stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for _ in range(150):
                assert process.poll() is None
                try:
                    if httpx.get(url + "/state", timeout=.2, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(.05)
            else:
                raise AssertionError("Creator MCP fixture did not start")
            yield url
        finally:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("protocol", ["native", "text"])
def test_global_creator_native_mcp_card_and_history(monkeypatch, protocol, tmp_path):
    from unittest.mock import AsyncMock
    from jiuwen_output_runtime import context_database
    from contracts.agent import NL2AgentRunRequest
    from contracts.authentication import AuthenticatedIdentity
    from management.db.conversation.repository import create_conversation, get_conversation_history
    from management.services.conversation.creation_history import persist_creation_stream
    from management.services.conversation.service import get_conversation_history_service
    from nexent.core.agents.contracts.config import ToolConfig
    from services import nl2agent_service as service

    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", "jiuwen")
    with creator_mcp(tmp_path) as url:
        def configure(info):
            info.observer = service._Nl2AgentBoundaryObserver(lang="en", stop_event=info.stop_event)
            info.agent_config.response_mode = "python_workflow"
            info.agent_config.tools = [ToolConfig(name=name, class_name=name, source="mcp", params={})
                                       for name in ("nl2a_wrapper", "forbidden_effect")]
            info.mcp_host = [{"url": url + "/mcp", "transport": "streamable-http"}]
            info.model_config_list = [m.model_copy(update={"temperature": None, "top_p": None}) for m in info.model_config_list]
            core_policy.prepare_creator_core(info, tenant_id="spike-tenant", user_id="fixture-user")

        info, state, output = asyncio.run(run_worker(monkeypatch, protocol, "creator_mcp", configure_run=configure))
        assert len(state["requests"]) == 1, output
        assert httpx.get(url + "/state", trust_env=False).json() == {"cards": 1, "effects": 0}
    assert info.run_result.status == "completed" and info.run_result.end_reason == "awaiting_input"
    assert info.run_result.error is None
    monkeypatch.setattr(service, "build_nl2agent_run_info", AsyncMock(return_value=info))

    async def replay(*args, **kwargs):
        for event in output:
            yield json.dumps(event)

    monkeypatch.setattr(service, "agent_run", replay)

    async def persist(cid):
        stream = await service.create_nl2agent_stream(NL2AgentRunRequest(query="Create", agent_id=42), "spike-tenant", "en",
                                                     identity=AuthenticatedIdentity("owner", "spike-tenant"))
        return [json.loads(event.removeprefix("data: ")) async for event in persist_creation_stream(
            stream, conversation_id=cid, assistant_index=1, user_id="owner", tenant_id="spike-tenant")]

    with context_database(monkeypatch):
        cid = create_conversation("Agent creator", "owner", workbench_config={
            "schema_version": 4, "mode": "agent_create", "agent_mounts": [], "skill_mounts": []})["conversation_id"]
        live = asyncio.run(persist(cid))
        assert sum(e["type"] == "nl2a" for e in live) == 1
        assert sum(e["type"] == "run_terminal" for e in live) == 1
        before = get_conversation_history(cid, "owner")
        message = get_conversation_history_service(cid, "owner")[0]["message"][0]
        assert message["status"] == "completed"
        cards = [json.loads(p["content"]) for p in message["message"] if p["type"] == "nl2a"]
        terminals = [json.loads(p["content"]) for p in message["message"] if p["type"] == "run_terminal"]
        assert len(cards) == 1 and cards[0]["agent_id"] == 42
        assert len(terminals) == 1 and terminals[0]["end_reason"] == "awaiting_input"
        assert terminals[0]["runtime_mode"] == "native_agent" and terminals[0]["error"] is None
        calls = [json.loads(p["content"]) for p in message["message"] if p["type"] == "tool"]
        results = [json.loads(p["content"]) for p in message["message"] if p["type"] == "tool_result"]
        assert calls and all(p["runtime_mode"] == "native_agent" for p in calls)
        assert {p["local_call_id"] for p in calls} == {p["local_call_id"] for p in results}
        assert not any(p["type"] == "error" for p in message["message"])
        assert get_conversation_history(cid, "owner") == before
