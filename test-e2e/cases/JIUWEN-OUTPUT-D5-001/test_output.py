# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'sdk'),str(ROOT/'backend'),str(ROOT/'test-e2e/infra/automation')]
from jiuwen_output_runtime import context_database,persist_output
from jiuwen_resource_runtime import resource_provider,run_resources
from jiuwen_collaboration_runtime import run_collaboration
from jiuwen_bridge_runtime import run_worker,stop_infrastructure

@pytest.fixture(scope="module",autouse=True)
def cleanup():
    yield
    stop_infrastructure()


pytestmark=[pytest.mark.case_id("JIUWEN-OUTPUT-D5-001"),pytest.mark.stage("D5")]

@pytest.mark.parametrize("fault",["missing","duplicate","broken_stream","cancel"])
def test_output_failure_preserves_facts(monkeypatch,tmp_path,fault):
    from openjiuwen.core.runner import Runner
    original=Runner.run_agent_streaming
    if fault in {"missing","duplicate"}:
        async def corrupt(*args,**kwargs):
            async for chunk in original(*args,**kwargs):
                if getattr(chunk,"type",None)=="answer":
                    if fault=="missing":continue
                    yield chunk
                yield chunk
        monkeypatch.setattr(Runner,"run_agent_streaming",corrupt)
    with context_database(monkeypatch):
        info,state,output=asyncio.run(run_worker(monkeypatch,"text" if fault=="broken_stream" else "native",
            "broken_stream" if fault=="broken_stream" else "cancel" if fault=="cancel" else "normal"))
        expected="stopped" if fault=="cancel" else "failed"
        assert info.attempt_outcome==expected
        terminal=[e for e in output if e["type"]=="run_terminal"]
        assert len(terminal)==1 and terminal[0]["status"]==expected
        assert not terminal[0]["final_content"] and not terminal[0]["final_block_ids"]
        if fault in {"broken_stream","cancel"}:assert any(e["type"]=="model_output" and e["content"] for e in output)
        assistant,saved,wire=asyncio.run(persist_output(monkeypatch,info,output))
        public = [json.loads(line[5:]) for frame in wire for line in frame.splitlines() if line.startswith("data:")]
        assert not any(e.get("type") in {"model_output", "tool_result", "step_observation", "run_terminal", "final_answer"} for e in public)
        if expected == "failed":
            assert any(e.get("type") == "error" for e in public)
        assert assistant["status"]==expected and not assistant["message_content"]
        assert any(e["type"]=="run_terminal" and e["status"]==expected for e in saved)
    monkeypatch.setattr(Runner,"run_agent_streaming",original)
    recovered,state,_=asyncio.run(run_worker(monkeypatch,"native","normal"))
    assert recovered.attempt_outcome=="completed"
    assert state["tool_calls"]==[(2,3)]
