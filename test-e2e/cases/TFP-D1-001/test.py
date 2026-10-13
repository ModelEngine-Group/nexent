"""TFP-D1-001: preserved fast-path acceptance checks."""

from __future__ import annotations

import json

import pytest
from shared.tool_fastpath import make_wrapper
from shared.tool_fastpath_aidp import aidp_runtime as aidp_runtime

from nexent.core.agents.tool_fastpath import (
    DeferredToolExecutor,
)
from nexent.core.utils.observer import MessageObserver, ProcessType


pytestmark = [pytest.mark.case_id("TFP-D1-001"), pytest.mark.stage("D1")]

def test_tfp_d1_001(monkeypatch):
    """TFP-D1-001: assignment, logs and saved final answer without acquisition."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    from nexent.core.agents.core_agent import _wrap_tool_for_observer
    from nexent.core.agents.nexent_agent import _wrap_tool_with_monitoring

    observer = MessageObserver()
    events = []
    monkeypatch.setattr(observer, "add_message", lambda *args, **kwargs: events.append((args, kwargs)))
    tool = wrapper._tools["read_skill_config"]
    assert _wrap_tool_with_monitoring(tool, "fixture") is tool
    _wrap_tool_for_observer(tool, observer, "fixture")
    assert wrapper._nexent_backend == "local"
    first = wrapper('result = read_skill_config(skill_name="demo")\nprint(result)')
    assert '"answer"' in first.logs
    assert not first.is_final_answer
    last = wrapper("final_answer(result)")
    assert last.is_final_answer
    assert last.output == wrapper.local.state["result"]
    assert calls == ["demo"]
    assert len(events) == 1
    assert events[0][1]["tool_name"] == tool.name
    assert acquisitions == []
    assert ordinary.calls == []
    wrapper.cleanup()
    wrapper.cleanup()
    assert releases == []

@pytest.mark.parametrize("allowed", [["kb-allowed"], []])
def test_tfp_d1_001_aidp(aidp_runtime, allowed):
    """TFP-D1-001: real AIDP filtering, results and events avoid all Docker acquisition."""
    agent = aidp_runtime.create()
    tool = agent.tools["aidp_search"]
    tool.set_allowed_kds(allowed)
    executor = agent.python_executor
    assert isinstance(executor, DeferredToolExecutor)
    output = executor('result = aidp_search(query="rules", kds_list=["Allowed", "Denied"])\nprint(result)')
    if allowed:
        assert "fixture-answer" in output.logs
        assert [request["kds_list"] for request in aidp_runtime.requests] == [["kb-allowed"]]
    else:
        assert "search was not executed" in output.logs
        assert aidp_runtime.requests == []
    assert "no read permission" in output.logs
    agent.model.answer = executor.local.state["result"]
    answer = agent.run("fixture", max_steps=1)
    assert agent.memory.steps[-1].is_final_answer is True
    assert str(answer) == executor.local.state["result"]
    assert "final_answer" not in agent.tools
    tool_events = [
        event for event in aidp_runtime.events
        if event[0][1] == ProcessType.TOOL and event[1].get("tool_name") == "aidp_search"
    ]
    assert len(tool_events) == 1
    assert tool_events[0][1]["tool_arguments"]["query"] == "rules"
    aidp_runtime.runtime._cleanup_sandbox()
    assert aidp_runtime.acquisitions == []
    assert aidp_runtime.releases == []

@pytest.mark.parametrize("source", [
    'import json\nresult = json.loads(raw)\nprint(json.dumps(result, ensure_ascii=False))',
    'import json as j\nresult = j.loads(raw)\nprint(j.dumps(result, ensure_ascii=False))',
    'from json import loads, dumps\nresult = loads(raw)\nprint(dumps(result, ensure_ascii=False))',
    'from json import loads as parse, dumps as encode\nresult = parse(raw)\nprint(encode(result, ensure_ascii=False))',
    'import json\nresult = json.loads(json.dumps({"value": "规则"}))\nprint(result)',
])
def test_tfp_d1_001_json(monkeypatch, source):
    """TFP-D1-001: real JSON imports, aliases and nested calls never acquire Docker."""
    wrapper, ordinary, calls, acquisitions, releases = make_wrapper(monkeypatch)
    wrapper.send_variables({"raw": '{"value": "规则"}'})
    output = wrapper(source)
    assert "规则" in output.logs
    assert wrapper.local.state["result"] == {"value": "规则"}
    answer = wrapper('final_answer(result)')
    assert answer.is_final_answer
    assert answer.output == {"value": "规则"}
    assert acquisitions == ordinary.calls == calls == []
    wrapper.cleanup()
    assert releases == []

def test_tfp_d1_001_json_tool_results(monkeypatch):
    """TFP-D1-001: parsing a real official tool result preserves local tool execution."""
    wrapper, ordinary, calls, acquisitions, _ = make_wrapper(monkeypatch)
    wrapper('import json as j\nraw = read_skill_config(skill_name="demo")\nresult = j.loads(raw)')
    output = wrapper('final_answer(j.dumps(result, ensure_ascii=False))')
    assert output.is_final_answer
    assert json.loads(output.output) == {"value": "answer"}
    assert calls == ["demo"]
    assert acquisitions == ordinary.calls == []
    wrapper.cleanup()
