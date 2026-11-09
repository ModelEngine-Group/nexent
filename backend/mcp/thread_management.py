# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from nexent.core.concurrency import LanePolicy, ThreadManager

from contracts.constants.environment import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS


mcp_thread_manager = ThreadManager(
    service_name="api-to-mcp",
    lane_policies={
        "control-io": LanePolicy(
            name="control-io",
            max_workers=8,
            max_queue_size=16,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "background-service": LanePolicy(
            name="background-service",
            max_workers=12,
            max_queue_size=8,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
    },
)
