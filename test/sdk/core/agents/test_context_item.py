"""Tests for the single fine-grained context item boundary."""

import pytest
from pydantic import ValidationError

from nexent.core.agents.context import (
    ContextItem,
    ContextItemInput,
    ContextItemRenderer,
    ContextItemRenderingError,
    ContextItemType,
)
from nexent.core.agents.context.models import normalize_context_inputs


def test_context_input_serializes_and_normalizes_without_source_object():
    value = ContextItemInput(
        id="system:duty",
        type=ContextItemType.SYSTEM_PROMPT,
        content={"text": "Follow the instructions."},
        source=("agent:duty",),
        priority=100,
        required=True,
    )

    dumped = value.model_dump(mode="json")
    item = ContextItem.from_input(value)

    assert dumped["type"] == "system_prompt"
    assert item.content == {"text": "Follow the instructions."}
    assert item.token_estimate > 0
    assert "_source_component" not in item.metadata


def test_context_input_rejects_empty_id_unknown_type_and_nonserializable_payload():
    with pytest.raises(ValidationError):
        ContextItemInput(id="", type="system_prompt", content={"text": "x"})
    with pytest.raises(ValidationError):
        ContextItemInput(id="x", type="unknown", content={"text": "x"})
    with pytest.raises(ValidationError, match="JSON serializable"):
        ContextItemInput(id="x", type="system_prompt", content=object())
    with pytest.raises(ValidationError, match="_source_component fallback is not permitted"):
        ContextItemInput(
            id="x", type="system_prompt", content={"text": "x"}, metadata={"_source_component": "x"}
        )


@pytest.mark.parametrize(
    ("item_type", "content", "message"),
    [
        ("system_prompt", {}, "system_prompt content requires text"),
        ("tool", {"description": "missing name"}, "tool content missing fields: name"),
        ("skill", {}, "skill content missing fields: name"),
        ("memory", {}, "memory content requires memory or content"),
        ("managed_agent", {}, "managed_agent content missing fields: name"),
        ("external_agent", {"name": "x"}, "external_agent content missing fields: agent_id"),
        ("knowledge_base", {}, "knowledge_base content requires text"),
        ("history", {"role": "system", "text": "x"}, "history content requires user or assistant role"),
    ],
)
def test_context_input_rejects_type_specific_invalid_payload(item_type, content, message):
    with pytest.raises(ValidationError, match=message):
        ContextItemInput(id="invalid", type=item_type, content=content)


def test_normalization_rejects_duplicate_ids():
    values = [
        ContextItemInput(id="same", type="system_prompt", content={"text": "one"}),
        ContextItemInput(id="same", type="system_prompt", content={"text": "two"}),
    ]

    with pytest.raises(ValueError, match="duplicate context item id: same"):
        normalize_context_inputs(values)


def test_normalization_copies_mutable_payload_from_public_input():
    value = ContextItemInput(
        id="system:copy",
        type="system_prompt",
        content={"text": "original", "nested": {"value": "original"}},
    )
    item = ContextItem.from_input(value)

    value.content["nested"]["value"] = "mutated"

    assert item.content["nested"]["value"] == "original"


def test_normalization_rejects_empty_required_item_but_allows_empty_optional_item():
    required = ContextItemInput(
        id="required", type="system_prompt", content={"text": ""}, required=True
    )
    optional = ContextItemInput(
        id="optional", type="system_prompt", content={"text": ""}, required=False
    )

    with pytest.raises(ValueError, match="required context item is empty: required"):
        normalize_context_inputs([required])
    assert normalize_context_inputs([optional])[0].id == "optional"


def test_renderer_outputs_only_selected_items_and_preserves_empty_as_no_message():
    items = normalize_context_inputs([
        ContextItemInput(id="one", type="system_prompt", content={"text": "selected"}),
        ContextItemInput(id="empty", type="system_prompt", content={"text": ""}),
        ContextItemInput(id="three", type="system_prompt", content={"text": "not selected"}),
    ])

    messages = ContextItemRenderer().render(items[:2])

    assert messages == [{"role": "system", "content": [{"type": "text", "text": "selected"}]}]
    assert "not selected" not in str(messages)


def test_renderer_uses_reduced_item_content_without_full_source_fallback():
    full = ContextItem.from_input(ContextItemInput(
        id="memory:one",
        type="history",
        content={"role": "user", "text": "full secret source"},
    ))
    reduced = full.model_copy(update={"content": {"text": "safe summary"}})

    messages = ContextItemRenderer().render([reduced])

    assert "safe summary" in str(messages)
    assert "full secret source" not in str(messages)


def test_renderer_wraps_handler_failure_and_rejects_invalid_payload():
    tool = ContextItem.from_input(ContextItemInput(id="tool:x", type="tool", content={"name": "x"}))
    renderer = ContextItemRenderer({ContextItemType.TOOL: lambda item: 1 / 0})

    with pytest.raises(ContextItemRenderingError, match="handler failed for item tool:x"):
        renderer.render([tool])
    invalid = ContextItem.from_input(ContextItemInput(
        id="system:x", type="system_prompt", content={"text": "valid"}
    )).model_copy(update={"content": {"unexpected": "x"}})
    with pytest.raises(ContextItemRenderingError, match="invalid system_prompt payload"):
        ContextItemRenderer().render([invalid])


def test_renderer_rejects_mixed_or_inconsistent_render_groups():
    tool = ContextItem.from_input(ContextItemInput(
        id="tool:x",
        type="tool",
        content={"name": "x"},
        metadata={"render_group": "shared", "language": "zh"},
    ))
    skill = ContextItem.from_input(ContextItemInput(
        id="skill:x",
        type="skill",
        content={"name": "x"},
        metadata={"render_group": "shared", "language": "zh"},
    ))
    with pytest.raises(ContextItemRenderingError, match="mixes context item types"):
        ContextItemRenderer().render([tool, skill])

    english_tool = ContextItem.from_input(ContextItemInput(
        id="tool:y",
        type="tool",
        content={"name": "y"},
        metadata={"render_group": "shared", "language": "en"},
    ))
    with pytest.raises(ContextItemRenderingError, match="inconsistent rendering metadata"):
        ContextItemRenderer().render([tool, english_tool])
