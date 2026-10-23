from __future__ import annotations

import pytest

from nexent.core.concurrency.errors import InvalidThreadPolicy, ThreadManagerError
from nexent.core.concurrency.models import (
    LanePolicy,
    ManagedTaskSpec,
    ManagedThreadSpec,
)


@pytest.mark.case_id('UT-SDK-AUTO-BCD444C05F3FCB6E')
@pytest.mark.stage('D1')
def test_concurrency_specs_reject_invalid_inputs() -> None:
    assert issubclass(InvalidThreadPolicy, ThreadManagerError)
    assert issubclass(InvalidThreadPolicy, ValueError)

    policy = LanePolicy(name='lane-a', max_workers=2, max_queue_size=4)
    assert policy.name == 'lane-a'
    assert policy.max_workers == 2
    assert policy.max_queue_size == 4

    invalid_policy_factories = [
        lambda: LanePolicy(name='', max_workers=2, max_queue_size=4),
        lambda: LanePolicy(name='lane-a', max_workers=0, max_queue_size=4),
        lambda: LanePolicy(name='lane-a', max_workers=-1, max_queue_size=4),
        lambda: LanePolicy(name='lane-a', max_workers=2, max_queue_size=-1),
        lambda: LanePolicy(
            name='lane-a', max_workers=2, max_queue_size=4, queue_timeout_seconds=-0.5
        ),
        lambda: LanePolicy(
            name='lane-a', max_workers=2, max_queue_size=4, cancel_grace_seconds=-1
        ),
        lambda: LanePolicy(
            name='lane-a', max_workers=2, max_queue_size=4, shutdown_grace_seconds=0
        ),
        lambda: LanePolicy(
            name='lane-a', max_workers=2, max_queue_size=4, shutdown_grace_seconds=-1
        ),
    ]
    for factory in invalid_policy_factories:
        with pytest.raises(InvalidThreadPolicy):
            factory()

    task = ManagedTaskSpec(task_name='task', owner='owner')
    assert task.task_name == 'task'
    assert task.owner == 'owner'

    for kwargs in (
        {'task_name': '', 'owner': 'owner'},
        {'task_name': 'task', 'owner': ''},
    ):
        with pytest.raises(ValueError):
            ManagedTaskSpec(**kwargs)

    thread = ManagedThreadSpec(task_name='svc', owner='owner', lane='background-service')
    assert thread.task_name == 'svc'
    assert thread.owner == 'owner'
    assert thread.lane == 'background-service'

    for kwargs in (
        {'task_name': '', 'owner': 'owner', 'lane': 'background-service'},
        {'task_name': 'svc', 'owner': '', 'lane': 'background-service'},
        {'task_name': 'svc', 'owner': 'owner', 'lane': ''},
    ):
        with pytest.raises(ValueError):
            ManagedThreadSpec(**kwargs)
