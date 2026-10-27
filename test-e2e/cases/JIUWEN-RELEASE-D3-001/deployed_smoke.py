# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run inside the deployed backend; report only synthetic outcomes, never credentials."""

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx
from management.db.client import get_db_session
from management.db.models import ConversationMessage, ModelRecord, UserTenant
from nexent.core.agents import nexent_agent
from nexent.core.agents.agent_model import (
    AgentConfig,
    AgentHistory,
    AgentRunInfo,
    ExternalA2AAgentConfig,
    ModelConfig,
    ToolConfig,
)
from nexent.core.agents.run_agent import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver
from management.services.configuration.user.memory import get_memory_switch
from management.services.model.runtime_snapshot import restore_runtime_model_snapshot
from smolagents import Tool
from management.services.permission.identity.authentication_helpers import generate_session_jwt

NATIVE, TEXT, TENANT = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
RESULT = {}


def saved_model(model_id, alias):
    with get_db_session() as session:
        model = session.query(ModelRecord).filter_by(model_id=model_id, tenant_id=TENANT, delete_flag="N").one()
        row = {c.name: getattr(model, c.name) for c in ModelRecord.__table__.columns}
        profile = restore_runtime_model_snapshot(row, TENANT, strict=True)
        return ModelConfig(
            cite_name=alias,
            model_name=profile.identity.request_model_id,
            api_key=model.api_key,
            url=profile.connection.base_url,
            resolved_profile=profile,
        )


def checked(response):
    assert response.status_code == 200, "API status " + str(response.status_code) + " at " + response.request.url.path
    return response.json()


def http_history():
    with get_db_session() as session:
        identity = next(
            (
                user
                for user in session.query(UserTenant).filter_by(tenant_id=TENANT, delete_flag="N")
                if not get_memory_switch(user.user_id)
            ),
            None,
        )
        assert identity is not None, "A memory-disabled test identity is required to prove database-only continuity"
        token = generate_session_jwt(identity.user_id, expires_in=1800)
    headers = {"Authorization": "Bearer " + token}
    config = httpx.Client(base_url="http://nexent-config:5010", headers=headers, trust_env=False, timeout=240)
    runtime = httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=240)
    agent, conversation = None, None
    marker = "M6_HISTORY_" + uuid.uuid4().hex[:12]
    try:
        request = {
            "name": "m6-" + uuid.uuid4().hex[:8],
            "description": "Temporary M6 verification",
            "model_ids": [NATIVE],
            "business_logic_model_id": NATIVE,
            "max_steps": 6,
            "agent_core": "smolagents",
            "is_main_agent": False,
            "provide_run_summary": False,
            "enable_context_manager": False,
            "enabled": True,
            "enabled_tool_ids": [],
            "enabled_skill_ids": [],
            "related_agent_ids": [],
            "duty_prompt": "Answer only the current question. Remember conversation facts. Never repeat old tasks.",
        }
        agent = checked(config.post("/agent/update", json=request))["agent_id"]
        checked(
            config.post(f"/agent/{agent}/publish", json={"version_name": "m6-1", "release_note": "Temporary smoke"})
        )
        data = checked(runtime.put("/conversation/create", json={"title": "M6 synthetic history"}))["data"]
        conversation = data["conversation_id"]
        first_snapshot = None
        outcomes = []
        for index, core in enumerate(["smolagents", "jiuwen", "smolagents"]):
            if index:
                checked(config.post("/agent/update", json={"agent_id": agent, "agent_core": core}))
                checked(
                    config.post(
                        f"/agent/{agent}/publish",
                        json={"version_name": "m6-" + str(index + 1), "release_note": "Temporary Core switch"},
                    )
                )
                loaded = checked(runtime.get(f"/conversation/{conversation}"))
                assert marker in json.dumps(loaded), "History reload lost synthetic marker"
            query = (
                "Remember this verification code: " + marker + ". Reply with the code only."
                if not index
                else (
                    "What verification code did I ask you to remember? Reply with that code only; do not repeat old tasks."
                )
            )
            response = runtime.post(
                "/agent/run",
                json={
                    "agent_id": agent,
                    "conversation_id": conversation,
                    "query": query,
                    "history": None if index == 0 else [],
                    "minio_files": [],
                },
            )
            assert response.status_code == 200, "Runtime HTTP status"
            events = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
            assert not any(e.get("type") == "tool" and e.get("tool_name") != "final_answer" for e in events), (
                "Unexpected tool kinds="
                + repr([(e.get("tool_name"), sorted(e)) for e in events if e.get("type") == "tool"])
            )
            if core == "jiuwen":
                terminals = [e for e in events if e.get("type") == "run_terminal" and not e.get("invocation_id")]
                assert len(terminals) == 1 and terminals[0]["status"] == "completed", "Root terminal missing"
            for _ in range(50):
                with get_db_session() as session:
                    messages = (
                        session.query(ConversationMessage)
                        .filter_by(conversation_id=conversation)
                        .order_by(ConversationMessage.message_index, ConversationMessage.message_id)
                        .all()
                    )
                    snapshot = [(m.message_id, m.message_role, m.message_content, m.status) for m in messages]
                    assert [m.message_index for m in messages] == list(range(len(messages))), "Server order regressed"
                assistants = [m for m in snapshot if m[1] == "assistant"]
                if len(assistants) == index + 1 and assistants[-1][3] == "completed":
                    break
                time.sleep(0.1)
            assert assistants[-1][3] == "completed" and marker in (assistants[-1][2] or ""), (
                "Persisted answer mismatch"
            )
            if first_snapshot is None:
                first_snapshot = snapshot
            else:
                assert snapshot[: len(first_snapshot)] == first_snapshot, "Original history changed"
            outcomes.append(
                {
                    "core": core,
                    "completed": True,
                    "history_loaded": index > 0,
                    "pre_run_memory_searches": sum(e.get("tool_name") == "search_memory" for e in events),
                }
            )
        RESULT["deployed_http_history"] = outcomes
    finally:
        if conversation:
            checked(runtime.delete(f"/conversation/{conversation}"))
        if agent:
            checked(config.request("DELETE", "/agent", json={"agent_id": agent}))
        config.close()
        runtime.close()


