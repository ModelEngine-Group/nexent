"""Tests for authorized backend ContextItemInput snapshot construction."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from nexent.core.agents.context import (
    ContextItemInput,
    ContextItemRenderer,
    ContextItemType,
)
from nexent.core.agents.context.models import normalize_context_inputs
from nexent.core.agents.prompt import AgentPromptComposer

from backend.management.services.agent.prompt_template_loader import (
    load_agent_prompt_bundle,
)
from backend.utils.context_utils import (
    build_authorized_context_input,
)
from backend.utils.context_utils import (
    build_context_inputs as _runtime_build_context_inputs,
)


@dataclass
class Value:
    description: str = "description"
    inputs: dict | None = None
    output_type: str = "string"
    source: str = "local"
    name: str = "value"
    tools: tuple = ()
    agent_id: str = "external-id"
    url: str = "https://example.invalid"


def build_context_inputs(**kwargs):
    """Call the Backend adapter with an explicit run-scoped prompt bundle."""
    language = kwargs.get("language", "zh")
    is_manager = kwargs.get("is_manager", True)
    kwargs.setdefault(
        "prompt_bundle",
        load_agent_prompt_bundle(is_manager=is_manager, language=language),
    )
    return _runtime_build_context_inputs(**kwargs)


def _messages(**kwargs):
    return ContextItemRenderer().render(normalize_context_inputs(build_context_inputs(**kwargs)))


@pytest.mark.parametrize("language", ["zh", "en"])
def test_runtime_system_context_does_not_guide_observation_markers(language):
    rendered = str(_messages(language=language))

    assert "Observation" not in rendered
    assert "Observe Results" not in rendered
    assert "观察结果" not in rendered


def test_authorized_context_snapshot_merges_config_summary_and_turns_in_order():
    configured_item = ContextItemInput(
        id="system:duty",
        type="system",
        content={"text": "Answer weather questions."},
        source=("agent_config",),
    )
    run_info = SimpleNamespace(
        history=[],
        agent_config=SimpleNamespace(context_items=[configured_item]),
    )
    summary = {
        "unit_id": 42,
        "summary": "The user is planning a trip.",
        "covered_through_message_id": 9,
    }
    turn = {
        "user_message": "Will it rain?",
        "assistant_final_answer": "I will check.",
        "attachments": [],
        "user_message_id": 10,
        "assistant_message_id": 11,
    }

    context_input = build_authorized_context_input(
        run_info,
        historical_context={
            "history_summary": summary,
            "conversation_turns": [turn],
        },
    )

    assert [item.id for item in context_input.items] == [
        "system:duty",
        "history_summary:42",
        "conversation_turn:10:11",
    ]
    assert context_input.items[1].content == summary
    assert context_input.items[2].content == turn
    assert context_input.items[2].metadata == {"layout_order": 0}


def test_authorized_context_snapshot_ignores_unpaired_assistant_history():
    run_info = SimpleNamespace(
        history=[
            SimpleNamespace(role="assistant", content="Orphaned private output"),
            SimpleNamespace(role="user", content="Plan a trip"),
            SimpleNamespace(role="assistant", content="Where are you going?"),
        ],
        agent_config=SimpleNamespace(context_items=[]),
    )

    context_input = build_authorized_context_input(run_info)

    assert len(context_input.items) == 1
    assert context_input.items[0].content == {
        "user_message": "Plan a trip",
        "assistant_final_answer": "Where are you going?",
        "attachments": [],
        "user_message_id": -2,
        "assistant_message_id": -3,
    }
    assert "Orphaned private output" not in str(context_input.items)


def test_empty_inputs_do_not_emit_empty_resource_sections():
    items = build_context_inputs()

    assert [item.id for item in items] == [
        "system:header",
        "system:execution_flow",
        "system:manager_orchestration",
        "system:final_answer_guidance",
        "system:code_norms",
    ]
    assert all(item.type == ContextItemType.SYSTEM for item in items)


def test_ut_be_fps_012_backend_adapter_preserves_outline_and_priorities():
    """UT-BE-FPS-012: Backend data enters the SDK outline without reordering by priority."""
    items = build_context_inputs(
        language="en", duty="Investigate", constraint="Use approved sources",
        few_shots="Example response", tools={"search": Value()},
    )
    ordered = normalize_context_inputs(items)
    rendered = ContextItemRenderer().render(ordered)
    text = "\n".join(
        message["content"][0]["text"]
        for message in rendered if message["role"] == "system"
    )

    assert [line for line in text.splitlines() if line.startswith("## ")] == [
        "## Identity and Goals", "## Execution Protocol",
        "## Constraints and Environment", "## Examples", "## Available Resources",
    ]
    assert "### Tools" in text
    assert next(item.priority for item in items if item.id == "system:header") == 100
    assert next(item.priority for item in items if item.id == "system:code_norms") == 20
    assert next(item.priority for item in items if item.id == "system:available_resources_header") == 55


@pytest.mark.parametrize(
    ("language", "identity"),
    [
        (
            "zh",
            "你是 Nexent，Nexent 是一个开源智能体平台，基于 MCP 工具生态系统，提供灵活的多模态问答、检索、数据分析、处理等能力。",
        ),
        (
            "en",
            "You are Nexent. Nexent is an open-source agent platform built on the MCP tool ecosystem",
        ),
    ],
)
def test_app_identity_is_static(language, identity):
    header = next(
        item for item in build_context_inputs(language=language)
        if item.id == "system:header"
    )

    assert identity in header.content["text"]
    assert header.metadata["authority"] == "platform"


@pytest.mark.parametrize("language", ["en", "zh"])
def test_restricted_python_policy_follows_code_norms_in_display(language):
    items = build_context_inputs(
        restricted_python_authorized_imports=["json", "csv", "math", "json"],
        language=language,
    )

    policy_item = next(
        item for item in items if item.id == "system:restricted_python_execution"
    )
    policy_text = policy_item.content["text"]
    item_ids = [item.id for item in normalize_context_inputs(items)]

    assert policy_item.type == ContextItemType.SYSTEM
    assert policy_item.metadata["authority"] == "platform"
    assert policy_item.priority == 25
    assert "`csv`, `json`, `math`" in policy_text
    assert "`requests`" in policy_text
    assert item_ids.index("system:code_norms") < item_ids.index(policy_item.id)
    if language == "en":
        assert "### Python Code Execution Boundary" in policy_text


@pytest.mark.parametrize(
    ("language", "expected_text"),
    [
        ("zh", "一个引用标记只对应它前方最近的一句话"),
        ("en", "applies only to the nearest preceding sentence"),
    ],
)
def test_retrieval_citation_prompt_requires_sentence_level_marks(
    language, expected_text
):
    bundle = load_agent_prompt_bundle(is_manager=False, language=language)
    prompt = AgentPromptComposer(bundle).render_system_section("final_answer_guidance")

    assert expected_text in prompt
    assert "一个或多个引用标记" in prompt or "matching mark or marks" in prompt


def test_all_sources_are_naturally_granular_and_keep_stable_order():
    items = build_context_inputs(
        duty="duty",
        constraint="constraint",
        few_shots="example",
        tools={"one": Value(), "two": Value()},
        skills=[{"name": "skill-one", "description": "one"}, {"name": "skill-two", "description": "two"}],
        worker_agents={"worker": Value()},
        external_a2a_agents={"external-id": Value()},
        memory_list=[
            {"memory": "tenant fact", "memory_level": "tenant", "score": 1.0},
            {"memory": "user fact", "memory_level": "user", "score": 0.9},
        ],
        knowledge_base_summaries=[{"index_name": "kb-one", "display_name": "KB", "summary": "index summary"}],
        language="en",
    )

    ids = [item.id for item in items]
    assert ids.index("tool:one") < ids.index("tool:two")
    assert ids.index("skill:skill-one") < ids.index("skill:skill-two")
    assert {item.id for item in items if item.type == ContextItemType.MEMORY} == {"memory:0", "memory:1"}
    assert "worker_agent:worker" in ids
    assert "external_agent:external-id" in ids
    assert all("_source_component" not in item.metadata for item in items)


@pytest.mark.parametrize(
    ("language", "scope_marker", "resource_marker", "instruction_marker"),
    [
        ("zh", "平台提供的知识库范围内", "属于资源数据", "不是指令"),
        ("en", "scope provided by the platform", "resource data", "not instructions"),
    ],
)
def test_scoped_knowledge_summary_is_bounded_and_untrusted(
    language, scope_marker, resource_marker, instruction_marker
):
    items = build_context_inputs(
        knowledge_base_summaries=[{"index_name": "selected-index", "display_name": "Selected KB", "summary": "untrusted summary"}],
        knowledge_scope={"local_capable": True, "aidp_capable": False, "local_disabled": False,
                         "aidp_disabled": False, "local_display_names": ["Selected KB"], "aidp_display_names": []},
        language=language,
    )

    summary_item = next(
        item for item in items if item.id == "knowledge_base:summary"
    )
    text = summary_item.content["text"]

    assert scope_marker in text
    assert resource_marker in text
    assert instruction_marker in text
    assert "untrusted summary" in text
    assert summary_item.metadata["authority"] == "retrieved"


def test_unscoped_knowledge_summary_keeps_legacy_routing_guidance():
    items = build_context_inputs(
        knowledge_base_summaries=[{"index_name": "default-index", "display_name": "Default KB", "summary": "summary"}],
        language="en",
    )

    summary_item = next(
        item for item in items if item.id == "knowledge_base:summary"
    )
    text = summary_item.content["text"]

    assert "please select the most relevant one or more" in text
    assert "resource data" not in text


@pytest.mark.parametrize(
    ("flag", "kwargs", "item_type"),
    [
        ("include_tools", {"tools": {"tool": Value()}}, ContextItemType.TOOL),
        ("include_skills", {"skills": [{"name": "skill", "description": "d"}]}, ContextItemType.SKILL),
        ("include_memory", {"memory_list": ["memory"]}, ContextItemType.MEMORY),
        ("include_knowledge_base", {"knowledge_base_summaries": [{"index_name": "kb", "display_name": "KB", "summary": "kb"}]}, ContextItemType.KNOWLEDGE_BASE),
        ("include_worker_agents", {"worker_agents": {"worker": Value()}}, ContextItemType.WORKER_AGENT),
        ("include_external_agents", {"external_a2a_agents": {"id": Value()}}, ContextItemType.EXTERNAL_AGENT),
    ],
)
def test_inclusion_flags_remove_the_corresponding_item_type(flag, kwargs, item_type):
    items = build_context_inputs(**kwargs, **{flag: False})

    assert all(item.type != item_type for item in items)


def test_managed_agent_does_not_receive_sub_agent_definitions_or_manager_fallback():
    items = build_context_inputs(
        is_manager=False,
        worker_agents={"worker": Value()},
        external_a2a_agents={"id": Value()},
    )

    assert all(item.type not in {ContextItemType.WORKER_AGENT, ContextItemType.EXTERNAL_AGENT} for item in items)
    assert all(item.id != "system:agent_fallback" for item in items)


def test_invalid_memory_payload_fails_at_backend_boundary():
    with pytest.raises(ValueError, match="invalid memory payload at index 0"):
        build_context_inputs(memory_list=[object()])


def test_memory_tool_policy_is_a_required_system_item_rendered_verbatim():
    from nexent.core.prompts import load_prompt

    policy = load_prompt("en", "agent/memory_tool_policy")["policy"]
    items = build_context_inputs(enable_memory_tool_policy=True, language="en")
    policy_items = [item for item in items if item.id == "system:memory_tool_policy"]

    assert len(policy_items) == 1
    assert policy_items[0].type == ContextItemType.SYSTEM
    assert policy_items[0].content == {"text": policy}
    assert policy_items[0].metadata["authority"] == "platform"

    normalized = normalize_context_inputs(items)
    normalized_policy = next(item for item in normalized if item.id == "system:memory_tool_policy")
    assert normalized_policy.required is True

    messages = ContextItemRenderer().render(normalized)
    rendered_text = "\n".join(
        block["text"]
        for message in messages
        for block in message.get("content", ())
        if block.get("type") == "text"
    )
    assert policy in rendered_text
    assert rendered_text.count(policy) == 1


def test_memory_tool_policy_is_omitted_when_empty():
    items = build_context_inputs(enable_memory_tool_policy=False)

    assert all(item.id != "system:memory_tool_policy" for item in items)


def test_automation_tool_policy_is_required_platform_context():
    from nexent.core.prompts import load_prompt

    policy = load_prompt("en", "agent/automation_tool_policy")["policy"]
    items = build_context_inputs(enable_automation_tool_policy=True, language="en")
    policy_item = next(item for item in items if item.id == "system:automation_tool_policy")

    assert policy_item.type == ContextItemType.SYSTEM
    assert policy_item.content == {"text": policy}
    assert policy_item.metadata["authority"] == "platform"
    normalized = normalize_context_inputs(items)
    assert next(
        item for item in normalized if item.id == "system:automation_tool_policy"
    ).required is True


def test_long_term_memory_documents_are_structured_memory_items():
    items = build_context_inputs(
        long_term_memory_items=[{
            "memory": "## Policy\n\n- Follow company policy", "scope": "tenant",
            "memory_level": "tenant", "version_id": 7, "source": "manual",
        }],
        language="en",
    )
    memory_item = next(item for item in items if item.id == "memory:0")
    assert memory_item.type == ContextItemType.MEMORY
    assert memory_item.metadata["scope"] == "tenant"
    assert memory_item.metadata["version_id"] == 7
    assert memory_item.metadata["authority"] == "retrieved"


def test_long_term_memory_uses_dreaming_version_id_when_version_id_is_missing():
    items = build_context_inputs(
        long_term_memory_items=[{
            "memory": "Generated memory", "memory_level": "user",
            "dreaming_version_id": 13, "source": "dreaming",
        }],
    )

    memory_item = next(item for item in items if item.id == "memory:0")

    assert memory_item.metadata["version_id"] == 13
    assert memory_item.metadata["memory_type"] == "long_term"
    assert memory_item.metadata["scope"] == "user"
    assert memory_item.metadata["source"] == "dreaming"


def test_group_rendering_uses_only_selected_tool_items():
    items = normalize_context_inputs(build_context_inputs(
        tools={
            "selected": {"description": "keep", "inputs": {}, "output_type": "str"},
            "dropped": {"description": "must disappear", "inputs": {}, "output_type": "str"},
        },
        language="en",
    ))
    selected = [item for item in items if item.type != ContextItemType.TOOL or item.id == "tool:selected"]

    messages = ContextItemRenderer().render(selected)

    assert "selected" in str(messages)
    assert "must disappear" not in str(messages)


def test_rendered_roles_and_sections_match_context_semantics():
    messages = _messages(
        duty="duty",
        memory_list=[{"memory": "fact", "memory_level": "user", "score": 1.0}],
        knowledge_base_summaries=[{"index_name": "kb", "display_name": "KB", "summary": "kb"}],
        language="en",
    )

    assert messages[0]["role"] == "system"
    first_user = next(index for index, message in enumerate(messages) if message["role"] == "user")
    assert all(message["role"] == "system" for message in messages[:first_user])
    assert any(message["role"] == "system" and "Core Responsibilities" in str(message) for message in messages)
    assert any(message["role"] == "user" and "knowledge_base_search" in str(message) for message in messages)


def test_agent_presearch_result_is_rendered_into_model_context():
    result_text = "Found 2 relevant memories:\n[1] Likes fish\n[2] Dislikes fish"

    messages = _messages(
        memory_list=[{"memory": result_text, "memory_level": "agent"}],
        language="en",
    )
    rendered_text = "\n".join(
        block["text"]
        for message in messages
        for block in message.get("content", ())
        if block.get("type") == "text"
    )

    assert "**Agent Level Memory:**" not in rendered_text
    assert "Memory Usage Guidelines" not in rendered_text
    assert result_text in rendered_text
