# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run one real lifespan discovery in a fresh process using configured production ports."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(root), str(root / "backend"), str(root / "sdk")]


async def main():
    from management.services.knowledge_base.ingestion_dispatch import (
        default_coordinator,
        ingestion_lifespan,
    )
    from nexent.core.concurrency import (
        LanePolicy,
        ThreadManager,
        clear_default_thread_manager,
        set_default_thread_manager,
    )

    manager = ThreadManager(
        service_name="ingestion-process-proof",
        lane_policies={
            "control-io": LanePolicy(
                name="control-io",
                max_workers=2,
                max_queue_size=4,
                queue_timeout_seconds=1,
                cancel_grace_seconds=2,
                shutdown_grace_seconds=4,
            ),
        },
    )
    manager.start()
    set_default_thread_manager(manager)
    coordinator = default_coordinator()
    advance, completed, rows = coordinator.advance, asyncio.Event(), []

    async def observed(file_id, actor, *, context):
        row = await advance(file_id, actor, context=context)
        rows.append(
            {
                "file_id": file_id,
                "stage": row["stage"],
                "job_id": row["forward_task_id"],
            }
        )
        completed.set()
        return row

    coordinator.advance = observed
    app = SimpleNamespace(state=SimpleNamespace())
    waiter = asyncio.create_task(completed.wait())
    try:
        async with ingestion_lifespan(app, enabled=True, coordinator=coordinator):
            (task,) = app.state.required_background_tasks
            await asyncio.wait(
                {waiter, task}, timeout=12, return_when=asyncio.FIRST_COMPLETED
            )
            if task.done():
                task.result()
            assert completed.is_set(), (
                "Fresh process did not observe its admitted ingestion"
            )
            assert not task.done(), "The ingestion lifespan task exited unexpectedly"
        assert task.done() and app.state.required_background_tasks == ()
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        drained = await manager.shutdown(timeout=4)
        clear_default_thread_manager(manager)
        assert not drained.stuck_execution_ids
    print(json.dumps(rows))


if __name__ == "__main__":
    asyncio.run(main())
