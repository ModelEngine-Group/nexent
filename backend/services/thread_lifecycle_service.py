from nexent.core.concurrency import LanePolicy, ThreadManager

from consts.const import (
    NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE,
    NORTHBOUND_CONTROL_THREAD_MAX_WORKERS,
    NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS,
    RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
    RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
    RUNTIME_AGENT_THREAD_MAX_WORKERS,
    RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS,
    RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
    RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
)


runtime_thread_manager = ThreadManager(
    service_name="runtime",
    lane_policies={
        "agent-run": LanePolicy(
            name="agent-run",
            max_workers=RUNTIME_AGENT_THREAD_MAX_WORKERS,
            max_queue_size=RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
            queue_timeout_seconds=RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
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
        "model-tool-io": LanePolicy(
            name="model-tool-io",
            max_workers=max(4, RUNTIME_AGENT_THREAD_MAX_WORKERS),
            max_queue_size=RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "mcp-session": LanePolicy(
            name="mcp-session",
            max_workers=RUNTIME_AGENT_THREAD_MAX_WORKERS,
            max_queue_size=0,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "sandbox": LanePolicy(
            name="sandbox",
            max_workers=200,
            max_queue_size=8,
            queue_timeout_seconds=0,
            cancel_grace_seconds=5,
            shutdown_grace_seconds=RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
        ),
        "background-service": LanePolicy(
            name="background-service",
            max_workers=12,
            max_queue_size=8,
            queue_timeout_seconds=0,
            cancel_grace_seconds=RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
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
    },
)


config_thread_manager = ThreadManager(
    service_name="config",
    lane_policies={
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


northbound_thread_manager = ThreadManager(
    service_name="northbound",
    lane_policies={
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
