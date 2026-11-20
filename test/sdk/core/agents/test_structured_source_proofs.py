# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SC-002..009: exact structured proof and typed owner-bound original recall."""

import json

import pytest
from nexent.core.agents.context import ContextItem, ContextItemInput
from nexent.core.agents.context.action_history import register_authorized_sources
from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.context.history_compression import _protected_fact_literals
from nexent.core.agents.context.structured_sources import StructuredSourceIndex


OWNER = "private-source-owner"


def page_text():
    # Preserve exact decimal digits without constructing a binary float.
    return (
        '{"page":1,"rows":['
        + ",".join(
            '{"id":"ledger-row-%05d","amount":123456789.01234567890123456789,"flag":true,"text":"%s"}'
            % (i, "Original 数值 " * 30)
            for i in range(40)
        )
        + "]}"
    )


def register_user(history, text, message=10, owner=OWNER):
    history.restore_sources(
        owner,
        [
            {
                "message_id": message,
                "unit_index": None,
                "source_kind": "user_message",
                "text": text,
                "parts": (text,),
            }
        ],
    )


def checkpoint(*sources):
    return ContextItem.from_input(
        ContextItemInput(
            id="checkpoint",
            type="history_summary",
            content={
                "summary": "accepted old facts",
                "covered_through_message_id": 42,
                "execution_sources": list(sources),
            },
        )
    )


