from dataclasses import dataclass
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
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.formatting import (
    _format_agent_fallback,
    _format_external_agents_description,
    _format_managed_agents_description,
    _format_memory_context,
    _format_skills_description,
    _format_tools_description,
)
from nexent.core.agents.context.rendering import ContextItemRenderer, ContextItemRenderingError
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
    assert runtime.chars_per_token == pytest.approx(1.5)
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


def test_formatting_empty_and_tool_variants():
    assert _format_memory_context([]) == ""
    assert _format_skills_description([]) == ""
    assert _format_managed_agents_description({}) == ""
    assert _format_external_agents_description({}) == ""
    assert _format_agent_fallback({"worker": {}}, {}) == ""
    assert "No tools are currently available" in _format_tools_description({}, language="en")

    tool = SimpleNamespace(
        description="remote search",
        inputs={"query": "string"},
        output_type="string",
        source="mcp",
    )
    zh_description = _format_tools_description({"search": tool}, language="zh", is_manager=False)
    en_description = _format_tools_description({"search": tool}, language="en", is_manager=False)
    assert "[MCP] search" in zh_description
    assert "presigned_url" in zh_description
    assert "Accepts input" in en_description
    assert "presigned_url" in en_description


def _direct_item(item_id, item_type, content, metadata=None):
    return ContextItem(
        id=item_id,
        type=item_type,
        content=content,
        metadata=metadata or {},
    )


def test_renderer_text_templates_and_payload_guards():
    renderer = ContextItemRenderer()
    skills_usage = _direct_item(
        "skills",
        ContextItemType.SYSTEM,
        {"template": "skills_usage", "skills": [], "language": "en", "is_manager": False},
    )
    fallback = _direct_item(
        "fallback",
        ContextItemType.SYSTEM,
        {"template": "agent_fallback", "language": "en"},
    )
    assert "No skills" in renderer.render([skills_usage])[0]["content"][0]["text"]
    assert "No agents" in renderer.render([fallback])[0]["content"][0]["text"]

    invalid_items = [
        _direct_item("unknown", ContextItemType.SYSTEM, {"template": "unknown"}),
        _direct_item("payload", ContextItemType.SYSTEM, {"text": "x", "extra": True}),
        _direct_item("missing", ContextItemType.SYSTEM, {"text": None}),
        _direct_item("role", ContextItemType.SYSTEM, {"text": "x", "role": "invalid"}),
    ]
    for item in invalid_items:
        with pytest.raises(ContextItemRenderingError):
            renderer.render([item])

    empty = _direct_item("empty", ContextItemType.SYSTEM, {"text": ""})
    assert renderer.render([empty]) == []


def test_renderer_handler_and_group_error_boundaries():
    renderer = ContextItemRenderer()
    ungrouped_tool = _direct_item("tool", ContextItemType.TOOL, {"name": "tool"})
    with pytest.raises(ContextItemRenderingError, match="no handler"):
        renderer.render([ungrouped_tool])

    renderer.register(ContextItemType.TOOL, lambda _item: 1 / 0)
    with pytest.raises(ContextItemRenderingError, match="handler failed"):
        renderer.render([ungrouped_tool])

    bad_group = _direct_item(
        "bad-group",
        ContextItemType.TOOL,
        {"name": "tool"},
        {"render_group": 3},
    )
    with pytest.raises(ContextItemRenderingError, match="invalid render group"):
        ContextItemRenderer().render([bad_group])

    tool = _direct_item(
        "group-tool",
        ContextItemType.TOOL,
        {"name": "tool"},
        {"render_group": "resources"},
    )
    skill = _direct_item(
        "group-skill",
        ContextItemType.SKILL,
        {"name": "skill"},
        {"render_group": "resources"},
    )
    with pytest.raises(ContextItemRenderingError, match="mixes context item types"):
        ContextItemRenderer().render([tool, skill])

    second_tool = _direct_item(
        "group-tool-2",
        ContextItemType.TOOL,
        {"name": "tool-2"},
        {"render_group": "resources", "language": "en"},
    )
    with pytest.raises(ContextItemRenderingError, match="inconsistent rendering metadata"):
        ContextItemRenderer().render([tool, second_tool])

    unsupported = _direct_item(
        "group-system",
        ContextItemType.SYSTEM,
        {"text": "system"},
        {"render_group": "system"},
    )
    with pytest.raises(ContextItemRenderingError, match="unsupported render group"):
        ContextItemRenderer().render([unsupported])

    broken_tool = _direct_item(
        "broken-tool",
        ContextItemType.TOOL,
        {},
        {"render_group": "tools"},
    )
    with pytest.raises(ContextItemRenderingError, match="handler failed for item group"):
        ContextItemRenderer().render([broken_tool])


