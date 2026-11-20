# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import Mock

import pytest
from runtime.sandbox_coordination import SandboxRunBusy, SandboxRunCoordinator
from runtime.sandbox_journal import SandboxRunJournal

from nexent.core.agents.sandbox_contracts import SandboxOwner


@pytest.fixture
def lifetime(tmp_path):
    client = Mock()
    client.eval.return_value = 1
    coordinator = SandboxRunCoordinator(client, SandboxRunJournal(tmp_path),
        SandboxOwner('release', 'namespace', 'runtime', 'uid', '10.0.0.1', 'epoch'))
    lease = coordinator.reserve('tenant', 'user', 7, 'a' * 32)
    coordinator.activate(lease)
    return coordinator, lease, coordinator.lifecycle(lease.run_id)


@pytest.mark.parametrize('kind', ['invocation', 'callback', 'kernel', 'process'])
def test_root_future_completion_does_not_release_live_business_descendants(lifetime, kind):
    coordinator, lease, lifecycle = lifetime
    holder = lifecycle.begin(kind)
    assert not coordinator.finish(lease)
    with pytest.raises(SandboxRunBusy):
        coordinator.reserve('tenant', 'user', 7, 'b' * 32)
    assert lifecycle.finish(holder)
    assert coordinator.journal.read_run(lease.run_id).phase == 'TERMINAL'


def test_uncertain_remote_execution_retains_only_its_conversation(lifetime):
    coordinator, lease, lifecycle = lifetime
    holder = lifecycle.begin('kernel')
    lifecycle.unknown(holder)
    assert not coordinator.finish(lease)
    assert coordinator.journal.read_run(lease.run_id).phase == 'UNKNOWN'
    with pytest.raises(SandboxRunBusy):
        coordinator.reserve('tenant', 'user', 7, 'b' * 32)
    assert coordinator.reserve('tenant', 'user', 8, 'c' * 32).run_id == 'c' * 32
    assert not coordinator.lost_coordination.is_set()
