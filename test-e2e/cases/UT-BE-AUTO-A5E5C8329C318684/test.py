'''BE-UT F-131 thread_lifecycle_service lane policies and cross-lane isolation.

Case UT-BE-AUTO-A5E5C8329C318684 (D1).
'''

import asyncio
import threading
import time

import pytest

from consts.const import (
    NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE,
    NORTHBOUND_CONTROL_THREAD_MAX_WORKERS,
    NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS,
    RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS,
    RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE,
    RUNTIME_AGENT_THREAD_MAX_WORKERS,
    RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS,
    RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS,
)
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    ManagerState,
    ThreadManager,
)
from services.thread_lifecycle_service import (
    config_thread_manager,
    mcp_thread_manager,
    northbound_thread_manager,
    runtime_thread_manager,
)

CASE_ID = 'UT-BE-AUTO-A5E5C8329C318684'

RUNTIME_LANES = {
    'agent-run',
    'control-io',
    'model-tool-io',
    'mcp-session',
    'sandbox',
    'background-service',
    'evaluation',
}
CONFIG_LANES = {'control-io', 'background-service', 'evaluation', 'model-tool-io'}
NORTHBOUND_LANES = {'control-io', 'background-service'}
MCP_LANES = {'control-io', 'background-service'}


def _assert_policy(policy, lane_name, max_workers, max_queue_size,
                   queue_timeout_seconds, cancel_grace_seconds,
                   shutdown_grace_seconds):
    assert isinstance(policy, LanePolicy)
    assert policy.name == lane_name
    assert policy.max_workers == max_workers
    assert policy.max_queue_size == max_queue_size
    assert policy.queue_timeout_seconds == queue_timeout_seconds
    assert policy.cancel_grace_seconds == cancel_grace_seconds
    assert policy.shutdown_grace_seconds == shutdown_grace_seconds


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D1')
async def test_thread_lifecycle_configured_policies_and_isolation():
    managers = [
        runtime_thread_manager,
        config_thread_manager,
        northbound_thread_manager,
        mcp_thread_manager,
    ]
    assert all(isinstance(m, ThreadManager) for m in managers)

    assert len({id(m) for m in managers}) == 4
    assert [m.service_name for m in managers] == [
        'runtime',
        'config',
        'northbound',
        'api-to-mcp',
    ]

    rt = runtime_thread_manager
    assert set(rt._policies.keys()) == RUNTIME_LANES
    for lane, policy in rt._policies.items():
        assert policy.name == lane

    _assert_policy(rt._policies['control-io'], 'control-io', 16, 32, 0, 2, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(rt._policies['sandbox'], 'sandbox', 200, 8, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(rt._policies['evaluation'], 'evaluation', 6, 12, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)

    agent_run = rt._policies['agent-run']
    assert agent_run.max_workers == RUNTIME_AGENT_THREAD_MAX_WORKERS
    assert agent_run.max_queue_size == RUNTIME_AGENT_THREAD_MAX_QUEUE_SIZE
    assert agent_run.queue_timeout_seconds == RUNTIME_AGENT_THREAD_QUEUE_TIMEOUT_SECONDS
    assert agent_run.cancel_grace_seconds == RUNTIME_AGENT_THREAD_CANCEL_GRACE_SECONDS

    assert rt._policies['model-tool-io'].max_workers == max(4, RUNTIME_AGENT_THREAD_MAX_WORKERS)

    for lane in ('control-io', 'model-tool-io', 'mcp-session', 'sandbox',
                 'background-service', 'evaluation'):
        assert rt._policies[lane].shutdown_grace_seconds == RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS

    cfg = config_thread_manager
    assert set(cfg._policies.keys()) == CONFIG_LANES
    for lane, policy in cfg._policies.items():
        assert policy.name == lane
    _assert_policy(cfg._policies['control-io'], 'control-io', 16, 32, 0, 2, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(cfg._policies['background-service'], 'background-service', 12, 8, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(cfg._policies['evaluation'], 'evaluation', 6, 12, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(cfg._policies['model-tool-io'], 'model-tool-io', 6, 16, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    for lane in CONFIG_LANES:
        assert cfg._policies[lane].shutdown_grace_seconds == RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS

    nb = northbound_thread_manager
    assert set(nb._policies.keys()) == NORTHBOUND_LANES
    for lane, policy in nb._policies.items():
        assert policy.name == lane
    _assert_policy(nb._policies['control-io'], 'control-io',
                   NORTHBOUND_CONTROL_THREAD_MAX_WORKERS,
                   NORTHBOUND_CONTROL_THREAD_MAX_QUEUE_SIZE,
                   0, 2, NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(nb._policies['background-service'], 'background-service',
                   12, 8, 0, 2, NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS)

    mcp = mcp_thread_manager
    assert set(mcp._policies.keys()) == MCP_LANES
    for lane, policy in mcp._policies.items():
        assert policy.name == lane
    _assert_policy(mcp._policies['control-io'], 'control-io', 8, 16, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)
    _assert_policy(mcp._policies['background-service'], 'background-service', 12, 8, 0, 5, RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS)

    for i, left in enumerate(managers):
        for right in managers[i + 1:]:
            assert left._policies is not right._policies
    for left in managers:
        for right in managers:
            if left is right:
                continue
            assert left._policies['control-io'] is not right._policies['control-io']
    assert rt._policies['control-io'].shutdown_grace_seconds == RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
    assert cfg._policies['control-io'].shutdown_grace_seconds == RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
    assert mcp._policies['control-io'].shutdown_grace_seconds == RUNTIME_THREAD_SHUTDOWN_GRACE_SECONDS
    assert nb._policies['control-io'].shutdown_grace_seconds == NORTHBOUND_THREAD_SHUTDOWN_GRACE_SECONDS

    started_here = False
    if runtime_thread_manager.state is ManagerState.CREATED:
        runtime_thread_manager.start()
        started_here = True

    entered = threading.Event()
    release = threading.Event()

    def blocking_fn():
        entered.set()
        release.wait(timeout=30)
        return 'control-done'

    control_task = asyncio.ensure_future(
        runtime_thread_manager.run(
            'control-io',
            ManagedTaskSpec(task_name='isolation-blocker', owner='ut-be-auto'),
            blocking_fn,
        )
    )
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 30), timeout=30)
        assert entered.is_set()
        begun = time.monotonic()
        probe = await asyncio.wait_for(
            runtime_thread_manager.run(
                'evaluation',
                ManagedTaskSpec(task_name='isolation-probe', owner='ut-be-auto'),
                lambda: 'bg-done',
            ),
            timeout=30,
        )
        assert probe == 'bg-done'
        assert time.monotonic() - begun < 30
    finally:
        release.set()
        control_result = await asyncio.wait_for(control_task, timeout=30)
        assert control_result == 'control-done'
        if started_here:
            await runtime_thread_manager.shutdown(timeout=30)
