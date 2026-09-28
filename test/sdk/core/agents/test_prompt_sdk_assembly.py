"""D1 cases for SDK-owned main-Agent prompt assembly."""

import pytest

from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer
from nexent.core.prompts import load_prompt


@pytest.mark.parametrize(
    "language,role",
    [(language, role) for language in ("zh", "en") for role in ("manager", "managed")],
)
def test_ut_sdk_fps_025_role_resource_factory_and_override(language, role):
    """UT-SDK-FPS-025: SDK loads and validates the complete role resource."""
    resource = "agent/agent_manager" if role == "manager" else "agent/agent_worker"
    expected = load_prompt(language, resource)
    bundle = AgentPromptBundle.from_resource(role=role, language=language)
    assert bundle.template["system_sections"]["header"] == expected["system_sections"]["header"]
    assert AgentPromptBundle.from_resource(
        role=role, language=language, template_override=expected,
    ).digest == bundle.digest


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_026_tool_policies_follow_explicit_flags(language):
    """UT-SDK-FPS-026: SDK does not infer policy activation from tool names."""
    composer = AgentPromptComposer(AgentPromptBundle.from_resource(role="manager", language=language))
    disabled = composer.compose_context_inputs(language=language, tools={
        "store_memory": {"description": "available"},
        "create_scheduled_task_proposal": {"description": "available"},
    })
    assert not any(item.id.endswith("_tool_policy") for item in disabled)

    enabled = composer.compose_context_inputs(
        language=language, enable_memory_tool_policy=True, enable_automation_tool_policy=True,
    )
    by_id = {item.id: item for item in enabled}
    assert by_id["system:memory_tool_policy"].content["text"] == load_prompt(
        language, "agent/memory_tool_policy",
    )["policy"]
    assert by_id["system:automation_tool_policy"].content["text"] == load_prompt(
        language, "agent/automation_tool_policy",
    )["policy"]
    assert by_id["system:memory_tool_policy"].metadata["authority"] == "platform"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_027_structured_knowledge_scope_and_summaries(language):
    """UT-SDK-FPS-027: SDK renders only supplied authorized knowledge data."""
    composer = AgentPromptComposer(AgentPromptBundle.from_resource(role="manager", language=language))
    items = composer.compose_context_inputs(
        language=language,
        knowledge_scope={
            "local_capable": True, "aidp_capable": False,
            "local_disabled": False, "aidp_disabled": False,
            "local_display_names": ["Allowed KB"], "aidp_display_names": [],
        },
        knowledge_base_summaries=[{
            "index_name": "allowed-index", "display_name": "Allowed KB", "summary": "Facts",
        }],
    )
    by_id = {item.id: item for item in items}
    assert by_id["system:knowledge_scope_policy"].content["text"] == load_prompt(
        language, "agent/knowledge_scope",
    )["policy"]
    assert "Allowed KB" in by_id["knowledge_scope:resources"].content["text"]
    assert "Facts" in by_id["knowledge_base:summary"].content["text"]
    assert by_id["knowledge_scope:resources"].content["role"] == "user"
    assert by_id["knowledge_base:summary"].source == ("knowledge_base:allowed-index",)

    empty = composer.compose_context_inputs(language=language, knowledge_scope={
        "local_capable": False, "aidp_capable": False,
        "local_disabled": False, "aidp_disabled": False,
        "local_display_names": [], "aidp_display_names": [],
    })
    resource = next(item for item in empty if item.id == "knowledge_scope:resources")
    assert load_prompt(language, "agent/knowledge_scope")["resources"]["no_capability"] in resource.content["text"]

    both = composer.compose_context_inputs(language=language, knowledge_scope={
        "local_capable": True, "aidp_capable": True,
        "local_disabled": False, "aidp_disabled": False,
        "local_display_names": ["Local KB"], "aidp_display_names": ["AIDP KB"],
    })
    both_text = next(item for item in both if item.id == "knowledge_scope:resources").content["text"]
    labels = load_prompt(language, "agent/knowledge_scope")["resources"]
    assert labels["local_heading"] in both_text and labels["aidp_heading"] in both_text
    assert "1. Local KB" in both_text and "1. AIDP KB" in both_text

    no_indexes = composer.compose_context_inputs(language=language, knowledge_base_no_indexes=True)
    summary = next(item for item in no_indexes if item.id == "knowledge_base:summary")
    assert labels["no_indexes"] in summary.content["text"]
