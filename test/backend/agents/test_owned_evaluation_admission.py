# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from runtime.sandbox_evaluation import dispatch_owned_evaluation

from nexent.core.concurrency import LanePolicy, ThreadManager


@asynccontextmanager
async def admitted():
    manager = ThreadManager(service_name='evaluation-ut', lane_policies={
        name: LanePolicy(name=name, max_workers=2, max_queue_size=0, queue_timeout_seconds=0)
        for name in ('evaluation', 'control-io')})
    manager.start()
    try:
        yield manager
    finally:
        await manager.shutdown(timeout=2)


@pytest.mark.asyncio
async def test_evaluation_capacity_precedes_db_claim_and_exact_identity_precedes_mutation():
    coordinator, claim, restore, executor = Mock(), Mock(return_value='stamp'), Mock(), Mock()
    order = []
    coordinator.associate.side_effect = lambda *args, **kwargs: order.append('associate')
    claim.side_effect = lambda *args: order.append('claim') or 'stamp'
    async with admitted() as manager:
        assert await dispatch_owned_evaluation('tenant', 'user', 19, 5, executor, manager=manager,
            coordinator=coordinator, claim=claim, restore=restore, admission=lambda: None)
        for _ in range(100):
            if executor.called:
                break
            await asyncio.sleep(0.01)
    assert order == ['associate', 'claim']
    executor.assert_called_once_with('tenant', 'user', 19, 5)
    restore.assert_not_called()
    assert coordinator.reserve.call_args.kwargs['kind'] == 'EVALUATION'
    assert any(call.kwargs == {'holder': 'dispatch'} for call in coordinator.finish.call_args_list)


@pytest.mark.asyncio
async def test_coordination_loss_after_claim_restores_only_exact_unstarted_claim():
    coordinator, claim, restore, executor = Mock(), Mock(return_value='stamp'), Mock(), Mock()
    checks = 0
    def admission():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError('coordination lost')
    async with admitted() as manager:
        with pytest.raises(RuntimeError, match='coordination lost'):
            await dispatch_owned_evaluation('tenant', 'user', 19, 5, executor, manager=manager,
                coordinator=coordinator, claim=claim, restore=restore, admission=admission)
    restore.assert_called_once_with(19, 'tenant', 'user', 'stamp')
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_uncertain_db_claim_keeps_dispatch_holder_for_scoped_recovery():
    coordinator, restore, executor = Mock(), Mock(), Mock()
    claim = Mock(side_effect=OSError('response lost'))
    async with admitted() as manager:
        with pytest.raises(OSError):
            await dispatch_owned_evaluation('tenant', 'user', 19, 5, executor, manager=manager,
                coordinator=coordinator, claim=claim, restore=restore, admission=lambda: None)
    coordinator.signal_lost.assert_called()
    assert not any(call.kwargs == {'holder': 'dispatch'} for call in coordinator.finish.call_args_list)
    executor.assert_not_called()
    restore.assert_not_called()
