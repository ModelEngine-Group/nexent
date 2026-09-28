"""D1 checks for the two-level Agent prompt outline."""

import re

import pytest

from nexent.core.agents.context import ContextItemRenderer, normalize_context_inputs
from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer
from nexent.core.prompts import load_prompt


def _composer(language: str, role: str) -> AgentPromptComposer:
    template = load_prompt(language, f"agent/agent_{role}")
    bundle = AgentPromptBundle.from_mapping(role=role, language=language, template=template)
    return AgentPromptComposer(bundle)


def _system_text(items) -> str:
    ordered = sorted(normalize_context_inputs(items), key=lambda item: item.layout_key)
    messages = ContextItemRenderer().render(ordered)
    return "\n".join(message["content"][0]["text"] for message in messages if message["role"] == "system")


@pytest.mark.parametrize("language,role", [(language, role) for language in ("zh", "en") for role in ("manager", "managed")])
def test_ut_sdk_fps_022_headings_and_optional_groups(language, role):
    """UT-SDK-FPS-022: only present modules emit H2/H3 headings in the agreed order."""
    composer = _composer(language, role)
    items = composer.compose_context_inputs(language=language, is_manager=role == "manager")
    text = _system_text(items)
    headings = re.findall(r"^#{1,4} .+$", text, flags=re.MULTILINE)
    assert headings
    assert all(heading.startswith(("## ", "### ")) for heading in headings)
    expected = (
        ["## 身份与目标", "## 执行协议", "## 约束与环境"]
        if language == "zh" else ["## Identity and Goals", "## Execution Protocol", "## Constraints and Environment"]
    )
    assert [heading for heading in headings if heading.startswith("## ")] == expected
    assert "## 可用资源" not in text and "## Available Resources" not in text
    assert "## 示例" not in text and "## Examples" not in text


def test_ut_sdk_fps_023_layout_order_preserves_priority():
    """UT-SDK-FPS-023: display order is independent from compaction priority."""
    composer = _composer("zh", "manager")
    items = composer.compose_context_inputs(
        language="zh", is_manager=True, duty="任务", constraint="限制", few_shots="示例",
        tools={"search": {"description": "检索"}},
        skills=[{"name": "writer", "description": "写作"}],
        worker_agents={"researcher": {"description": "研究"}},
        external_a2a_agents={"remote": {"name": "remote", "description": "远程"}},
        enable_planning=True, verification_enabled=True,
        restricted_python_authorized_imports=["json"],
    )
    by_id = {item.id: item for item in items}
    assert by_id["system:header"].priority == 100
    assert by_id["system:code_norms"].priority == 20
    assert by_id["system:available_resources_header"].priority == 55
    assert all("layout_order" in item.metadata for item in items if item.type.value == "system")
    ordered = normalize_context_inputs(items)
    ordered.sort(key=lambda item: item.layout_key)
    ids = [item.id for item in ordered]
    assert ids.index("system:constraint") < ids.index("system:code_norms")
    assert ids.index("system:footer") < ids.index("system:available_resources_header")
    assert ids.index("system:available_resources_header") < ids.index("tool:search")
    text = _system_text(items)
    headings = re.findall(r"^## .+$", text, flags=re.MULTILINE)
    assert headings == ["## 身份与目标", "## 执行协议", "## 约束与环境", "## 示例", "## 可用资源"]
    assert "### 工具" in text and "### 技能" in text
    assert "### 内部子智能体" in text and "### 外部子智能体" in text
    assert not re.search(r"^\d+\. (?:工具|技能|子智能体)", text, flags=re.MULTILINE)
    first = ordered[0]
    higher_priority = first.model_copy(update={"priority": first.priority + 100})
    assert first.layout_key == higher_priority.layout_key


def test_ut_sdk_fps_024_dynamic_context_headings_do_not_change_roles():
    """UT-SDK-FPS-024: retrieved material has titles but remains user data."""
    composer = _composer("en", "manager")
    items = composer.compose_context_inputs(
        language="en", is_manager=True, memory_list=["remembered fact"],
        knowledge_scope={"local_capable": True, "aidp_capable": False, "local_disabled": False,
                         "aidp_disabled": False, "local_display_names": ["Allowed index"], "aidp_display_names": []},
        knowledge_base_summaries=[{"index_name": "allowed", "display_name": "Allowed index", "summary": "Index summary"}],
    )
    messages = ContextItemRenderer().render(normalize_context_inputs(items))
    dynamic = [message["content"][0]["text"] for message in messages if message["role"] == "user"]
    assert any(text.startswith("## Retrieved Memory") and "remembered fact" in text for text in dynamic)
    assert any(text.startswith("## Available Knowledge Base Indexes") for text in dynamic)
    assert any(text.startswith("## Knowledge Base Summary") for text in dynamic)
