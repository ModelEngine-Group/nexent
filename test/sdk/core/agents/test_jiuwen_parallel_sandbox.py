# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep each native Python delegation's resources and cancellation local to the call."""

import asyncio
import json
from pathlib import Path
from threading import Event, Lock

import pytest

from nexent.core.agents.contracts.config import AgentConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.orchestration.children import child_run_info, invoke_child
from nexent.core.agents.sandbox.config import SandboxConfig, SandboxLevel, SandboxScope, ShellPolicy
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.core.utils.observer import MessageObserver


def run_info(**options):
    return AgentRunInfo(query="task", model_config_list=[], observer=MessageObserver(), stop_event=Event(),
                        agent_config=AgentConfig(name="agent", description="Agent", model_name="model", tools=[]),
                        **options)


@pytest.mark.parametrize("sandbox_scope", [SandboxScope.SYSTEM, SandboxScope.SESSION])
def test_python_children_use_distinct_workspaces_and_keep_nexent_policy(tmp_path, sandbox_scope):
    root = tmp_path / "root"
    root.mkdir()
    config = SandboxConfig(level=SandboxLevel.DOCKER, scope=sandbox_scope, network_disabled=True,
                           shell_policy=ShellPolicy.RESTRICTED, extra_kwargs={"workspace_root": str(tmp_path)})
    parent = run_info(workspace_path=str(root), sandbox_config=config, minio_files=[{"object_name": "authorized"}])
    access_check = object()
    parent.agent_config.tools = [
        ToolConfig(name="download_from_s3", class_name="DownloadFromS3Tool", source="builtin",
                   params={"workspace_path": str(root)}, metadata={"validate_url_access": access_check}),
        ToolConfig(name="upload_to_s3", class_name="UploadToS3Tool", source="builtin",
                   params={"workspace_path": str(root)}, metadata={"run_id": "root"}),
    ]
    first, second = [child_run_info(parent, parent.agent_config, RunCancellationScope(), parallel_mode="sandbox")
                     for _ in range(2)]
    assert first.workspace_run_id != second.workspace_run_id
    for info in (first, second):
        directory = Path(info.workspace_path)
        assert directory.parent == root.parent.resolve() and directory.name == info.workspace_run_id
        assert info.sandbox_config.output_dir == str(directory / "outputs")
        assert info.sandbox_config.extra_kwargs["workspace_root"] == str(tmp_path)
        assert info.sandbox_config.scope == config.scope and info.sandbox_config.level == config.level
        assert info.sandbox_config.network_disabled and info.sandbox_config.shell_policy == ShellPolicy.RESTRICTED
        assert info.sandbox_config.failure_policy == "error"
        assert info.minio_files == parent.minio_files and info.minio_files is not parent.minio_files
        download, upload = info.agent_config.tools
        assert download.params["workspace_path"] == upload.params["workspace_path"] == str(directory)
        assert download.metadata["validate_url_access"] is access_check
        assert upload.metadata["run_id"] == info.workspace_run_id
    assert parent.sandbox_config.failure_policy == "local"
    assert parent.agent_config.tools[1].metadata["run_id"] == "root"


def test_child_returns_only_published_artifact_references(mocker):
    info = run_info()

    def complete(run, *, run_scope):
        run.published_child_files = [{"name": "same.txt", "url": "s3://test/workspace/owned/outputs/same.txt"}]
        return "child answer"

    mocker.patch("nexent.core.agents.orchestration.children.execute_adapter", side_effect=complete)
    tool_result = json.loads(invoke_child(info, "Generate a file"))
    assert tool_result == {"answer": "child answer", "artifacts": info.published_child_files}


@pytest.mark.asyncio
async def test_one_native_child_timeout_keeps_parent_and_later_sibling_alive(mocker):
    adapter = JiuwenAdapter(run_info(collaboration_timeout_seconds=0.6))
    adapter.scope = RunCancellationScope(adapter.run_info.stop_event)
    adapter.manager = ThreadManager("child-timeout", {"control-io": LanePolicy(name="control-io", max_workers=2,
                                                                              max_queue_size=2)})
    adapter.manager.start()
    adapter._parallel_child_calls = {"slow": "sandbox", "peer": "sandbox"}
    mocker.patch.object(adapter.events, "tool_call", side_effect=lambda name, arguments, call, **_: arguments["task"])
    slow_started, slow_stopped = Event(), Event()

    def forward(task):
        scope, mode = adapter._child_context.get()
        assert mode == "sandbox"
        if task == "slow":
            slow_started.set()
            assert scope.stop_event.wait(3)
            slow_stopped.set()
        else:
            assert slow_stopped.wait(3)
            assert not scope.cancelled
        return task

    handler = adapter._business_handler("child", forward, lane="control-io", local_child=True)
    try:
        slow = asyncio.create_task(handler(task="slow"))
        deadline = asyncio.get_running_loop().time() + 0.4
        while not slow_started.is_set() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert slow_started.is_set()
        await asyncio.sleep(0.2)
        results = await asyncio.gather(slow, handler(task="peer"), return_exceptions=True)
        assert isinstance(results[0], TimeoutError) and results[1] == "peer"
        assert not adapter.scope.cancelled
    finally:
        drained = await adapter.manager.shutdown(timeout=3)
    assert not drained.stuck_execution_ids


@pytest.mark.asyncio
async def test_native_python_batch_respects_the_parent_slot_limit(mocker):
    adapter = JiuwenAdapter(run_info(collaboration_timeout_seconds=4))
    adapter.scope = RunCancellationScope(adapter.run_info.stop_event)
    adapter.manager = ThreadManager("child-capacity", {"control-io": LanePolicy(name="control-io", max_workers=6,
                                                                               max_queue_size=4)})
    adapter.manager.start()
    tasks = [f"child-{index}" for index in range(5)]
    adapter._parallel_child_calls = dict.fromkeys(tasks, "sandbox")
    mocker.patch.object(adapter.events, "tool_call", side_effect=lambda name, arguments, call, **_: arguments["task"])
    release, full = Event(), Event()
    starts = []
    lock = Lock()

    def forward(task):
        with lock:
            starts.append(task)
            if len(starts) >= 4:
                full.set()
        assert release.wait(3)
        return task

    handler = adapter._business_handler("child", forward, lane="control-io", local_child=True)
    batch = asyncio.gather(*(handler(task=task) for task in tasks))
    try:
        async with asyncio.timeout(2):
            while not full.is_set():
                await asyncio.sleep(0.01)
        assert len(starts) == 4
    finally:
        release.set()
        results = await batch
        drained = await adapter.manager.shutdown(timeout=3)
    assert results == tasks and set(starts) == set(tasks)
    assert not drained.stuck_execution_ids
