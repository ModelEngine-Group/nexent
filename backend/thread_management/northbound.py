# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from nexent.core.concurrency import LanePolicy, ThreadManager

from contracts.constants.environment import (
    NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE,
    NORTHBOUND_CONTROL_THREAD_MAX_WORKERS,
    NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS,
)


northbound_thread_manager = ThreadManager(
    service_name="northbound",
    lane_policies={
        "model-tool-io": LanePolicy(
            name="model-tool-io",
            max_workers=6,
            max_queue_size=16,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "control-io": LanePolicy(
            name="control-io",
            max_workers=NORTHBOUND_CONTROL_THREAD_MAX_WORKERS,
            max_queue_size=NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE,
            queue_timeout_seconds=0,
            cancel_grace_seconds=2,
            shutdown_grace_seconds=NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "background-service": LanePolicy(
            name="background-service",
            max_workers=12,
            max_queue_size=8,
            queue_timeout_seconds=0,
            cancel_grace_seconds=2,
            shutdown_grace_seconds=NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
    },
)