async def sdk_resources(directory, url, protocol):
    effects = []

    class M6AddTool:
        name, description = "add", "Add two integers."
        inputs = {"a": {"type": "integer"}, "b": {"type": "integer"}}

        def forward(self, a, b):
            effects.append((a, b))
            return a + b

    nexent_agent.M6AddTool = M6AddTool
    skills = directory / protocol / "skills"
    skill = skills / "fixture_skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: fixture_skill\ndescription: M6 synthetic skill\n---\nM6_SKILL_GUIDE\n")
    effect_file = directory / (protocol + "-effects.txt")
    (skill / "scripts/hello.py").write_text(
        "from pathlib import Path\np=Path("
        + repr(str(effect_file))
        + ")\np.write_text(p.read_text()+'x' if p.exists() else 'x')\nprint('M6_SCRIPT_OK')\n"
    )
    params = {
        "local_skills_dir": str(skills),
        "authorized_skill_names": ["fixture_skill"],
        "isolated_skills_root": True,
    }
    tools = [
        ToolConfig(name="add", class_name="M6AddTool", source="local", params={}),
        ToolConfig(name="multiply", class_name="multiply", source="mcp", params={}),
        ToolConfig(name="read_skill_md", class_name="ReadSkillMdTool", source="builtin", params=params),
        ToolConfig(name="run_skill_script", class_name="RunSkillScriptTool", source="builtin", params=params),
    ]
    model = saved_model(NATIVE if protocol == "native" else TEXT, "resource-model")
    manager = make_manager()
    try:
        config = AgentConfig(
            agent_core="jiuwen",
            name="m6-resource",
            description="M6",
            model_name=model.cite_name,
            max_steps=10,
            tools=tools,
        )
        info = AgentRunInfo(
            query="Execute these actions in order exactly once: add(a=2,b=3), multiply(a=5,b=4), "
            "read_skill_md(skill_name='fixture_skill'), run_skill_script(skill_name='fixture_skill', "
            "script_path='scripts/hello.py'). You MUST call all four tools. Then reply M6_CHAIN_OK.",
            agent_config=config,
            model_config_list=[model],
            tenant_id=TENANT,
            observer=MessageObserver(lang="en"),
            stop_event=threading.Event(),
            thread_manager=manager,
            mcp_host=[url + "/mcp"],
            model_deadline=time.monotonic() + 240,
        )
        events = [json.loads(e) async for e in agent_run(info, thread_manager=manager)]
        assert not model.api_key or model.api_key not in json.dumps(events), "Credential exposed in public events"
        assert info.attempt_outcome == "completed", "Resource run failed: " + str(info.run_result.end_reason)
        names = [e.get("tool_name") for e in events if e["type"] == "tool"]
        assert all(names.count(n) == 1 for n in ("add", "multiply", "read_skill_md", "run_skill_script")), (
            "Resource effects missing or repeated"
        )
        assert effects == [(2, 3)] and effect_file.read_text() == "x", "Local/skill effect mismatch"
        pairs = {e["tool_name"]: e.get("local_call_id") for e in events if e["type"] == "tool"}
        results = {
            name: " ".join(
                e.get("result", e.get("content", ""))
                for e in events
                if e["type"] == "tool_result" and e.get("local_call_id") == call_id
            )
            for name, call_id in pairs.items()
        }
        assert "20" in results["multiply"] and "M6_SKILL_GUIDE" in results["read_skill_md"]
        assert "M6_SCRIPT_OK" in results["run_skill_script"]
        state = httpx.get(url + "/state", trust_env=False).json()
        assert state["model_calls"] == 0, "Real provider was replaced by a local model fixture"
        before = state["mcp_calls"]
        follow = info.model_copy(
            update={
                "query": "Reply M6_FOLLOW_OK only. Do not call any tools.",
                "history": [
                    AgentHistory(role="user", content=info.query),
                    AgentHistory(role="assistant", content=info.run_result.final_content),
                ],
                "observer": MessageObserver(lang="en"),
                "stop_event": threading.Event(),
                "cancellation_scope": None,
                "model_deadline": time.monotonic() + 180,
            }
        )
        _ = [e async for e in agent_run(follow, thread_manager=manager)]
        assert follow.attempt_outcome == "completed" and "M6_FOLLOW_OK" in follow.run_result.final_content
        assert effects == [(2, 3)] and effect_file.read_text() == "x"
        assert httpx.get(url + "/state", trust_env=False).json()["mcp_calls"] == before
        RESULT[protocol + "_resources"] = {"tools": names, "completed": True, "followup_no_replay": True}
    finally:
        drained = await manager.shutdown(timeout=8)
        assert not drained.stuck_execution_ids and manager.snapshot().active_count == 0


