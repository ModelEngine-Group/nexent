"""AGENT-CORE-D3-001: Native Jiuwen execution through the Nexent managed worker."""

import asyncio
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from nexent.core.agents.agent_model import AgentConfig, AgentHistory, AgentRunInfo, ModelConfig, ToolConfig
from nexent.core.agents.context.models import ContextItemInput, ContextItemType
from nexent.core.agents.context_input import ContextInput
from nexent.core.agents.run_agent import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver


@pytest.fixture
def native_manager():
    manager = ThreadManager("jiuwen-tests", {name: LanePolicy(name=name, max_workers=4, max_queue_size=8)
                                           for name in ["agent-run", "model-tool-io", "mcp-session"]})
    manager.start()
    yield manager
    asyncio.run(manager.shutdown(timeout=5))


@pytest.fixture
def native_provider(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "provider.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("jiuwen_http_fixture.py")), str(port)],
                                   stdout=log, stderr=log)
        url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail((tmp_path / "provider.log").read_text(encoding="utf-8"))
                try:
                    if httpx.get(url + "/state", timeout=0.2, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.05)
            else:
                pytest.fail("Local Jiuwen provider did not become ready")
            yield url
        finally:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("snapshot_history", [False, True])
@pytest.mark.parametrize("transient_failure", [False, True])
def test_AGENT_CORE_D3_001_native_worker(
    native_manager, native_provider, tmp_path, monkeypatch, snapshot_history, transient_failure,
):
    from openjiuwen.core.runner import Runner

    from nexent.core.agents import nexent_agent
    from nexent.core.agents.core_adapters.jiuwen import JiuwenAdapter

    calls = []

    class NativeAddTool:
        name, description = "add", "Add integers"
        inputs = {"a": {"type": "integer"}, "b": {"type": "integer"}}

        def forward(self, a, b):
            calls.append((a, b))
            return a + b

    monkeypatch.setattr(nexent_agent, "NativeAddTool", NativeAddTool, raising=False)
    monkeypatch.setattr(nexent_agent.NexentAgent, "create_single_agent",
                        lambda *args, **kwargs: pytest.fail("Jiuwen invoked a smolagents Agent"))
    owned_cards = []
    original_prepare = JiuwenAdapter.prepare

    def track_prepare(adapter):
        original_prepare(adapter)
        owned_cards.extend(card.id for card in adapter.native_agent.ability_manager.list())

    monkeypatch.setattr(JiuwenAdapter, "prepare", track_prepare)
    skill = tmp_path / "skills" / "fixture_skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: fixture_skill\ndescription: Fixture skill guide\n---\nSKILL_GUIDE_MARKER\n",
                                    encoding="utf-8")
    (skill / "scripts" / "hello.py").write_text("print('SCRIPT_RESULT_MARKER')\n", encoding="utf-8")
    parameters = {"local_skills_dir": str(skill.parent), "authorized_skill_names": ["fixture_skill"],
                  "isolated_skills_root": True}
    observer = MessageObserver(lang="en")
    info = AgentRunInfo(query="Execute the authorized tool chain", observer=observer, stop_event=__import__("threading").Event(),
                        thread_manager=native_manager, model_config_list=[ModelConfig(cite_name="fixture",
                            model_name="fixture-model", api_key=uuid.uuid4().hex, url=native_provider + "/v1",
                            timeout_seconds=5, max_output_tokens=512)],
                        mcp_host=[native_provider + "/mcp"], mcp_request_timeout_seconds=5,
                        user_context={"user_id": "fixture-user"},
                        agent_config=AgentConfig(agent_core="jiuwen", name="native-fixture", description="Fixture agent",
                            model_name="fixture", max_steps=6, instructions="Preserve business instructions.", tools=[
                                ToolConfig(name="add", class_name="NativeAddTool", source="local", params={}),
                                ToolConfig(name="multiply", class_name="multiply", source="mcp", params={}),
                                ToolConfig(name="read_skill_md", class_name="ReadSkillMdTool", source="builtin", params=parameters),
                                ToolConfig(name="run_skill_script", class_name="RunSkillScriptTool", source="builtin", params=parameters),
                            ]))

    info.history = [AgentHistory(role="user", content="Earlier question HISTORY_USER_MARKER"),
                    AgentHistory(role="assistant", content="Earlier answer HISTORY_ASSISTANT_MARKER")]
    if snapshot_history:
        info.context_input = ContextInput(items=(ContextItemInput(
            id="history:turn:1", type=ContextItemType.CONVERSATION_TURN,
            content={"user_message": info.history[0].content, "assistant_final_answer": info.history[1].content,
                     "user_message_id": 1, "assistant_message_id": 2},
        ),))
        info.history = [AgentHistory(role="user", content="UNAUTHORIZED_HISTORY_MARKER")]
    if transient_failure:
        info.query += " TRANSIENT_RETRY_MARKER"

    async def run():
        return [message async for message in agent_run(info, thread_manager=native_manager)]

    output = asyncio.run(run())
    state = httpx.get(native_provider + "/state", trust_env=False).json()
    assert info.attempt_outcome == "completed", (output[-1:], state)
    assert calls == [(2, 3)]
    expected_calls = 6 if transient_failure else 5
    assert state["mcp_calls"] == 1 and state["model_calls"] == expected_calls
    assert state["user_id"] == "fixture-user"
    assert state["saw_skill"]
    messages = state["messages"]
    serialized = json.dumps(messages)
    assert serialized.count("HISTORY_USER_MARKER") == 1
    assert serialized.count("HISTORY_ASSISTANT_MARKER") == 1
    assert "UNAUTHORIZED_HISTORY_MARKER" not in serialized
    assert messages[0]["role"] == "system"
    assert serialized.count(info.query) == 1
    assert "forbidden_tool" not in state["tools"] and "bash" not in state["tools"]
    assert all(Runner.resource_mgr.get_tool(card_id) is None for card_id in owned_cards)
    decoded = [json.loads(message) for message in output]
    final = [message for message in decoded if message.get("type") == "final_answer"]
    assert len(final) == 1 and "native_result_20" in str(final)
    assert any(message.get("type") == "tool" for message in decoded)
    assert sum(message.get("type") == "step_count" for message in decoded) == expected_calls

    # A new turn may use the completed result without re-running the old tool chain.
    follow_up = info.model_copy(update={
        "query": "What can you do? CURRENT_TASK_ONLY_MARKER", "observer": MessageObserver(lang="en"),
        "context_input": None,
        "history": [AgentHistory(role="user", content=info.query),
                    AgentHistory(role="assistant", content="native_result_20")],
    })

    async def run_follow_up():
        return [message async for message in agent_run(follow_up, thread_manager=native_manager)]

    second_output = asyncio.run(run_follow_up())
    second_state = httpx.get(native_provider + "/state", trust_env=False).json()
    assert follow_up.attempt_outcome == "completed", second_output[-1:]
    assert calls == [(2, 3)] and second_state["mcp_calls"] == 1
    assert second_state["model_calls"] == expected_calls + 1
    assert any("CURRENT_RESPONSE_MARKER" in message for message in second_output)
    assert all(Runner.resource_mgr.get_tool(card_id) is None for card_id in owned_cards)
