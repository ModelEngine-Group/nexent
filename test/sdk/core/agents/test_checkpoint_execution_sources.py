# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Approved private checkpoint sources preserve bounded owner-scoped recall."""

import json

import pytest
from nexent.core.agents.context.action_history import register_authorized_sources
from nexent.core.agents.context.execution_history import ExecutionHistory, result_text
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.agents.context.rendering import _render_summary
from nexent.core.tools.read_execution_output_tool import ReadExecutionOutputTool


def checkpoint(*sources):
    return ContextItem.from_input(
        ContextItemInput(
            id="checkpoint",
            type="history_summary",
            content={
                "summary": "Accepted old facts",
                "covered_through_message_id": 42,
                "execution_sources": list(sources),
            },
            metadata={"execution_source_refs": ["message:999/unit-index:0"]},
        )
    )


def source(message=42, index=5, text=None):
    fields = {
        "STDOUT": text
        if text is not None
        else "prefix " * 1000 + "真实中段" + " suffix" * 1000
    }
    return {
        "message_id": message,
        "unit_index": index,
        "content": json.dumps({"content": result_text(fields)}),
    }


@pytest.mark.parametrize("owner", ["smol-new-run", "jiuwen-new-run"])
def test_b010_checkpoint_registers_original_but_renders_only_trusted_reference(owner):
    store = ExecutionHistory()
    original = checkpoint(source())
    authorized = register_authorized_sources([original], store, owner)
    wire = str(_render_summary(authorized[0]))
    assert "Accepted old facts" in wire and "message:42/unit-index:5" in wire
    assert (
        "message:999" not in wire and "真实中段" not in wire and "prefix " not in wire
    )
    reader = ReadExecutionOutputTool(store, owner, lambda: None)
    full = json.loads(source()["content"])["content"]
    middle = full.index("真实中段")
    result = json.loads(reader.forward("message:42/unit-index:5", middle, 4))
    assert result == {"text": "真实中段", "next_offset": middle + 4, "eof": False}
    with pytest.raises(PermissionError):
        store.read("foreign", "message:42/unit-index:5")
    with pytest.raises(ValueError):
        reader.forward("../other-conversation")
    with pytest.raises(PermissionError):
        reader.forward("message:999/unit-index:0")
    # Re-register only via the same trusted private snapshot for another run.
    new_items = register_authorized_sources([original], store, owner + "-next")
    assert (
        json.loads(store.read(owner + "-next", "message:42/unit-index:5", middle, 4))[
            "text"
        ]
        == "真实中段"
    )
    assert new_items[0].metadata == authorized[0].metadata


@pytest.mark.parametrize(
    "failure", ["conflict", "stale", "invalid_id", "invalid_content"]
)
def test_b011_invalid_source_batch_never_half_registers(failure):
    store = ExecutionHistory()
    good = source(50)
    bad = source(60)
    if failure == "conflict":
        inputs = [good, source(50, text="conflict")]
    elif failure == "stale":
        register_authorized_sources(
            [checkpoint(source(60, text="existing"))], store, "owner"
        )
        inputs = [good, bad]
    elif failure == "invalid_id":
        inputs = [good, source(True)]
    else:
        bad["content"] = json.dumps({"content": "<STDOUT>unclosed"})
        inputs = [good, bad]
    with pytest.raises((ValueError, PermissionError)):
        register_authorized_sources([checkpoint(*inputs)], store, "owner")
    with pytest.raises(PermissionError):
        store.read("owner", "message:50/unit-index:5")
    if failure == "stale":
        assert "existing" in store.read("owner", "message:60/unit-index:5")


def test_b011_duplicate_same_source_is_idempotent_and_budget_remains_bounded():
    store = ExecutionHistory()
    register_authorized_sources([checkpoint(source(), source())], store, "owner")
    reader = ReadExecutionOutputTool(store, "owner", lambda: None)
    for _ in range(4):
        reader.forward("message:42/unit-index:5", 0, 4000)
    with pytest.raises(ValueError, match="budget exhausted"):
        reader.forward("message:42/unit-index:5")
