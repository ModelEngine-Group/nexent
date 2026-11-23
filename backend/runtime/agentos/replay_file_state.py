# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manage trial-local file I/O and its lifetime across cancellation."""
import asyncio

from fastapi import HTTPException
from nexent.core.agents.resources.replay_files import FILE_CLASSES, ReplayFileDirectory
from nexent.core.concurrency import run_blocking


async def _disk(operation, fn, *args):
    task = asyncio.create_task(run_blocking(operation, fn, *args, lane="control-io", owner="runtime"))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class TrialFileState:
    def __init__(self, info):
        self.info = info
        self.directory = None
        self.expected_bindings = set()

    async def prepare(self, initial):
        config = self.info.agent_config
        unsupported = [tool.class_name for tool in config.tools if not (
            tool.source == "builtin" and tool.class_name in {"DownloadFromS3Tool", "UploadToS3Tool"}
            or tool.source == "local" and (tool.class_name in FILE_CLASSES or tool.class_name == "ParallelExecutorTool"))]
        if config.worker_agents or config.external_a2a_agents or unsupported:
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_FILE_STATE_UNSUPPORTED_BINDINGS", "tools": unsupported})

        def attach():
            self.directory = ReplayFileDirectory(initial)
            self.info.observer.replay_file_directory = self.directory
            for tool in config.tools:
                if tool.class_name in FILE_CLASSES:
                    self.expected_bindings.add(tool.class_name)
                    tool.params = {**(tool.params or {}), "init_path": str(self.directory.root)}
            self.info.tool_fastpath_enabled = False

        await _disk("prepare-replay-files", attach)

    async def receipt(self):
        try:
            state = await _disk("read-replay-files", self.directory.receipt)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail={"code": "AGENTOS_FILE_STATE_UNREADABLE"}) from exc
        state["complete"] = state["complete"] and set(state["bound"]) == self.expected_bindings
        return state

    async def release(self):
        if self.directory is None:
            return
        worker = self.info.thread_future
        if worker is not None and not worker.done():
            worker.add_done_callback(lambda _: self.directory.close())
        else:
            await _disk("release-replay-files", self.directory.close)
