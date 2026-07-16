"""Behavior snapshots for legacy and managed context assembly paths."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import StrictUndefined, Template

from backend.utils.context_utils import build_context_components
from backend.utils.prompt_template_utils import get_agent_prompt_template
from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.summary_config import ContextManagerConfig


SNAPSHOT_PATH = Path(__file__).with_name("prompt_equivalence_snapshot.json")


def _message_text(message):
    return "".join(part.get("text", "") for part in message["content"])


def _digest(text):
    return {"chars": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()}


def _case_inputs(language, rich):
    tool = SimpleNamespace(
        name="search",
        description="Search <docs> & data",
        inputs='{"q":"string"}',
        output_type="string",
        source="local",
    )
    builtin_tool = SimpleNamespace(
        name="run_skill_script",
        description="Run skill script",
        inputs='{"path":"string"}',
        output_type="string",
        source="local",
    )
    return {
        "duty": "Duty <&> 职责",
        "constraint": "Constraint\n第二行",
        "few_shots": "User: {x}\nAssistant: ✓",
        "app_name": "Nexent",
        "app_description": "Desc & <tag>",
        "user_id": "user-1",
        "language": language,
        "is_manager": rich,
        "tools": {"search": tool, "run_skill_script": builtin_tool} if rich else {},
        "skills": (
            [{"name": "analysis-skill", "description": "Analyze <input> & report"}]
            if rich
            else []
        ),
        "managed_agents": (
            {"analyst": SimpleNamespace(name="analyst", description="Internal analyst ✓")}
            if rich
            else {}
        ),
        "external_a2a_agents": (
            {
                "ext-1": SimpleNamespace(
                    agent_id="ext-1",
                    name="remote_helper",
                    description="External & safe",
                )
            }
            if rich
            else {}
        ),
        "memory_list": (
            [{"memory": "Prefers concise answers <3", "memory_level": "user", "score": 0.91}]
            if rich
            else []
        ),
        "memory_search_query": "special <query>",
        "knowledge_base_summary": "**KB**: facts & <evidence>" if rich else "",
        "kb_ids": ["kb-1"] if rich else [],
    }


def _legacy_prompt(values):
    template = get_agent_prompt_template(values["is_manager"], values["language"])["system_prompt"]
    return Template(template, undefined=StrictUndefined).render(
        duty=values["duty"],
        constraint=values["constraint"],
        few_shots=values["few_shots"],
        tools=values["tools"],
        skills=values["skills"],
        managed_agents=values["managed_agents"],
        external_a2a_agents=values["external_a2a_agents"],
        APP_NAME=values["app_name"],
        APP_DESCRIPTION=values["app_description"],
        memory_list=values["memory_list"],
        knowledge_base_summary=values["knowledge_base_summary"],
        user_id=values["user_id"],
    )


def _capture(values):
    legacy = _legacy_prompt(values)
    components = build_context_components(**values)
    messages = [message for component in components for message in component.to_messages()]
    return {
        "legacy": _digest(legacy),
        "managed": {
            "components": [component.component_type for component in components],
            "messages": [
                {"role": message["role"], **_digest(_message_text(message))}
                for message in messages
            ],
        },
    }


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("rich", [False, True], ids=["empty", "full"])
def test_legacy_and_managed_prompt_snapshots(language, rich):
    """Freeze both paths without incorrectly requiring their current outputs to be equal."""
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    case_name = f"{language}_{'full' if rich else 'empty'}"
    assert _capture(_case_inputs(language, rich)) == expected[case_name]


def test_full_snapshot_covers_required_context_sources():
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    for language in ("zh", "en"):
        snapshot = expected[f"{language}_full"]["managed"]
        assert {"tools", "skills", "memory", "knowledge_base"}.issubset(snapshot["components"])
        assert {"managed_agents", "external_a2a_agents"}.issubset(snapshot["components"])
        assert [message["role"] for message in snapshot["messages"]].count("user") == 2


@pytest.mark.parametrize("language", ["zh", "en"])
def test_final_managed_message_order_baseline(language):
    """Freeze ContextManager priority ordering, including dynamic evidence placement."""
    values = _case_inputs(language, rich=True)
    components = build_context_components(**values)
    manager = ContextManager(ContextManagerConfig(strategy="full"))
    manager.replace_components(components)

    messages = manager.build_context_messages()
    roles = [message["role"] for message in messages]
    texts = [_message_text(message) for message in messages]

    assert roles[0:2] == ["system", "user"]
    assert roles[-2:] == ["user", "system"]
    assert "Prefers concise answers <3" in texts[1]
    assert "**KB**: facts & <evidence>" in texts[-2]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_model_call_message_sequence_matches_managed_builder(language):
    """Freeze roles, order, text parts, and empty-history behavior at the model boundary."""
    values = _case_inputs(language, rich=True)
    components = build_context_components(**values)
    manager = ContextManager(ContextManagerConfig(enabled=False, strategy="full"))
    manager.replace_components(components)
    memory = SimpleNamespace(system_prompt=None, steps=[])

    run_context = manager.prepare_run_context(memory, fallback_system_prompt="fallback")
    final_context = manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        run_context=run_context,
    )

    expected_messages = [*run_context.stable_messages, *run_context.dynamic_messages]
    assert final_context.messages == expected_messages
    assert all(message["content"] for message in final_context.messages)
    assert all(part["type"] == "text" for message in final_context.messages for part in message["content"])


def test_none_and_empty_sources_do_not_emit_empty_messages():
    components = build_context_components(
        duty=None,
        constraint="",
        few_shots=None,
        app_name=None,
        app_description="",
        user_id=None,
        language="zh",
        is_manager=False,
        tools={},
        skills=[],
        memory_list=[],
        knowledge_base_summary="",
    )
    manager = ContextManager(ContextManagerConfig(strategy="full"))
    manager.replace_components(components)

    messages = manager.build_context_messages()

    assert messages
    assert all(_message_text(message) for message in messages)
