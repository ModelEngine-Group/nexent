from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

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
from nexent.core.agents.context.llm_summary import _strip_code_fences
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

    assert format_summary_output('```markdown\n# Summary\n\ntext\n```') == "# Summary\n\ntext"
    assert format_summary_output('```json\n{"fact": "保留"}\n```') == '{"fact": "保留"}'

    assert format_summary_output("plain summary") == "plain summary"


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
    assert runtime.context_window_tokens is None
    assert runtime.hard_input_budget_tokens is None
    assert runtime.processing_mode is None
    assert runtime.token_counts() == {"uncompressed": None, "compressed": None}
    assert runtime.global_compression_stats() == {"calls": 0, "records": []}

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


def test_memory_formatting_renders_agent_presearch_and_ignores_retired_levels():
    result_text = "Found 1 relevant memories:\n[1] Existing preference"

    rendered = _format_memory_context(
        [{"memory": result_text, "memory_level": "agent"}],
        language="en",
    )

    assert "**Agent Level Memory:**" in rendered
    assert result_text in rendered
    assert "user_agent" not in rendered
    assert _format_memory_context(
        [{"memory": "retired", "memory_level": "user_agent"}],
        language="en",
    ) == ""
    assert _format_memory_context(
        [{"memory": "unknown", "memory_level": "retrieved"}],
        language="en",
    ) == ""


def test_versioned_long_term_markdown_is_not_wrapped_as_scored_list_item():
    markdown = "## Preferences\n\n- concise\n- use English"
    rendered = _format_memory_context([{
        "memory": markdown, "memory_level": "user", "version_id": 9,
        "memory_type": "long_term", "source": "dreaming",
    }], language="en")
    assert markdown in rendered
    assert f"- {markdown}" not in rendered
    assert "`(0.00)`" not in rendered


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
    assert message["role"] == "user"
    text = message["content"][0]["text"]
    assert '<completed_action_history read_only="true">' in text
    assert "index: 1" in text
    assert "recorded_result:\ndone" in text
    assert "Step 1:" not in text
    assert not text.lstrip().startswith("{")


def test_renderer_current_action_preserves_raw_messages():
    messages = [{"role": "assistant", "content": [{"type": "text", "text": "raw action"}]}]
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {"messages": messages},
    )

    assert ContextItemRenderer().render([action]) == messages


def test_renderer_current_action_compact_with_tool_calls():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {
            "step_number": 3,
            "tool_calls": [{"name": "search", "arguments": {"q": "foo"}}],
            "observations": "found 5 results",
            "error": None,
            "result": "answer is 42",
        },
    )
    message = ContextItemRenderer().render([action])[0]
    text = message["content"][0]["text"]
    assert "index: 3" in text
    assert "tool: search" in text
    assert '"q": "foo"' in text
    assert "outcome:\nfound 5 results" in text
    assert "recorded_result:\nanswer is 42" in text
    assert "Called tool" not in text
    assert not text.lstrip().startswith("{")


def test_renderer_current_action_compact_with_single_tool_call_dict():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {
            "step_number": 2,
            "tool_calls": {"name": "execute", "arguments": {"code": "print(1)"}},
            "result": "1",
        },
    )
    message = ContextItemRenderer().render([action])[0]
    text = message["content"][0]["text"]
    assert "tool: execute" in text
    assert '"code": "print(1)"' in text


def test_renderer_current_action_preserves_string_tool_arguments():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {
            "step_number": 2,
            "tool_calls": [{
                "name": "python_interpreter",
                "arguments": "result = search(query='GAIA')\nprint(result)",
            }],
            "observations": "evidence",
        },
    )

    message = ContextItemRenderer().render([action])[0]
    text = message["content"][0]["text"]

    assert message["role"] == "user"
    assert "tool: python_interpreter" in text
    assert "result = search(query='GAIA')\nprint(result)" in text
    assert "python_interpreter'()" not in text


