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

pytestmark=[pytest.mark.case_id("JIUWEN-CONTEXT-D3-001"),pytest.mark.stage("D3")]

@pytest.mark.parametrize("original",["smolagents","jiuwen"])
@pytest.mark.parametrize("protocol",["native","text"])
@pytest.mark.parametrize("cm,existing_checkpoint",[(False,False),(True,False),(False,True),(True,True)])
def test_saved_core_context_continuation(monkeypatch,original,protocol,cm,existing_checkpoint):
    with context_database(monkeypatch) as engine:
        result=asyncio.run(run_context_scenario(monkeypatch,engine,original,protocol,cm,existing_checkpoint=existing_checkpoint))
    assert result["effects"]==["once"]
    assert result["infos"][0].agent_config.agent_core==original
    assert result["infos"][1].agent_config.agent_core!=(original)
    assert result["infos"][1].agent_config.version_no==2
    assert result["before"] and result["after"]
    followups=[body for phase,body in result["calls"] if phase!="seed"]
    assert len(followups)==2
    assert "UNTRUSTED_CLIENT_HISTORY" not in str(result["calls"])
    assert str(followups[0]).count("CURRENT_FOLLOWUP_ONLY")==1
    assert str(followups[1]).count("RELOADED_CURRENT_ONLY")==1
    for body in followups:
        assert "OLD_FACT_ALPHA" in str(body)
        assert "s3://files/old.txt" in str(body)
        assert "TOOL_RESULT_ALPHA" in str(body)
    if cm:
        assert result["summaries"] and result["checkpoints"]
        source=str(result["summaries"][0])
        assert "s3://files/old.txt" in source and "TOOL_RESULT_ALPHA" in source
        assert all(not body.get("tools") for body in result["summaries"])
        assert all(body.get("max_tokens",0)>0 for body in result["summaries"])
    else:
        assert not result["summaries"]
        assert len(result["checkpoints"]) == int(existing_checkpoint)