def test_renderer_current_action_without_raw_messages():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {"step_number": 1, "result": "done"},
    )
    message = ContextItemRenderer().render([action])[0]
    assert message["role"] == "assistant"
    assert '"result": "done"' in message["content"][0]["text"]


def test_context_manager_management_and_diagnostic_helpers():
    manager = ContextManager(ContextManagerConfig(token_threshold=100, chars_per_token=2.0))
    item_input = ContextItemInput(id="system", type="system", content={"text": "policy"})
    normalized = ContextItem.from_input(item_input)

    assert manager.hard_input_budget_tokens == 110
    assert manager.processing_mode == "passthrough"
    assert manager.get_step_compression_stats() == {"calls": 0, "records": []}
    assert manager.get_all_compression_stats() == {"calls": 0, "records": []}
    assert manager.get_token_counts() == {"uncompressed": None, "compressed": None}
    assert manager.export_summary() == {"history_candidate": None}

    manager.register_item(item_input)
    assert manager.get_registered_items()[0].id == "system"
    with pytest.raises(ValueError, match="duplicate context item id"):
        manager.register_item(item_input)
    assert manager.build_system_prompt()[0]["role"] == "system"

    manager.replace_items([])
    assert manager.get_registered_items() == []
    manager.replace_items([item_input])
    assert manager.get_registered_items()[0].id == "system"
    manager.clear_items()
    assert manager.get_registered_items() == []

    with pytest.raises(TypeError, match="cannot mix"):
        manager._item_source([normalized, item_input])
    with pytest.raises(ValueError, match="requires final_answer_templates"):
        manager._purpose_messages(purpose="final_answer", task="task", final_answer_templates=None)


@dataclass
class _Payload:
    value: int


class _Dumpable:
    def model_dump(self, mode=None):
        return {"mode": mode, "value": 2}


def test_context_manager_runtime_value_normalization_helpers():
    manager = ContextManager(ContextManagerConfig(token_threshold=100))
    assert manager._normalize({2: (_Dumpable(),)}) == {
        "2": [{"mode": None, "value": 2}]
    }
    assert manager._normalize(SimpleNamespace(name="worker")) == {"name": "worker"}
    assert manager._canonical_tools([{"z": 1}, {"a": 1}]) == [{"a": 1}, {"z": 1}]

    message = SimpleNamespace(role=_Role.USER, content={"payload": _Payload(1)})
    assert manager._message_to_dict(message) == {
        "role": "user",
        "content": {"payload": {"value": 1}},
    }
    assert manager._message_to_dict({"role": "user", "content": {_Role.USER}}) == {
        "role": "user",
        "content": ["user"],
    }
    assert manager._to_json_value(_Dumpable()) == {"mode": "json", "value": 2}
    assert manager._to_json_value(SimpleNamespace(name="value")) == "namespace(name='value')"


def test_context_manager_memory_rendering_and_change_reasons():
    manager = ContextManager(ContextManagerConfig(token_threshold=100))
    system_prompt = SimpleNamespace(to_messages=lambda: [{"role": "system", "content": "policy"}])
    step = SimpleNamespace(to_messages=lambda: [{"role": "user", "content": "task"}])
    assert manager.render_memory_messages(SimpleNamespace(system_prompt=system_prompt, steps=[step])) == [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "task"},
    ]

    assert manager._change_reasons("first", {"tools": "a", "purpose": "step", "system": "one"}) == [
        "initial_request"
    ]
    manager._previous_stable_fingerprint = "first"
    assert manager._change_reasons("first", manager._previous_stable_items) == []
    assert manager._change_reasons(
        "second",
        {"tools": "b", "purpose": "final", "system": "two"},
    ) == ["tool_schema_version", "context_purpose", "system_prompt_version"]
    manager._previous_stable_fingerprint = "second"
    assert manager._change_reasons("third", manager._previous_stable_items) == [
        "unexpected_nondeterminism"
    ]
