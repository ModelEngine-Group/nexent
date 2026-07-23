"""Tests for authorized backend ContextItemInput snapshot construction."""

from dataclasses import dataclass

import pytest

from backend.utils.context_utils import build_app_context_string, build_context_inputs
from nexent.core.agents.context import ContextItemRenderer, ContextItemType
from nexent.core.agents.context.models import normalize_context_inputs


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


def _messages(**kwargs):
    return ContextItemRenderer().render(normalize_context_inputs(build_context_inputs(**kwargs)))


def test_empty_inputs_emit_only_required_skeleton_and_fallback_items():
    items = build_context_inputs()

    assert [item.id for item in items] == [
        "system:execution_flow",
        "system:available_resources_header",
        "system:agent_fallback",
        "system:skills_usage",
        "system:code_norms",
    ]
    assert all(item.type == ContextItemType.SYSTEM for item in items)


def test_all_sources_are_naturally_granular_and_keep_stable_order():
    items = build_context_inputs(
        duty="duty",
        constraint="constraint",
        few_shots="example",
        app_name="app",
        app_description="description",
        user_id="user",
        tools={"one": Value(), "two": Value()},
        skills=[{"name": "skill-one", "description": "one"}, {"name": "skill-two", "description": "two"}],
        managed_agents={"worker": Value()},
        external_a2a_agents={"external-id": Value()},
        memory_list=[
            {"memory": "tenant fact", "memory_level": "tenant", "score": 1.0},
            {"memory": "user fact", "memory_level": "user", "score": 0.9},
        ],
        knowledge_base_summary="index summary",
        kb_ids=["kb-one"],
        language="en",
    )

    ids = [item.id for item in items]
    assert ids.index("tool:one") < ids.index("tool:two")
    assert ids.index("skill:skill-one") < ids.index("skill:skill-two")
    assert {item.id for item in items if item.type == ContextItemType.MEMORY} == {"memory:0", "memory:1"}
    assert "managed_agent:worker" in ids
    assert "external_agent:external-id" in ids
    assert all("_source_component" not in item.metadata for item in items)


@pytest.mark.parametrize(
    ("flag", "kwargs", "item_type"),
    [
        ("include_tools", {"tools": {"tool": Value()}}, ContextItemType.TOOL),
        ("include_skills", {"skills": [{"name": "skill", "description": "d"}]}, ContextItemType.SKILL),
        ("include_memory", {"memory_list": ["memory"]}, ContextItemType.MEMORY),
        ("include_knowledge_base", {"knowledge_base_summary": "kb"}, ContextItemType.KNOWLEDGE_BASE),
        ("include_managed_agents", {"managed_agents": {"worker": Value()}}, ContextItemType.MANAGED_AGENT),
        ("include_external_agents", {"external_a2a_agents": {"id": Value()}}, ContextItemType.EXTERNAL_AGENT),
    ],
)
def test_inclusion_flags_remove_the_corresponding_item_type(flag, kwargs, item_type):
    items = build_context_inputs(**kwargs, **{flag: False})

    assert all(item.type != item_type for item in items)


def test_managed_agent_does_not_receive_sub_agent_definitions_or_manager_fallback():
    items = build_context_inputs(
        is_manager=False,
        managed_agents={"worker": Value()},
        external_a2a_agents={"id": Value()},
    )

    assert all(item.type not in {ContextItemType.MANAGED_AGENT, ContextItemType.EXTERNAL_AGENT} for item in items)
    assert all(item.id != "system:agent_fallback" for item in items)


def test_invalid_memory_payload_fails_at_backend_boundary():
    with pytest.raises(ValueError, match="invalid memory payload at index 0"):
        build_context_inputs(memory_list=[object()])


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
        knowledge_base_summary="kb",
        language="en",
    )

    assert messages[0]["role"] == "system"
    first_user = next(index for index, message in enumerate(messages) if message["role"] == "user")
    assert all(message["role"] == "system" for message in messages[:first_user])
    assert any(message["role"] == "system" and "Core Responsibilities" in str(message) for message in messages)
    assert any(message["role"] == "user" and "knowledge_base_search" in str(message) for message in messages)


def test_app_context_compatibility_string_is_unchanged():
    assert build_app_context_string("App", "Description", "user") == (
        "Application: App\nDescription: Description\nCurrent user: user"
    )
