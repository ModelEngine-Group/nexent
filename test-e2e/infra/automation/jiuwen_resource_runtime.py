# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real native/text resource flows through managed workers and local protocol servers."""

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import Mock

import httpx

if sys.platform == "win32":
    for folder in ("pywin32_system32", "win32", "win32/lib"):
        sys.path.append(str(Path(httpx.__file__).resolve().parents[1] / folder))

from jiuwen_bridge_fixture import profile_for
import nexent.core.tools as nexent_agent
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentHistory, AgentRunInfo
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver


def read_workspace_evidence(path):
    """Inspect real outputs through Docker when Windows denies Linux-created file ACLs."""
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except PermissionError:
        if sys.platform != "win32":
            raise
        import docker

        client = docker.from_env()
        try:
            return client.containers.run(
                "nexent/nexent-sandbox-full:latest",
                ["-c", "from pathlib import Path; print(Path('/evidence/" + path.name + "').read_text(), end='')"],
                entrypoint="python", user="0", network_disabled=True, remove=True,
                volumes={str(path.parent): {"bind": "/evidence", "mode": "ro"}},
            ).decode()
        finally:
            client.close()


@contextmanager
def resource_provider(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "resource-provider.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("jiuwen_resource_provider.py")), str(port)],
            stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(150):
                if process.poll() is not None:
                    raise AssertionError("Controlled resource server exited")
                try:
                    if httpx.get(url + "/state", timeout=.2, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(.05)
            else:
                raise AssertionError("Controlled resource server did not become ready")
            yield url
        finally:
            process.terminate()
            process.wait(timeout=5)


async def run_resources(monkeypatch, tmp_path, url, protocol, scenario="normal", *, docker_sandbox=False):
    def forbidden(*args, **kwargs):
        raise AssertionError("Native provider client or CodeAgent constructed")

    monkeypatch.setattr("openjiuwen.core.foundation.llm.model.create_model_client", forbidden)
    monkeypatch.setattr(CoreAgent, "__init__", forbidden)
    monitoring = Mock()
    monitoring.trace_llm_request.side_effect = lambda *args, **kwargs: nullcontext(None)
    monkeypatch.setattr("nexent.core.model_service.service.get_monitoring_manager", lambda: monitoring)
    calls, owned_cards = [], []

    class ResourceAddTool:
        name, description = "add", "Add integers"
        inputs = {"a": {"type": "integer"}, "b": {"type": "integer"}}

        def forward(self, a, b):
            calls.append((a, b))
            return a + b

    monkeypatch.setattr(nexent_agent, "ResourceAddTool", ResourceAddTool, raising=False)
    prepare = JiuwenAdapter.prepare

    def track_prepare(adapter):
        prepare(adapter)
        if docker_sandbox:
            assert adapter.resources.agent.python_executor._nexent_backend == "docker"
        owned_cards.extend(card.id for card in adapter.native_agent.ability_manager.list())

    monkeypatch.setattr(JiuwenAdapter, "prepare", track_prepare)
    close = JiuwenAdapter.close

    def track_close(adapter):
        if adapter.native_agent is not None:
            owned_cards.extend(card.id for card in adapter.native_agent.ability_manager.list())
        close(adapter)

    monkeypatch.setattr(JiuwenAdapter, "close", track_close)
    skill = tmp_path / "skills" / "fixture_skill"
    (skill / "scripts").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: fixture_skill\ndescription: Fixture skill guide\n---\nSKILL_GUIDE_MARKER\n", encoding="utf-8",
    )
    effect = tmp_path / "run/outputs/script-effects.txt" if docker_sandbox else tmp_path / "script-effects.txt"
    (skill / "scripts/hello.py").write_text(
        f"from pathlib import Path\nimport os\np=Path(os.environ.get('NEXENT_OUTPUT_DIR', {str(effect.parent)!r}))/"
        "'script-effects.txt'\n"
        "p.write_text(p.read_text()+'x' if p.exists() else 'x')\nprint('SCRIPT_RESULT_MARKER')\n",
        encoding="utf-8",
    )
    hidden = skill.parent / "forbidden_skill"
    hidden.mkdir(exist_ok=True)
    (hidden / "SKILL.md").write_text("---\nname: forbidden_skill\ndescription: SECRET_SKILL\n---\n", encoding="utf-8")
    parameters = {"local_skills_dir": str(skill.parent), "authorized_skill_names": ["fixture_skill"],
                  "isolated_skills_root": True}
    sandbox = None
    if docker_sandbox:
        from nexent.core.agents.sandbox.config import SandboxConfig, SandboxLevel

        parameters["workspace_path"] = str(tmp_path / "run")
        sandbox = SandboxConfig(level=SandboxLevel.DOCKER, docker_image="nexent/nexent-sandbox-full:latest",
            network_disabled=False, timeout_seconds=30, workspace_mode="bind", container_workspace_root="/work",
            failure_policy="error", extra_kwargs={"workspace_root": str(tmp_path)})
    tools = [ToolConfig(name="add", class_name="ResourceAddTool", source="local", params={}),
             ToolConfig(name="multiply", class_name="multiply_values", source="mcp", params={"b": 4}),
             ToolConfig(name="read_skill_md", class_name="ReadSkillMdTool", source="builtin", params=parameters),
             ToolConfig(name="run_skill_script", class_name="RunSkillScriptTool", source="builtin", params=parameters)]
    if scenario == "parallel":
        tools.append(ToolConfig(name="parallel_executor", class_name="ParallelExecutorTool", source="builtin", params={}))
    manager = ThreadManager("jiuwen-resource-tests", {
        name: LanePolicy(name=name, max_workers=1 if name == "model-tool-io" else 2, max_queue_size=8)
        for name in ("agent-run", "model-tool-io", "mcp-session", "sandbox", "control-io", "background-service")
    })
    manager.start()
    profile = profile_for(url, protocol)
    info = AgentRunInfo(
        query="Run the authorized resource chain" + (" BLOCK_MCP_MARKER" if scenario in {"timeout", "cancel"}
                                                     else " PARALLEL_MARKER" if scenario == "parallel" else "")
              + (" NATIVE_FILE_MARKER" if docker_sandbox and protocol == "native" else ""),
        observer=MessageObserver(lang="en"), stop_event=threading.Event(), thread_manager=manager,
        tenant_id="spike-tenant", user_context={"user_id": "captured-user"},
        sandbox_config=sandbox, workspace_path=str(tmp_path / "run") if docker_sandbox else None,
        mcp_host=[url + "/mcp"], mcp_request_timeout_seconds=5, mcp_close_timeout_seconds=2,
        mcp_tool_timeout_seconds=.4 if scenario == "timeout" else 10,
        model_config_list=[ModelConfig(cite_name="fixture", model_name=profile.identity.request_model_id,
            url=profile.connection.base_url, api_key="fixture-only", resolved_profile=profile)],
        agent_config=AgentConfig(agent_core="jiuwen", name="resource-runtime", description="Fixture",
                                model_name="fixture", max_steps=6, tools=tools),
    )
    async def consume(run_info):
        events = []
        try:
            async for event in agent_run(run_info, thread_manager=manager):
                events.append(json.loads(event))
        except asyncio.CancelledError:
            if scenario != "cancel" or not run_info.stop_event.is_set():
                raise
            await asyncio.wait_for(asyncio.wrap_future(run_info.thread_future), timeout=5)
            events.extend(json.loads(event) for event in run_info.observer.get_cached_message())
        return events

    async def cancel_when_mcp_started():
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(500):
                state = (await client.get(url + "/state")).json()
                if state["mcp_calls"]:
                    info.stop_event.set()
                    return
                await asyncio.sleep(.01)
        raise AssertionError("MCP did not start")

    canceller = asyncio.create_task(cancel_when_mcp_started()) if scenario == "cancel" else None
    started = time.monotonic()
    try:
        output = await consume(info)
        if canceller:
            await canceller
        elapsed = time.monotonic() - started
        async with httpx.AsyncClient(trust_env=False) as client:
            state = (await client.get(url + "/state")).json()
        if scenario in {"normal", "parallel"}:
            assert info.attempt_outcome == "completed", output[-1:]
            if docker_sandbox and protocol == "native":
                artifact = tmp_path / "run/outputs/native-created.txt"
                assert read_workspace_evidence(artifact) == "NATIVE_SANDBOX_FILE_MARKER"
            previous = (len(calls), state["mcp_calls"], read_workspace_evidence(effect))
            follow_up = info.model_copy(update={
                "query": "What can you do? CURRENT_TASK_ONLY_MARKER", "observer": MessageObserver(lang="en"),
                "stop_event": threading.Event(), "cancellation_scope": None,
                "history": [AgentHistory(role="user", content=info.query),
                            AgentHistory(role="assistant", content="native_result_20")],
            })
            second = await consume(follow_up)
            assert follow_up.attempt_outcome == "completed", second[-1:]
            assert any("CURRENT_RESPONSE_MARKER" in str(event) for event in second)
            async with httpx.AsyncClient(trust_env=False) as client:
                later = (await client.get(url + "/state")).json()
            assert previous == (len(calls), later["mcp_calls"], read_workspace_evidence(effect))
        return info, state, output, calls, read_workspace_evidence(effect), elapsed
    finally:
        if canceller and not canceller.done():
            canceller.cancel()
            await asyncio.gather(canceller, return_exceptions=True)
        drained = await manager.shutdown(timeout=5)
        assert not drained.stuck_execution_ids
        assert manager.snapshot().active_count == 0
        from openjiuwen.core.runner import Runner

        assert all(Runner.resource_mgr.get_tool(card_id) is None for card_id in owned_cards)
