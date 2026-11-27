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
from infrastructure.rdb.client import get_db_session
from management.db.models import ConversationMessage, ConversationMessageUnit, ModelRecord, UserTenant
from nexent.core.agents.cores.smolagents import agent as nexent_agent
from nexent.core.agents.contracts.config import AgentConfig, ExternalA2AAgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentHistory, AgentRunInfo
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver
from management.services.configuration.user.memory import get_memory_switch
from infrastructure.model_adapter import restore_model_snapshot
from smolagents import Tool
from management.services.permission.identity.session import generate_session_jwt

NATIVE, TEXT, TENANT = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
RESULT = {}
PHASE, ACTOR, RAW_CHECKPOINT, PROVIDER = sys.argv[4:8]
CHECKPOINT = Path(RAW_CHECKPOINT)


def saved_model(model_id, alias):
    with get_db_session() as session:
        model = session.query(ModelRecord).filter_by(model_id=model_id, tenant_id=TENANT, delete_flag="N").one()
        row = {c.name: getattr(model, c.name) for c in ModelRecord.__table__.columns}
        profile = restore_model_snapshot(row, TENANT)
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


def http_history(phase, checkpoint, actor):
    """Execute one authorized phase so the caller can switch the owned deployment."""
    state = json.loads(checkpoint.read_text()) if checkpoint.is_file() else {}
    with get_db_session() as session:
        session.query(UserTenant).filter_by(user_id=actor, tenant_id=TENANT, delete_flag="N").one()
    assert not get_memory_switch(actor), "An explicit memory-disabled test actor is required"
    token = generate_session_jwt(actor, expires_in=1800)
    headers = {"Authorization": "Bearer " + token}
    with httpx.Client(base_url="http://nexent-gateway:5013/api", headers=headers, trust_env=False, timeout=240) as api:
        if phase == "cleanup":
            if state.get("conversation"):
                checked(api.delete(f"/conversation/{state['conversation']}"))
                state.pop("conversation")
                checkpoint.write_text(json.dumps(state))
            if state.get("agent"):
                checked(api.request("DELETE", "/agent", json={"agent_id": state["agent"]}))
                state.pop("agent")
            checkpoint.unlink(missing_ok=True)
            return
        if phase == "prepare":
            assert not state
            state["marker"] = "M6_HISTORY_" + uuid.uuid4().hex[:12]
            state["agent"] = checked(api.post("/agent/update", json={
                "name": "m6_" + uuid.uuid4().hex[:8],
                "description": "Temporary M6 verification",
                "model_ids": [NATIVE],
                "business_logic_model_id": NATIVE,
                "max_steps": 6,
                "is_main_agent": False,
                "provide_run_summary": False,
                "enable_context_manager": False,
                "enabled": True,
                "enabled_tool_ids": [],
                "enabled_skill_ids": [],
                "related_agent_ids": [],
                "duty_prompt": "Answer only the current question. Remember conversation facts. Never repeat old tasks.",
            }))["agent_id"]
            checkpoint.write_text(json.dumps(state))
            state["version"] = checked(api.post(f"/agent/{state['agent']}/publish", json={
                "version_name": "m6-history", "release_note": "Temporary smoke",
            }))["version_no"]
            state["conversation"] = checked(api.put("/conversation/create", json={
                "title": "M6 synthetic history",
            }))["data"]["conversation_id"]
            checkpoint.write_text(json.dumps(state))
            return

        index = int(phase)
        expected_core = ("smolagents", "jiuwen", "smolagents")[index]
        assert checked(api.get("/tenant_config/deployment_version"))["agent_core"] == expected_core
        marker, conversation = state["marker"], state["conversation"]
        if index:
            loaded = checked(api.get(f"/conversation/{conversation}"))
            assert marker in json.dumps(loaded), "History reload lost synthetic marker"
        query = (f"Remember this verification code: {marker}. Reply with the code only." if not index else
                 "What verification code did I ask you to remember? Reply with that code only; do not repeat old tasks.")
        response = api.post("/agent/run", json={
            "agent_id": state["agent"], "version_no": state["version"], "conversation_id": conversation,
            "query": query, "history": [], "minio_files": [],
        })
        assert response.status_code == 200, "Runtime HTTP status"
        events = [json.loads(line[5:].strip()) for line in response.text.splitlines()
                  if line.startswith("data:") and line[5:].strip() != "[DONE]"]
        assert not any(e.get("type") == "error" for e in events), "History execution produced a terminal error"
        assert not any(e.get("type") == "tool" and e.get("tool_name") != "final_answer" for e in events)
        if expected_core == "jiuwen":
            finals = [e for e in events if e.get("type") == "final_answer"
                      and e.get("answer_phase") == "complete" and not e.get("invocation_id")]
            assert len(finals) == 1 and marker in finals[0]["content"], "Root completion missing"

        for _ in range(50):
            with get_db_session() as session:
                rows = session.query(ConversationMessage).filter_by(conversation_id=conversation).order_by(
                    ConversationMessage.message_index, ConversationMessage.message_id
                ).all()
                snapshot = [[m.message_id, m.message_role, m.message_content, m.status] for m in rows]
                assert [m.message_index for m in rows] == list(range(len(rows))), "Server order regressed"
                assistants = [m for m in rows if m.message_role == "assistant"]
                if len(assistants) == index + 1 and assistants[-1].status == "completed":
                    if expected_core == "jiuwen":
                        terminals = session.query(ConversationMessageUnit).filter_by(
                            message_id=assistants[-1].message_id, unit_type="run_terminal"
                        ).all()
                        root_terminals = [unit for unit in terminals if not unit.invocation_id]
                        assert len(root_terminals) == 1 and json.loads(root_terminals[0].unit_content)["status"] == "completed"
                    break
            time.sleep(0.1)
        assert len(snapshot) == 2 * (index + 1) and snapshot[-1][3] == "completed"
        assert marker in (snapshot[-1][2] or ""), "Persisted answer mismatch"
        original = state.get("original", snapshot)
        assert snapshot[:len(original)] == original, "Original history changed"
        state["original"] = original
        checkpoint.write_text(json.dumps(state))
        RESULT["deployed_http_history"] = {
            "core": expected_core, "completed": True, "history_loaded": index > 0,
            "pre_run_memory_searches": sum(e.get("tool_name") == "search_memory" for e in events),
        }

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
    CHECKPOINT.with_suffix(".progress.json").write_text(json.dumps({"phase": phase, "completed": list(RESULT)}))


async def main():
    if PHASE != "sdk":
        http_history(PHASE, CHECKPOINT, ACTOR)
        print("SMOKE_RESULT=" + json.dumps(RESULT))
        return
    with tempfile.TemporaryDirectory(prefix="m6-real-") as raw:
        directory = Path(raw)
        import socket

        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, PROVIDER, str(port)],
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
