# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run current-source CoreAgent code against real Docker and published A2A peers."""

import ast
import asyncio
import hashlib
import inspect
import json
import logging
import sys
import traceback
from pathlib import Path

import requests

import docker
from agents.create_agent_info import create_model_config_list
from final_answers import final_answer_text
from nexent.core import agent_names
from nexent.core.agents import a2a_agent_proxy, nexent_agent, sandbox
from nexent.core.agents.agent_model import AgentConfig, ExternalA2AAgentConfig, ToolConfig
from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.core.concurrency.context import _reset_current_thread_manager, _set_current_thread_manager
from nexent.core.utils.observer import MessageObserver


class ModelOutputCapture(logging.Handler):
    def __init__(self, payload):
        super().__init__(logging.INFO)
        self.payload = payload

    def emit(self, record):
        if str(record.msg).startswith("MODEL OUTPUT"):
            self.payload.setdefault("_model_outputs", []).append(record.getMessage()[:1500])


def run(payload):
    root = Path(payload["source_root"]).resolve()
    fingerprints = {}
    for module in (agent_names, a2a_agent_proxy, nexent_agent, sandbox):
        path = Path(inspect.getfile(module)).resolve()
        assert path.is_relative_to(root), "Runtime imported the installed image instead of staged worktree source"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(root).as_posix()
        assert payload["fingerprints"][relative] == digest, f"Source fingerprint differs: {relative}"
        fingerprints[relative] = digest

    model_configs = asyncio.run(create_model_config_list(payload["tenant_id"]))
    selected = next(item for item in model_configs if item.cite_name == payload["model_name"])
    assert selected.api_key and selected.url, "Existing real model configuration is incomplete"
    payload["_private_values"] = [payload["access_key"], *(item.api_key for item in model_configs if item.api_key)]
    peers = [ExternalA2AAgentConfig(
        agent_id=str(item["external_id"]), name=item["name"], description="Echo the supplied test task.",
        url=item["agent_url"], protocol_type=item["protocol_type"], api_key=payload["access_key"], timeout=180,
    ) for item in payload["peers"]]
    for peer in payload["peers"]:
        response = requests.get(
            f'http://nexent-northbound:5013/nb/a2a/{peer["endpoint"]}/.well-known/agent-card.json', timeout=10,
        )
        response.raise_for_status()
        assert response.json()["name"] == peer["name"]
        assert peer["agent_url"].startswith("http://nexent-northbound:5013/nb/a2a/")
    peers = agent_names.resolve_external_agent_configs(peers, {"create_directory"})
    assert peers[0].name == peers[0].invocation_name == "parallel_probe_a"
    assert peers[1].name != peers[1].invocation_name
    assert {item.agent_id: item.invocation_name for item in peers} == {
        item.agent_id: item.invocation_name
        for item in agent_names.resolve_external_agent_configs(list(reversed(peers)), {"create_directory"})
    }
    manager = ThreadManager("callable-live", {
        "model-tool-io": LanePolicy("model-tool-io", 4, 8),
        "sandbox": LanePolicy("sandbox", 8, 16),
        "background-service": LanePolicy("background-service", 2, 4),
    })
    manager.start()
    binding = _set_current_thread_manager(manager)
    client = docker.from_env()
    results, leases = [], []
    payload["_leases"] = leases
    payload["_results"] = results

    class LiveFactory(nexent_agent.NexentAgent):
        def _cleanup_sandbox(self):
            try:
                for executor in self._sandbox_executors:
                    container = executor.container
                    leases.append({"container_id": container.id, "kernel_id": executor.kernel_id})
                    assert getattr(executor, "_nexent_backend", None) == "docker", "Local fallback is forbidden"
                    container.reload()
                    assert container.attrs["State"]["Running"]
                    assert executor.kernel_id, "An actual Jupyter kernel is required"
            finally:
                super()._cleanup_sandbox()

    composer = AgentPromptComposer(AgentPromptBundle.from_resource(role="manager", language="zh"))
    workspace = root / "tool-workspace"
    workspace.mkdir()
    format_hint = (
        " 首次响应必须用完整 <code>...</code> 输出实际工具调用，不要使用 Markdown 代码围栏。"
        "收到工具结果后，用完整 <final_answer>...</final_answer> 输出结果。"
    )
    scenarios = [
        ("directory", '只调用 create_directory(directory_path="test") 创建目录，不调用任何外部智能体。成功后简短确认。' + format_hint, None),
        ("legacy", f'只调用 parallel_probe_a(task="{payload["task"]}")，原样回复工具返回的完整标记。' + format_hint, 0),
        ("alias", f'只调用名为 {peers[1].name} 的外部智能体（其调用名为 {peers[1].invocation_name}），task 参数为 "{payload["task"]}"，原样回复工具返回的完整标记。' + format_hint, 1),
    ]
    try:
        for scenario, query, peer_index in scenarios:
            payload["_scenario"] = scenario
            observer = MessageObserver(lang="zh")
            scope = RunCancellationScope()
            factory = LiveFactory(
                observer, model_configs, scope.stop_event, cancellation_scope=scope,
                sandbox_config=sandbox.SandboxConfig(
                    level=sandbox.SandboxLevel.DOCKER, scope=sandbox.SandboxScope.SESSION,
                    failure_policy="error", timeout_seconds=180, auto_sync_outputs=False,
                ),
                user_context={"user_id": payload["user_id"], "tenant_id": payload["tenant_id"]},
            )
            tool = ToolConfig(
                class_name="CreateDirectoryTool", name="create_directory", source="local",
                params={"init_path": str(workspace)},
            )
            config = AgentConfig(
                name="A2A_test", description="Live callable-name regression", model_name=payload["model_name"],
                tools=[tool], external_a2a_agents=peers, max_steps=5, enable_protocol_repair_retry=True,
                prompt_templates=composer.compatibility_templates(),
                context_items=composer.compose_context_inputs(
                    prompt="严格执行用户指定的工具调用。不要猜测工具结果，收到返回后再给出最终回答。",
                    language="zh", is_manager=True, tools={"create_directory": tool},
                    external_a2a_agents={item.agent_id: item for item in peers},
                ),
            )
            offset = len(leases)
            try:
                factory.set_agent(factory.create_single_agent(config))
                factory.agent_run_with_observer(query)
                events = [json.loads(item) for item in observer.get_cached_message()]
                answer = final_answer_text(events)
                actions = [step.code_action for step in factory.agent.memory.steps if getattr(step, "code_action", None)]
                payload["_actions"] = actions
                failures = [str(step.error) for step in factory.agent.memory.steps if getattr(step, "error", None)]
                assert not failures, f"Code execution errors: {failures}"
                assert len(leases) > offset, "The action did not acquire a real Docker kernel"
                if peer_index is None:
                    assert (workspace / "test").is_dir()
                    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                               and node.func.id == "create_directory"
                               and any(key.arg == "directory_path" and isinstance(key.value, ast.Constant)
                                       and key.value.value == "test" for key in node.keywords)
                               for action in actions for node in ast.walk(ast.parse(action)))
                else:
                    peer = peers[peer_index]
                    expected = payload["peers"][peer_index]["marker"]
                    assert expected in answer and payload["task"] in answer, "Peer-only marker was not returned"
                    starts = [event for event in events if event.get("type") == "subagent_start"]
                    assert len(starts) == 1, "Exactly one intended A2A invocation is required"
                    event = starts[0]
                    assert event.get("agent_name") == peer.name
                    identity = json.loads(event["content"])
                    assert identity["invocation_name"] == peer.invocation_name
                    assert any(peer.invocation_name + "(" in action for action in actions)
                results.append({"scenario": scenario, "status": "PASS", "actions": actions,
                                "answer": answer,
                                "peer_marker_verified": peer_index is not None, "leases": leases[offset:]})
            finally:
                factory._cleanup_sandbox()
        for lease in leases:
            try:
                client.containers.get(lease["container_id"])
            except docker.errors.NotFound:
                continue
            raise AssertionError("Owned session sandbox container leaked")
        return {"status": "PASS", "fingerprints": fingerprints, "model": payload["model_name"],
                "scenarios": results, "aliases": {item.name: item.invocation_name for item in peers},
                "sandbox_cleanup": "PASS"}
    finally:
        _reset_current_thread_manager(binding)
        asyncio.run(manager.shutdown(timeout=10))
        client.close()


def main():
    logging.getLogger().setLevel(logging.WARNING)
    payload = json.load(sys.stdin)
    model_logger = logging.getLogger("model_call.core_agent")
    capture = ModelOutputCapture(payload)
    model_logger.addHandler(capture)
    model_logger.setLevel(logging.INFO)
    try:
        result = run(payload)
    except Exception as exc:
        detail = str(exc)
        for value in payload.get("_private_values", [payload.get("access_key")]):
            if value:
                detail = detail.replace(value, "***")
        result = {"status": "FAIL", "error_type": type(exc).__name__, "error": detail[:2000],
                  "leases": payload.get("_leases", []),
                  "scenario": payload.get("_scenario"), "scenarios": payload.get("_results", []),
                  "actions": payload.get("_actions", []),
                  "model_outputs": payload.get("_model_outputs", [])[-8:],
                  "frames": [f"{Path(frame.filename).name}:{frame.lineno}" for frame in traceback.extract_tb(exc.__traceback__)[-8:]]}
    model_logger.removeHandler(capture)
    serialized = json.dumps(result, ensure_ascii=False)
    for value in payload.get("_private_values", [payload.get("access_key")]):
        if value:
            serialized = serialized.replace(value, "***")
    print("LIVE_RESULT:" + serialized)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