def make_manager():
    manager = ThreadManager(
        "m6-real-smoke",
        {
            name: LanePolicy(name=name, max_workers=3, max_queue_size=12)
            for name in ("agent-run", "model-tool-io", "mcp-session", "sandbox", "control-io", "background-service")
        },
    )
    manager.start()
    return manager


async def collaborators(child_core):
    effects, requests = [], []

    class M6EchoTool(Tool):
        name, description, inputs = "child_echo", "Return the M6 child marker.", {}
        output_type = "string"

        def forward(self):
            effects.append("child")
            return "M6_CHILD_OK"

    nexent_agent.M6EchoTool = M6EchoTool
    model = saved_model(NATIVE, "parent-model")
    child_model = saved_model(TEXT if child_core == "smolagents" else NATIVE, "child-model")

    async def handle(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            size = next(
                int(line.split(b":", 1)[1])
                for line in header.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            body = json.loads(await reader.readexactly(size))
            requests.append(body)
            output = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {"message": {"role": "agent", "parts": [{"text": "M6_REMOTE_OK"}]}},
                }
            ).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(output)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + output
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    manager = make_manager()
    try:
        async with server:
            child = AgentConfig(
                agent_core=child_core if child_core != "a2a" else "jiuwen",
                name="delegate",
                invocation_name="delegate",
                description="Execute the delegated task",
                model_name=child_model.cite_name,
                runtime_model_config=child_model,
                max_steps=5,
                tools=[ToolConfig(name="child_echo", class_name="M6EchoTool", source="local", params={})],
                instructions=(
                    "You must invoke child_echo exactly once and return its marker. "
                    + (
                        "After the observation, respond with <final_answer>M6_CHILD_OK</final_answer>. "
                        "Never call final_answer() as a Python function and never call child_echo again."
                        if child_core == "smolagents"
                        else ""
                    )
                ),
            )
            external = ExternalA2AAgentConfig(
                agent_id="m6-remote",
                name="delegate",
                description="Return remote marker",
                url="http://127.0.0.1:" + str(server.sockets[0].getsockname()[1]),
                protocol_type="JSONRPC",
                timeout=15,
            )
            root = AgentConfig(
                agent_core="jiuwen",
                name="m6-parent",
                description="M6",
                model_name=model.cite_name,
                tools=[],
                max_steps=5,
                worker_agents=[] if child_core == "a2a" else [child],
                external_a2a_agents=[external] if child_core == "a2a" else [],
            )
            task = (
                "Return the remote marker"
                if child_core == "a2a"
                else "Invoke child_echo exactly once and return its marker"
            )
            info = AgentRunInfo(
                query="You MUST call delegate exactly once with task: "
                + task
                + ". Reply with the exact marker from delegate. Do not invent the result.",
                agent_config=root,
                model_config_list=[model],
                tenant_id=TENANT,
                observer=MessageObserver(lang="en"),
                stop_event=threading.Event(),
                thread_manager=manager,
                model_deadline=time.monotonic() + 240,
                collaboration_timeout_seconds=180,
            )
            events = [json.loads(e) async for e in agent_run(info, thread_manager=manager)]
            assert info.attempt_outcome == "completed", "Collaboration run failed: " + str(info.run_result.end_reason)
            expected = "M6_REMOTE_OK" if child_core == "a2a" else "M6_CHILD_OK"
            diagnostics = {
                "core": child_core,
                "effects": len(effects),
                "remote_requests": len(requests),
                "marker_in_result": expected in info.run_result.final_content,
                "tool_result_errors": [e.get("is_error") for e in events if e["type"] == "tool_result"],
                "child_terminals": [
                    e.get("status") for e in events if e["type"] == "run_terminal" and e.get("invocation_id")
                ],
            }
            assert expected in info.run_result.final_content, "Collaboration marker missing: " + json.dumps(
                diagnostics
            )
            assert len(requests) == 1 if child_core == "a2a" else effects == ["child"], (
                "Collaboration effect count: " + json.dumps(diagnostics)
            )
            assert any(e["type"] == "subagent_start" for e in events), "Child invocation event missing"
            RESULT["collaboration_" + child_core] = {
                "completed": True,
                "effects": len(requests) if child_core == "a2a" else len(effects),
            }
    finally:
        server.close()
        await server.wait_closed()
        drained = await manager.shutdown(timeout=8)
        assert not drained.stuck_execution_ids and manager.snapshot().active_count == 0


