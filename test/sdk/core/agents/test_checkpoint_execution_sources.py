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


@pytest.mark.parametrize(
    "text",
    [
        "\x1b[31merror\x1b[0m",
        "\x00\x01\x1f",
        "progress\rupdate\r\n",
        "中文🙂\t&<literal>\n",
    ],
)
def test_canonical_execution_text_preserves_control_characters_and_newlines(text):
    from nexent.core.agents.context.action_history import decode_execution_fields

    fields = {
        "STDOUT": text,
        "OUTPUT": "",
        "RETURN_VALUE": "literal &#27;",
        "ERROR": "\x1b[31mfailed\x1b[0m",
    }
    original = result_text(fields)
    assert decode_execution_fields({"content": original}) == fields
    saved = source(text="placeholder")
    saved["content"] = json.dumps({"content": original})
    for owner in ["current", "next-checkpoint-owner"]:
        store = ExecutionHistory()
        register_authorized_sources([checkpoint(saved)], store, owner)
        assert (
            json.loads(store.read(owner, "message:42/unit-index:5"))["text"] == original
        )
        assert store.authorized_sources(owner)[0].parts == tuple(fields.values())
        with pytest.raises(PermissionError):
            store.read("foreign", "message:42/unit-index:5")


@pytest.mark.parametrize(
    "text",
    [
        "<STDOUT>ok</STDOUT><ERROR>bad</ERROR>",
        "<STDOUT>ok</STDOUT>\ntrailing",
        "<STDOUT>one</STDOUT>\n<STDOUT>two</STDOUT>",
        "<OTHER>unexpected</OTHER>",
        "<STDOUT attr='x'>ok</STDOUT>",
        "<!DOCTYPE fields [<!ENTITY x 'injected'>]><STDOUT>&x;</STDOUT>",
        "<STDOUT>unescaped <tag/></STDOUT>",
        "<STDOUT>&#27;</STDOUT>",
        "<STDOUT>&#0;</STDOUT>",
        "<STDOUT>&#x1b;</STDOUT>",
    ],
)
def test_canonical_decoder_rejects_noncanonical_or_injected_channel_markup(text):
    from nexent.core.agents.context.action_history import decode_execution_fields

    assert decode_execution_fields({"content": text}) is None
    bad = source(index=6)
    bad["content"] = json.dumps({"content": text})
    store = ExecutionHistory()
    with pytest.raises(PermissionError):
        register_authorized_sources([checkpoint(source(), bad)], store, "owner")
    assert not store.authorized_sources("owner")


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_array_sources_revalidate_saved_proof_independently_of_source_order(
    reverse,
):
    raw = json.dumps([{"id": i, "detail": "original value " * 20} for i in range(20)])
    store = ExecutionHistory()
    store.restore_sources(
        "old",
        [
            {
                "message_id": 1,
                "unit_index": None,
                "source_kind": "user_message",
                "text": raw,
                "parts": (raw,),
            }
        ],
    )
    proofs = list(store.structured_source_index("old").collections.values())
    fields = {"STDOUT": raw}
    sources = [
        {
            "record_type": "user_message",
            "message_id": i,
            "unit_index": None,
            "content": raw,
        }
        for i in [1, 2]
    ]
    sources += [
        {
            "record_type": "execution_result",
            "message_id": 3,
            "unit_index": 0,
            "content": json.dumps({"content": result_text(fields)}),
        }
    ]
    item = checkpoint(*(list(reversed(sources)) if reverse else sources))
    item.content["structured_source_proofs"] = proofs
    new = ExecutionHistory()
    register_authorized_sources([item], new, "new")
    assert len(new.authorized_sources("new")) == 3
    offset = len(raw) // 2
    assert (
        json.loads(new.read("new", proofs[0]["source_ref"], offset, 80))["text"]
        == raw[offset : offset + 80]
    )