def test_sc001_user_bulk_has_exact_source_proof_and_unicode_middle_page():
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    index = StructuredSourceIndex(history, OWNER)
    projected = index.project_text("Critical task directive stays outside.\n" + text)
    assert "Critical task directive stays outside." in projected
    assert "ledger-row-00039" not in projected and "trusted_bulk_source" in projected
    descriptor = json.loads(projected.split("\n", 1)[1])["rows"]["trusted_bulk_source"]
    assert (
        descriptor["source_kind"] == "user_message"
        and descriptor["source_ref"] == "message:10/user-message"
    )
    assert descriptor["row_count"] == 40 and descriptor["json_path"] == "/rows"
    offset = text.index("123456789.01234567890123456789", len(text) // 2)
    assert (
        json.loads(history.read(OWNER, "message:10/user-message", offset, 50))["text"]
        == text[offset : offset + 50]
    )
    with pytest.raises(PermissionError):
        history.read("foreign", "message:10/user-message")


@pytest.mark.parametrize(
    "change", ["amount", "precision", "row_order", "missing", "extra"]
)
def test_sc003_no_partial_value_type_field_or_order_equivalence(change):
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    if change == "amount":
        changed = text.replace("123456789.01234567890123456789", "true", 1)
    elif change == "precision":
        changed = text.replace(
            "123456789.01234567890123456789", "123456789.01234567890123456788", 1
        )
    elif change == "field_order":
        changed = text.replace(
            '"id":"ledger-row-00000","amount":123456789.01234567890123456789',
            '"amount":123456789.01234567890123456789,"id":"ledger-row-00000"',
            1,
        )
    elif change == "row_order":
        changed = (
            text.replace("ledger-row-00000", "TEMP")
            .replace("ledger-row-00001", "ledger-row-00000")
            .replace("TEMP", "ledger-row-00001")
        )
    elif change == "missing":
        changed = text.replace('"flag":true,', "", 1)
    else:
        changed = text.replace('"flag":true,', '"flag":true,"extra":false,', 1)
    assert StructuredSourceIndex(history, OWNER).project_text(changed) == changed


@pytest.mark.parametrize("case", ["duplicate", "partial", "nan"])
def test_sc003_invalid_structural_regions_fail_closed(case):
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    if case == "duplicate":
        changed = text[:-1] + ',"page":2}'
    elif case == "partial":
        changed = text[:-1]
    elif case == "deep":
        changed = "[" * 30 + text + "]" * 30
    elif case == "nan":
        changed = text.replace("123456789.01234567890123456789", "NaN", 1)
    else:
        changed = "{} " * 130 + text
    assert StructuredSourceIndex(history, OWNER).project_text(changed) == changed


def test_sc002_any_identifier_outside_a_covered_region_remains_protected():
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    projected = StructuredSourceIndex(history, OWNER).project_text(
        "Explicit fact ledger-row-00017=Keep-123.\n" + text
    )
    protected = _protected_fact_literals(projected)
    assert protected["ledger-row-00017"] == ("Keep-123",)
    assert "ledger-row-00018" not in protected


def test_sc003_source_proof_cannot_claim_unreadable_parts():
    history = ExecutionHistory()
    with pytest.raises(ValueError, match="readable original"):
        history.restore_sources(
            OWNER,
            [
                {
                    "message_id": 10,
                    "unit_index": None,
                    "source_kind": "user_message",
                    "text": "different readable text",
                    "parts": (page_text(),),
                }
            ],
        )
    assert not history.authorized_sources(OWNER)


@pytest.mark.parametrize("bad", ["stale", "invalid_id", "fake_unit", "unsupported"])
def test_sc006_source_batch_failure_publishes_nothing(bad):
    history = ExecutionHistory()
    text = page_text()
    good = {
        "message_id": 20,
        "unit_index": None,
        "source_kind": "user_message",
        "text": text,
        "parts": (text,),
    }
    invalid = {**good, "message_id": 30}
    if bad == "stale":
        register_user(history, "earlier committed source", 30)
    elif bad == "invalid_id":
        invalid["message_id"] = True
    elif bad == "fake_unit":
        invalid["unit_index"] = 0
    else:
        invalid["source_kind"] = "arbitrary_message_rpc"
    with pytest.raises((ValueError, PermissionError)):
        history.restore_sources(OWNER, [good, invalid])
    with pytest.raises(PermissionError):
        history.read(OWNER, "message:20/user-message")
    if bad == "stale":
        assert "earlier committed source" in history.read(
            OWNER, "message:30/user-message"
        )


def test_sc006_user_checkpoint_restores_same_original_in_new_owner_and_rejects_foreign():
    text = page_text()
    source = {
        "record_type": "user_message",
        "message_id": 10,
        "unit_index": None,
        "content": text,
    }
    store = ExecutionHistory()
    items = register_authorized_sources([checkpoint(source)], store, OWNER)
    assert (
        items[0].metadata["structured_source_proofs"][0]["source_kind"]
        == "user_message"
    )
    new = ExecutionHistory()
    register_authorized_sources([checkpoint(source)], new, "new-owner")
    offset = text.index("ledger-row-00020")
    assert (
        json.loads(new.read("new-owner", "message:10/user-message", offset, 50))["text"]
        == text[offset : offset + 50]
    )
    with pytest.raises(PermissionError):
        new.read(OWNER, "message:10/user-message")


def test_sc008_model_supplied_proofs_do_not_register_sources():
    item = checkpoint()
    item = item.model_copy(
        update={
            "metadata": {
                "execution_source_refs": ["message:999/user-message"],
                "structured_source_proofs": [
                    {
                        "source_kind": "user_message",
                        "source_ref": "message:999/user-message",
                    }
                ],
            }
        }
    )
    store = ExecutionHistory()
    result = register_authorized_sources([item], store, OWNER)
    assert not result[0].metadata
    with pytest.raises(PermissionError):
        store.read(OWNER, "message:999/user-message")


def test_sc003_object_key_order_and_equivalent_decimal_notation_are_legal():
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    reordered = text.replace(
        '"id":"ledger-row-00000","amount":123456789.01234567890123456789',
        '"amount":123456789.012345678901234567890,"id":"ledger-row-00000"',
        1,
    )
    projected = StructuredSourceIndex(history, OWNER).project_text(reordered)
    assert "trusted_bulk_source" in projected and "ledger-row-00039" not in projected


def test_sc003_more_than_128_json_roots_can_still_project_valid_data():
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    projected = StructuredSourceIndex(history, OWNER).project_text("{} " * 140 + text)
    assert projected.startswith("{} " * 140) and "trusted_bulk_source" in projected


def test_sc003_single_large_row_and_small_critical_arrays_use_actual_gain():
    text = json.dumps(
        {
            "rows": [{"id": "one-row-001", "payload": "x" * 9000}],
            "critical": ["service", "tax"],
        }
    )
    history = ExecutionHistory()
    register_user(history, text)
    projected = json.loads(StructuredSourceIndex(history, OWNER).project_text(text))
    assert projected["rows"]["trusted_bulk_source"]["row_count"] == 1
    assert projected["critical"] == ["service", "tax"]


def test_sc003_no_new_depth_limit_for_ordinary_nested_json():
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    nested = "[" * 40 + text + "]" * 40
    projected = StructuredSourceIndex(history, OWNER).project_text(nested)
    assert "trusted_bulk_source" in projected


def test_sc003_parser_resource_failure_keeps_input_and_authority_unchanged():
    text = page_text()
    history = ExecutionHistory()
    register_user(history, text)
    unsupported = "[" * 2000 + text + "]" * 2000
    assert (
        StructuredSourceIndex(history, OWNER).project_text(unsupported) == unsupported
    )


def test_sc001_canonical_executor_repr_only_decodes_string_tokens(capsys):
    from nexent.core.agents.context.action_history import decode_execution_fields
    from nexent.core.agents.context.execution_history import result_text

    text = page_text()
    value = (
        "{'payload': "
        + repr(text)
        + ", 'unsafe': __import__('builtins').print('must-never-execute')}"
    )
    fields = {"RETURN_VALUE": value}
    payload = json.dumps({"content": result_text(fields)})
    store = ExecutionHistory()
    register_authorized_sources(
        [
            checkpoint(
                {
                    "record_type": "execution_result",
                    "message_id": 42,
                    "unit_index": 1,
                    "content": payload,
                }
            )
        ],
        store,
        OWNER,
    )
    turn = {
        "user_message": "Original directive remains.",
        "assistant_final_answer": "Earlier execution.",
        "execution_records": [{"record_type": "execution_result", "content": payload}],
    }
    projected = store.structured_source_index(OWNER).project_turn(turn)
    projected_fields = decode_execution_fields(
        json.loads(projected["execution_records"][0]["content"])
    )
    assert "trusted_bulk_source" in projected_fields["RETURN_VALUE"]
    assert "ledger-row-00039" not in projected_fields["RETURN_VALUE"]
    assert (
        "__import__('builtins').print('must-never-execute')"
        in projected_fields["RETURN_VALUE"]
    )
    assert turn["execution_records"][0]["content"] == payload
    assert not capsys.readouterr().out
    original = result_text(fields)
    offset = original.index("ledger-row-00020")
    assert (
        json.loads(store.read(OWNER, "message:42/unit-index:1", offset, 100))["text"]
        == original[offset : offset + 100]
    )


def test_sc006_checkpoint_proof_revalidates_complete_original_before_atomic_publication():
    text = page_text()
    store = ExecutionHistory()
    register_user(store, text)
    proof = next(iter(store.structured_source_index(OWNER).collections.values()))
    source = {
        "record_type": "user_message",
        "message_id": 10,
        "unit_index": None,
        "content": text,
    }
    item = checkpoint(source).model_copy(
        update={
            "content": {
                **checkpoint(source).content,
                "structured_source_proofs": [proof],
            }
        }
    )
    next_store = ExecutionHistory()
    restored = register_authorized_sources([item], next_store, "new-owner")
    assert restored[0].metadata["structured_source_proofs"] == [proof]
    offset = text.index("ledger-row-00020")
    assert (
        json.loads(next_store.read("new-owner", "message:10/user-message", offset, 50))[
            "text"
        ]
        == text[offset : offset + 50]
    )
    changed = {
        **source,
        "content": text.replace(
            "123456789.01234567890123456789", "123456789.01234567890123456788", 1
        ),
    }
    fresh = ExecutionHistory()
    stale_item = checkpoint(changed).model_copy(
        update={
            "content": {
                **checkpoint(changed).content,
                "structured_source_proofs": [proof],
            }
        }
    )
    with pytest.raises(PermissionError, match="Stale"):
        register_authorized_sources([stale_item], fresh, "new-owner")
    assert not fresh.authorized_sources("new-owner")


@pytest.mark.parametrize(
    "field,value",
    [
        ("row_count", True),
        ("json_path", "/wrong"),
        ("source_kind", "tool_result"),
        ("sha256", "0" * 64),
    ],
)
def test_sc006_forged_checkpoint_descriptor_cannot_publish_sources(field, value):
    text = page_text()
    old = ExecutionHistory()
    register_user(old, text)
    proof = {
        **next(iter(old.structured_source_index(OWNER).collections.values())),
        field: value,
    }
    source = {
        "record_type": "user_message",
        "message_id": 10,
        "unit_index": None,
        "content": text,
    }
    item = checkpoint(source).model_copy(
        update={
            "content": {
                **checkpoint(source).content,
                "structured_source_proofs": [proof],
            }
        }
    )
    fresh = ExecutionHistory()
    with pytest.raises(PermissionError):
        register_authorized_sources([item], fresh, "new-owner")
    assert not fresh.authorized_sources("new-owner")