def test_renderer_current_action_without_step_number():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {
            "tool_calls": [{"name": "search", "arguments": {"q": "GAIA"}}],
            "result": "done",
        },
    )

    text = ContextItemRenderer().render([action])[0]["content"][0]["text"]

    assert "index:" not in text
    assert "tool: search" in text
    assert "recorded_result:\ndone" in text


def test_renderer_summary_legacy_dict_renders_markdown():
    summary = _direct_item(
        "summary",
        ContextItemType.HISTORY_SUMMARY,
        {
            "summary": {"task_overview": "did work", "completed_work": "finished"},
            "covered_through_message_id": 10,
        },
    )
    message = ContextItemRenderer().render([summary])[0]
    text = message["content"][0]["text"]
    assert "## Task Overview" in text
    assert "did work" in text
    assert "## Completed Work" in text


def test_strip_code_fences():
    assert _strip_code_fences("plain text") == "plain text"
    assert _strip_code_fences("```markdown\n# Title\n```") == "# Title"
    assert _strip_code_fences("```\ncontent\n```") == "content"
    assert _strip_code_fences("") is None
    assert _strip_code_fences("   ") is None


def test_renderer_summary_legacy_dict_list_values():
    summary = _direct_item(
        "summary",
        ContextItemType.HISTORY_SUMMARY,
        {
            "summary": {
                "key_decisions": ["decision A", "decision B"],
                "pending_items": [],
                "context_to_preserve": None,
                "custom_field": 42,
            },
            "covered_through_message_id": 10,
        },
    )
    message = ContextItemRenderer().render([summary])[0]
    text = message["content"][0]["text"]
    assert "- decision A" in text
    assert "- decision B" in text
    assert "42" in text


def test_renderer_summary_legacy_dict_all_empty_falls_back_to_json():
    summary = _direct_item(
        "summary",
        ContextItemType.HISTORY_SUMMARY,
        {
            "summary": {"task_overview": "", "completed_work": None},
            "covered_through_message_id": 10,
        },
    )
    message = ContextItemRenderer().render([summary])[0]
    text = message["content"][0]["text"]
    assert "task_overview" in text


def test_renderer_current_action_compact_non_standard_tool_calls():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {
            "step_number": 4,
            "tool_calls": "raw_tool_call_string",
            "result": "done",
        },
    )
    message = ContextItemRenderer().render([action])[0]
    text = message["content"][0]["text"]
    assert "tool_records:" in text


def test_renderer_current_action_compact_list_tool_call_non_dict():
    action = _direct_item(
        "action",
        ContextItemType.CURRENT_ACTION,
        {
            "step_number": 5,
            "tool_calls": ["not_a_dict_tool_call"],
            "result": "done",
        },
    )
    message = ContextItemRenderer().render([action])[0]
    text = message["content"][0]["text"]
    assert "tool_record:" in text


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


def test_ac_p2_005_rebuild_target_tightens_both_context_budgets():
    manager = ContextManager(
        ContextManagerConfig(
            token_threshold=100,
            soft_input_budget_tokens=80,
            hard_input_budget_tokens=100,
            chars_per_token=1.0,
        )
    )
    memory = MagicMock(system_prompt=None, steps=[])
    run_context = manager.prepare_run_context(
        memory,
        "",
        items=[
            ContextItemInput(
                id="system:large",
                type="system",
                content={"text": "x" * 60},
            )
        ],
    )

    rebuilt = manager.assemble_final_context(
        model=MagicMock(),
        memory=memory,
        current_run_start_idx=0,
        run_context=run_context,
        target_input_budget_tokens=40,
    )

    assert rebuilt.evidence.soft_budget == 40
    assert rebuilt.evidence.hard_budget == 40
    assert rebuilt.evidence.over_hard_budget is True
    assert rebuilt.evidence.budget_failure_reason == "single_context_item_oversize"


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
