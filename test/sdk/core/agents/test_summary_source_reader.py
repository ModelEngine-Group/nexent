# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Summary discovery shares existing reader authority, limits and CoreAgent registration."""

import json
from copy import deepcopy

import pytest
from smolagents.agents import EMPTY_PROMPT_TEMPLATES
from smolagents.models import Model

from nexent.core.agents.context import ContextManager
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.utils.observer import MessageObserver


def store(mocker, *, discovery=True):
    callback = mocker.Mock(return_value={"results": [{"output_ref": "message:2/unit-index:5"}],
                                      "next_offset": 1, "eof": True})
    history = ExecutionHistory(read_conversation_result=lambda *args: "ORIGINAL",
        discover_summary_sources=callback if discovery else None)
    history.authorize_persisted_reads("owner")
    return history, callback


def test_core_registers_discovery_and_original_reads_on_the_same_host_tool(mocker):
    history, callback = store(mocker)
    observer = MessageObserver()
    observer.execution_history = history
    agent = CoreAgent(observer=observer, model=Model(model_id="unit"), tools=[],
        prompt_templates=deepcopy(EMPTY_PROMPT_TEMPLATES),
        context_runtime=ManagedContextRuntime(ContextManager()), max_steps=1, verbosity_level=0)
    reader = agent.tools["read_execution_output"]
    page = json.loads(reader.forward("summary"))
    assert page["results"][0]["output_ref"] == "message:2/unit-index:5"
    assert json.loads(reader.forward(page["results"][0]["output_ref"]))["text"] == "ORIGINAL"
    assert callback.call_count == 1 and agent._execution_loaded


@pytest.mark.parametrize("offset,max_chars", [(-1, 4000), (True, 4000), (0, 0), (0, 16001), (0, True)])
def test_discovery_reuses_existing_range_validation(mocker, offset, max_chars):
    history, callback = store(mocker)
    with pytest.raises(ValueError):
        history.read("owner", "summary", offset, max_chars)
    callback.assert_not_called()


def test_discovery_cannot_bypass_owner_or_existing_action_limits(mocker):
    history, callback = store(mocker)
    with pytest.raises(PermissionError):
        history.read("foreign", "summary")
    history._read_chars["owner"] = 16000
    with pytest.raises(ValueError, match="budget exhausted"):
        history.read("owner", "summary")
    callback.assert_not_called()
    history.reset_read_budget("owner", max_rendered_chars=1)
    with pytest.raises(ValueError, match="context budget"):
        history.read("owner", "summary")
    assert history._read_chars["owner"] == 0


def test_no_loaded_checkpoint_disables_discovery_without_changing_direct_read(mocker):
    history, callback = store(mocker, discovery=False)
    with pytest.raises(PermissionError):
        history.read("owner", "summary")
    assert json.loads(history.read("owner", "message:2/unit-index:5"))["text"] == "ORIGINAL"
    callback.assert_not_called()


def test_failed_or_oversized_discovery_does_not_consume_read_allowance(mocker):
    history, callback = store(mocker)
    callback.side_effect = PermissionError("checkpoint deleted")
    with pytest.raises(PermissionError):
        history.read("owner", "summary")
    assert history._read_chars.get("owner", 0) == 0
    callback.side_effect = None
    callback.return_value = {"results": ["x" * 5000]}
    with pytest.raises(ValueError, match="page size"):
        history.read("owner", "summary")
    assert history._read_chars.get("owner", 0) == 0