def progress(phase):
    Path("/tmp/m6-smoke-progress.json").write_text(json.dumps({"phase": phase, "completed": list(RESULT)}))


async def main():
    progress("http-history")
    http_history()
    with tempfile.TemporaryDirectory(prefix="m6-real-") as raw:
        directory = Path(raw)
        import socket

        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "/tmp/m6_resource_provider.py", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            url = "http://127.0.0.1:" + str(port)
            for _ in range(100):
                try:
                    if httpx.get(url + "/state", trust_env=False, timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            progress("native-resources")
            await sdk_resources(directory, url, "native")
            progress("text-resources")
            await sdk_resources(directory, url, "text")
            for core in ("jiuwen", "smolagents", "a2a"):
                progress("collaboration-" + core)
                await collaborators(core)
        finally:
            process.terminate()
            process.wait(timeout=10)
    import nexent.monitor.monitoring as monitoring
    from nexent.core.concurrency.helpers import shutdown_fallback_thread_manager

    if monitoring._monitoring_buffer is not None:
        monitoring._monitoring_buffer.stop()
    await shutdown_fallback_thread_manager(timeout=8)
    progress("completed")
    print("SMOKE_RESULT=" + json.dumps(RESULT))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        detail = str(error)[:180] if isinstance(error, AssertionError) else "See exception category"
        print("SMOKE_FAILURE=" + type(error).__name__ + ":" + detail)
        print("SMOKE_PARTIAL=" + json.dumps(RESULT))
        raise SystemExit(1)
