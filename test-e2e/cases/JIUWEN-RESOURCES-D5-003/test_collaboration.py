import asyncio
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'sdk'), str(ROOT/'backend'), str(ROOT/'test-e2e/infra/automation')]
from jiuwen_collaboration_runtime import run_collaboration
from jiuwen_bridge_runtime import stop_infrastructure

@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    stop_infrastructure()

import time
pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D5-003"), pytest.mark.stage("D5")]

@pytest.mark.parametrize("child,fault,protocol", [
    ("jiuwen", "cancel", "native"), ("jiuwen", "cancel", "text"),
    ("a2a", "cancel", "native"), ("a2a", "cancel", "text"),
    ("jiuwen", "capacity", "text"),
    ("a2a", "timeout", "native"), ("a2a", "timeout", "text"),
])
def test_nested_stop_and_recovery(monkeypatch, child, fault, protocol):
    start = time.monotonic()
    with monkeypatch.context() as patch:
        info, state, output, cores = asyncio.run(run_collaboration(patch, child_core=child, protocol=protocol, fault=fault))
    assert time.monotonic() - start < 10
    if fault != "capacity":
        assert state["closed"]
    assert state["effects"] == [] and state["parent_effects"] == []
    assert len(state["child"] if child == "jiuwen" else state["remote"]) == 1
    assert sum(event.get("type") == "subagent_start" for event in output) == 1
    assert sum(event.get("type") == "subagent_end" for event in output) == 1
    if fault in {"cancel", "capacity"}:
        assert info.attempt_outcome == "stopped"
        assert len(state["parent"]) == 1
    else:
        assert "Error:" in str(output)
    with monkeypatch.context() as patch:
        recovered, state, output, cores = asyncio.run(run_collaboration(patch, child_core=child, protocol=protocol))
    assert recovered.attempt_outcome == "completed" and "CHILD_DONE" in str(output)
    assert len(state["child"] if child == "jiuwen" else state["remote"]) == (2 if child == "jiuwen" else 1)
