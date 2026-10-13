"""SAI-D1-001: case-local preserved component regression."""
import threading
from types import SimpleNamespace

import pytest
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.tools.parallel_executor import _parallel_executor
from shared.sai_component import (
    ORIGINAL_SANDBOX_CLEANUP as ORIGINAL_SANDBOX_CLEANUP,
)
from shared.sai_component import (
    manager as manager,
)
from shared.sai_component import (
    setup_factory as setup_factory,
)


def test_SAI_D1_001_parallel_instances(setup_factory, monkeypatch, manager):
    factory, child, instances, cleaned, _ = setup_factory
    assert len(instances) == 1
    barrier = threading.Barrier(2)
    monkeypatch.setattr(NexentAgent, 'create_model', lambda self, name: SimpleNamespace(barrier=barrier))
    starts, ends = [], []
    monkeypatch.setattr(factory.observer, 'add_subagent_start', lambda **kw: starts.append(kw))
    monkeypatch.setattr(factory.observer, 'add_subagent_end', lambda **kw: ends.append(kw))
    results = _parallel_executor([(child, {'task': 'LEFT'}, 'left'), (child, {'task': 'RIGHT'}, 'right')])
    assert [results[key]['task'] for key in ('left', 'right')] == ['LEFT', 'RIGHT']
    assert results['left']['agent'] is not results['right']['agent']
    assert results['left']['model'] is not results['right']['model']
    assert results['left']['agent'].state is not results['right']['agent'].state
    assert child.name == 'child'
    assert len(cleaned) == 2 and all(owner is not factory for owner in cleaned)
    assert len(starts) == len(ends) == 2
    assert {s['invocation_id'] for s in starts} == {e['invocation_id'] for e in ends}
    assert not factory._subagent_invocations


pytestmark = [pytest.mark.case_id("SAI-D1-001"), pytest.mark.stage("D1")]
