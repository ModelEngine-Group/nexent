import asyncio
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'sdk'),str(ROOT/'backend'),str(ROOT/'test-e2e/infra/automation')]
from jiuwen_context_runtime import context_database,run_context_scenario
from jiuwen_bridge_runtime import stop_infrastructure

@pytest.fixture(scope="module",autouse=True)
def cleanup():
    yield
    stop_infrastructure()

pytestmark=[pytest.mark.case_id("JIUWEN-CONTEXT-D5-001"),pytest.mark.stage("D5")]

@pytest.mark.parametrize("protocol",["native","text"])
@pytest.mark.parametrize("fault",["invalid_summary","cancel_summary"])
def test_context_failure_preserves_history(monkeypatch,protocol,fault):
    with context_database(monkeypatch) as engine:
        result=asyncio.run(run_context_scenario(monkeypatch,engine,"smolagents",protocol,True,fault))
    assert result["effects"]==["once"]
    assert len(result["checkpoints_before_recovery"]) == 1
    assert result["checkpoints"][0] == result["checkpoints_before_recovery"][0]
    assert "OLD_FACT_ALPHA" in result["checkpoints"][0]
    assert result["summaries"]
    if fault=="cancel_summary":
        assert result["infos"][1].attempt_outcome=="stopped"
        assert result["phase"]["closed"]
        assert result["phase"]["cancel_elapsed"] < 10
        assert not [body for phase,body in result["calls"] if phase=="followup"]
    else:
        assert result["infos"][1].attempt_outcome=="completed"
    assert result["infos"][-1].attempt_outcome=="completed"
    assert len([body for phase,body in result["calls"] if phase=="reload"])==1
