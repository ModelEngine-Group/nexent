"""Northbound title-generation thread admission regressions."""

import pytest

from nexent.core.concurrency import ManagedTaskSpec
from services.thread_lifecycle_service import northbound_thread_manager


@pytest.mark.asyncio
async def test_northbound_model_lane_executes_and_releases_work():
    manager = northbound_thread_manager
    manager.start()
    try:
        result = await manager.run(
            "model-tool-io", ManagedTaskSpec(task_name="title-test", owner="test"),
            lambda: "Generated title",
        )
        assert result == "Generated title"
        with pytest.raises(ValueError, match="provider failure"):
            await manager.run(
                "model-tool-io", ManagedTaskSpec(task_name="title-error", owner="test"),
                lambda: (_ for _ in ()).throw(ValueError("provider failure")),
            )
        lane = next(lane for lane in manager.snapshot().lanes if lane.name == "model-tool-io")
        assert lane.active_count == 0
        assert lane.max_workers > 0
        assert lane.capacity == lane.max_workers + lane.max_queue_size
    finally:
        result = await manager.shutdown(timeout=5)
        assert result.stuck_execution_ids == ()
