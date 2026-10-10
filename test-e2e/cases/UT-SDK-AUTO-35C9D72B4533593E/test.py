"""SDK unit test for the observer WARNING process type, ANSI stripping, and ParseTransformer."""

import json

import pytest

from nexent.core.utils.observer import (
    DefaultTransformer,
    Message,
    MessageObserver,
    ParseTransformer,
    ProcessType,
)

pytestmark = [
    pytest.mark.case_id("UT-SDK-AUTO-35C9D72B4533593E"),
    pytest.mark.stage("D1"),
]


def test_warning_process_type_and_observer_contract():
    assert ProcessType.WARNING.value == "warning"
    assert ProcessType.ERROR.value == "error"

    observer = MessageObserver()
    assert ProcessType.WARNING in observer.transformers
    assert isinstance(observer.transformers[ProcessType.WARNING], DefaultTransformer)
    assert isinstance(observer.transformers[ProcessType.ERROR], DefaultTransformer)

    observer.add_message("", ProcessType.WARNING, "step failed")
    messages = observer.get_cached_message()
    assert len(messages) == 1
    warning = json.loads(messages[0])
    assert warning["type"] == "warning"
    assert warning["content"] == "step failed"

    esc = chr(0x1B)
    bel = chr(0x07)
    ansi_content = f"{esc}[31m红字{esc}[0m plain {esc}]8;;http://x{bel}"
    observer.add_message("", ProcessType.WARNING, ansi_content)
    stripped = json.loads(observer.get_cached_message()[0])
    assert esc not in stripped["content"]
    assert "红字" in stripped["content"]
    assert "http://x" not in stripped["content"]

    recoverable = [
        "step failed: division by zero",
        "Agent execution interrupted by external stop signal",
        "Failed to upload output file report.pdf: boom",
    ]
    for content in recoverable:
        observer.add_message("", ProcessType.WARNING, content)
    for raw in observer.get_cached_message():
        assert json.loads(raw)["type"] == "warning"

    parse_input = "<code>1+1</code>"
    assert ParseTransformer().transform(content=parse_input) == parse_input

    observer.add_message(
        agent_name="agent",
        process_type=ProcessType.ERROR,
        content="Error in interaction: boom",
    )
    fatal = json.loads(observer.get_cached_message()[0])
    assert fatal["type"] == "error"
    assert fatal["content"] == "Error in interaction: boom"

    unit = json.loads(Message(ProcessType.WARNING, "plain").to_json())
    assert unit["type"] == "warning"
    assert unit["content"] == "plain"
