# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contracts.constants.constants import (
    MAX_CONCURRENT_CONVERSIONS,
    MAX_CONCURRENT_UPLOADS,
)
from contracts.constants.environment import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
from nexent.core.concurrency import LanePolicy, ThreadManager

config_thread_manager = ThreadManager(
    service_name="config",
    lane_policies={
        "file-stream": LanePolicy(
            name="file-stream",
            max_workers=5,
            max_queue_size=5,
            queue_timeout_seconds=30,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "file-upload": LanePolicy(
            name="file-upload",
            max_workers=MAX_CONCURRENT_UPLOADS,
            max_queue_size=MAX_CONCURRENT_UPLOADS,
            queue_timeout_seconds=30,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "office-conversion": LanePolicy(
            name="office-conversion",
            max_workers=MAX_CONCURRENT_CONVERSIONS,
            max_queue_size=MAX_CONCURRENT_CONVERSIONS,
            queue_timeout_seconds=30,
            cancel_grace_seconds=2,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "control-io": LanePolicy(
            name="control-io",
            max_workers=16,
            max_queue_size=32,
            queue_timeout_seconds=0,
            cancel_grace_seconds=2,
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
        "evaluation": LanePolicy(
            name="evaluation",
            max_workers=6,
            max_queue_size=12,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "model-tool-io": LanePolicy(
            name="model-tool-io",
            max_workers=6,
            max_queue_size=16,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
    },
)
