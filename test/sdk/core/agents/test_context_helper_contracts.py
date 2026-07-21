from enum import Enum
from types import SimpleNamespace

import pytest

from nexent.core.agents.context.budget import (
    _is_context_length_error,
    extract_message_text,
    format_summary_output,
    message_role,
)
from nexent.core.agents.context.config import ContextManagerConfig
from nexent.core.agents.context.models import (
    ContextItem,
    ContextItemInput,
    ContextItemType,
    SystemContextItem,
    normalize_context_inputs,
)
from nexent.core.agents.context.step_renderer import StepRenderer
from nexent.core.context_runtime.contracts import (
    ContextEvidence,
    FinalContext,
    UnconfiguredContextRuntime,
)


class _Role(Enum):
    USER = "user"


def test_summary_output_normalization_and_fallback(caplog):
    assert format_summary_output("   ") is None
    assert format_summary_output('```json\n{"fact": "保留"}\n```') == '{\n  "fact": "保留"\n}'

    assert format_summary_output("plain summary") == "plain summary"
    assert "not valid JSON" in caplog.text


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("maximum context length exceeded"), True),
        (RuntimeError("input is too long"), True),
        (RuntimeError("temporary connection failure"), False),
    ],
)
def test_context_length_error_detection(error, expected):
    assert _is_context_length_error(error) is expected


def test_message_role_and_text_extraction_support_runtime_shapes():
    assert message_role({"role": "assistant"}) == "assistant"
    assert message_role(SimpleNamespace(role=_Role.USER)) == "user"
    assert extract_message_text({"content": "plain"}) == "plain"
    assert extract_message_text(
        {"content": [{"type": "text", "text": "first"}, "ignored", {"text": " second"}]}
    ) == "first second"
    assert extract_message_text(SimpleNamespace(content=42)) == "42"
    assert extract_message_text(SimpleNamespace(content=None)) == ""


def test_step_renderer_estimates_and_truncates_all_limit_shapes():
    renderer = StepRenderer(ContextManagerConfig(chars_per_token=2.0))
    assert renderer.estimate_text_tokens("") == 0
    assert renderer.estimate_text_tokens("abcdef") == 3
    assert renderer.truncate_text_to_tokens("short", 3) == "short"
    assert renderer.truncate_text_to_tokens("abcdef", 1) == "ab"

    long_text = "a" * 100
    truncated = renderer.truncate_text_to_tokens(long_text, 20)
    assert truncated.startswith("aaa")
    assert "...[summary input truncated]..." in truncated
    assert truncated.endswith("aaa")


def test_context_contract_defaults_and_unconfigured_runtime_guards():
    evidence = ContextEvidence()
    final = FinalContext(messages=[{"role": "user", "content": "hello"}])
    runtime = UnconfiguredContextRuntime()

    assert evidence.processing_mode == "passthrough"
    assert final.tools == []
    assert final.evidence == evidence
    assert runtime.context_manager is None
    assert runtime.compression_stats() == {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_hits": 0,
        "cache_types": [],
    }
    assert runtime.consume_history_summary_event() is None
    assert runtime.chars_per_token == 1.5
    assert runtime.token_threshold is None

    guarded_calls = [
        lambda: runtime.replace_items([]),
        lambda: runtime.prepare_run(memory=object(), fallback_system_prompt="system"),
        lambda: runtime.prepare_step(model=object(), memory=object(), current_run_start_idx=0),
        lambda: runtime.prepare_final_answer(
            model=object(),
            memory=object(),
            current_run_start_idx=0,
            task="task",
            final_answer_templates={},
        ),
        lambda: runtime.render_summary_messages(memory=object()),
        lambda: runtime.finalize_evidence(status="completed"),
    ]
    for guarded_call in guarded_calls:
        with pytest.raises(RuntimeError, match="requires a context runtime"):
            guarded_call()


def test_context_item_validation_rejects_invalid_and_empty_payloads():
    with pytest.raises(ValueError, match="memory content requires"):
        ContextItemInput(id="memory", type="memory", content={})
    with pytest.raises(ValueError, match="system content requires text"):
        ContextItemInput(id="system", type="system", content={})
    with pytest.raises(ValueError, match="requires type system"):
        SystemContextItem(id="wrong", type=ContextItemType.MEMORY, content={"memory": "x"})

    empty_task = ContextItemInput(id="task", type="current_task", content={"text": ""})
    with pytest.raises(ValueError, match="required context item is empty"):
        normalize_context_inputs([empty_task])


def test_context_item_representation_guards_and_compact_cache():
    raw_item = ContextItem.from_input(
        ContextItemInput(id="system", type="system", content={"text": "policy"})
    )
    with pytest.raises(ValueError, match="does not support compact"):
        raw_item.compact()
    with pytest.raises(ValueError, match="unsupported representation"):
        raw_item.represent("missing")

    compactable = ContextItem.from_input(
        ContextItemInput(
            id="planning",
            type="current_planning",
            content={"text": "x" * 5000},
        )
    )
    first = compactable.represent("compact")
    second = compactable.represent("compact")
    assert first is second
    assert compactable.representation_cache_stats == (1, 1)
    assert "deterministically compacted" in first.content["text"]
