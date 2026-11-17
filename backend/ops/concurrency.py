# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Create a bounded worker manager owned only by the operations process."""


def create_thread_manager():
    # Keep the disabled operations bootstrap independent of the Agent SDK.
    from contracts.constants.environment import RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
    from nexent.core.concurrency import LanePolicy, ThreadManager

    def lane(name, workers, queued, queue_timeout=2):
        return LanePolicy(
            name=name,
            max_workers=workers,
            max_queue_size=queued,
            queue_timeout_seconds=queue_timeout,
            cancel_grace_seconds=2,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        )

    return ThreadManager(
        service_name="ops",
        lane_policies={
            "trajectory-read": lane("trajectory-read", 4, 8),
            "trajectory-cleanup": lane("trajectory-cleanup", 1, 0, 0),
            "control-io": lane("control-io", 2, 4),
            "background-service": lane("background-service", 3, 0, 0),
        },
    )
