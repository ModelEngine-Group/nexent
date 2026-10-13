"""D1 contracts for Agent prompt composition and run-scoped resources."""

import re
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from test.common.source_files import iter_project_python_files
from nexent.core.agents.prompt import (
    AgentPromptBundle,
    AgentPromptComposer,
)
from nexent.core.tools.prompt_registry import (
    PromptToolPolicySnapshot,
    filter_effective_prompt_tools,
)


def _template(role: str = "managed") -> dict:
    module = "manager_agent" if role == "manager" else "managed_agent"
    stage = {"task": "{{task}}", "report": "{{final_answer}}"}
    if role == "manager":
        stage["orchestration"] = "Coordinate available workers."
    return {
            "system_sections": {
                "outline_identity": "## Identity and Goals",
                "outline_execution": "## Execution Protocol",
                "outline_constraints": "## Constraints and Environment",
                "header": "### Header\nAgent", "code_norms": "### Code rules",
                "execution_flow": "### Flow", "available_resources_header": "### Resources",
                "final_answer_guidance": "### Final Answer Requirements\nFinish the task.",
                "sandbox_workspace_guidance": "### Sandbox workspace\nUse /mnt/nexent/workdir/<run_id>/outputs.",
                "planning_guidance": "### Planning\nCall create_plan.",
                "self_verification_guidance": "### Self-verification\nUse Verification feedback.",
                "restricted_python_execution": "### Python Code Execution Boundary\nAllowed: {{authorized_imports}}.",
                "skill_usage": (
                    "### Skill Usage Requirements\n"
                    "Call read_skill_md(skill_name=\"skill-name\", additional_files=[]).\n"
                    "Call run_skill_script(skill_name=\"skill-name\", "
                    "script_path=\"scripts/example.py\", params=\"\", source=\"skill\")."
                ),
                "duty": "### Duty\n{{duty}}",
                "constraint": "### Constraints\n{{constraint}}",
                "footer": "### Examples\n{{few_shots}}",
                "knowledge_guidance_scoped": "Use only scoped knowledge.",
                "knowledge_guidance_unscoped": "Use available knowledge.",
            },
            module: stage,
            "final_answer": {
                "pre_messages": "Answer within the user's requested format.",
                "post_messages": "Task: {{task}}",
            },
        }


def _bundle(role: str = "managed", language: str = "en") -> AgentPromptBundle:
    return AgentPromptBundle.from_mapping(
        role=role,
        language=language,
        template=_template(role),
    )


@pytest.mark.parametrize("role", ["managed", "manager"])
def test_ut_sdk_dpr_008_sdk_owns_complete_template_validation(role):
    """UT-SDK-DPR-008: the SDK accepts each complete role contract."""
    bundle = AgentPromptBundle.from_mapping(
        role=role,
        language="en",
        template=_template(role),
    )

    assert bundle.role == role
    assert bundle.digest
    assert isinstance(bundle.template, MappingProxyType)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda template: template.update({"orphan": {}}), "root fields"),
        (lambda template: template["system_sections"].pop("header"), "system_sections"),
        (lambda template: template["managed_agent"].update({"orchestration": "bad"}), "managed_agent"),
        (lambda template: template["system_sections"].update({"header": "{{secret_value}}"}), "system_sections.header"),
        (lambda template: template["system_sections"].update({"header": "{{duty}}"}), "system_sections.header"),
    ],
)
def test_ut_sdk_dpr_008_sdk_rejects_invalid_contract_without_prompt_disclosure(
    mutate, field,
):
    """UT-SDK-DPR-008: invalid structure and placeholders fail in the SDK."""
    template = _template()
    mutate(template)

    with pytest.raises(ValueError, match=field) as error:
        AgentPromptBundle.from_mapping(
            role="managed",
            language="en",
            template=template,
        )

    assert "secret_value" not in str(error.value)
    assert "{{duty}}" not in str(error.value)


def test_ut_sdk_dpr_009_prompt_package_has_single_responsibility_modules():
    """UT-SDK-DPR-009: prompt implementation follows the public package layout."""
    agents_root = Path(__file__).parents[4] / "sdk" / "nexent" / "core" / "agents"
    prompt_root = agents_root / "prompt"
    sources = {
        name: (prompt_root / name).read_text(encoding="utf-8")
        for name in ("schema.py", "validator.py", "bundle.py", "composer.py")
    }

    from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer

    assert "REQUIRED_SYSTEM_SECTIONS" in sources["schema.py"]
    assert "jinja2" not in sources["schema.py"]
    assert "validate_agent_prompt_template" in sources["validator.py"]
    assert "class AgentPromptBundle" not in sources["validator.py"]
    assert "class AgentPromptBundle" in sources["bundle.py"]
    assert "ContextItem" not in sources["bundle.py"]
    assert "class AgentPromptComposer" in sources["composer.py"]
    assert "REQUIRED_SYSTEM_SECTIONS =" not in sources["composer.py"]

    assert not (agents_root / "context" / "prompt_composer.py").exists()
    repository_root = agents_root.parents[3]
    for source_root in (repository_root / "backend", repository_root / "sdk"):
        for path in iter_project_python_files(source_root):
            assert "context.prompt_composer" not in path.read_text(encoding="utf-8")
    assert AgentPromptComposer(AgentPromptBundle.from_mapping(
        role="managed", language="en", template=_template(),
    )).render_system_section("header") == "### Header\nAgent"


@pytest.mark.parametrize("role", ["managed", "manager"])
@pytest.mark.parametrize(
    ("task", "result"),
    [
        ("Reply in one line: report the result.", "Done."),
        ('Return JSON with only the key "answer".', '{"answer":"done"}'),
    ],
)
def test_ut_sdk_dpr_001_delegation_preserves_format_and_report(role, task, result):
    """UT-SDK-DPR-001: delegation must not add answer scaffolding."""
    composer = AgentPromptComposer(_bundle(role=role))

    delegated = composer.render_delegated_task(name="worker", task=task)
    returned = composer.render_delegated_report(result)

    assert delegated == task
    assert returned == result
    assert "one-line answer" not in delegated
    assert "summary_of_work" not in returned


def test_ut_sdk_dpr_001_delegated_report_keeps_agent_name_compatibility():
    """UT-SDK-DPR-001: legacy report templates may still render the agent name."""
    templates = _template()
    templates["managed_agent"]["report"] = "Report from {{name}}: {{final_answer}}"
    composer = AgentPromptComposer(AgentPromptBundle.from_mapping(
        role="managed",
        language="en",
        template=templates,
    ))

    assert composer.render_delegated_report("Done.", name="worker") == (
        "Report from worker: Done."
    )


@pytest.mark.parametrize("task", ["Reply in one line.", 'Return only {"answer":"..."}.'])
def test_ut_sdk_dpr_002_final_answer_has_neutral_messages(task):
    """UT-SDK-DPR-002: max-step instructions preserve the current task format."""
    composer = AgentPromptComposer(_bundle())

    templates = composer.compatibility_templates()
    final = templates["final_answer"]

    assert final["post_messages"] == "Task: {{task}}"
    assert task in composer.render_final_answer_post_message(task)
    assert "1. What has been accomplished" not in final["pre_messages"]
    assert "summary" not in final["pre_messages"].lower()
    assert templates["system_prompt"] == ""
    assert "planning" not in composer.bundle.template
    assert templates["planning"]["initial_plan"] == ""
    assert "verification" not in templates


@pytest.mark.parametrize("task", ["Reply in one line.", 'Return only {"answer":"..."}.'])
def test_ut_sdk_dpr_002_context_manager_renders_max_step_stage_without_scaffold(task):
    """UT-SDK-DPR-002: the final-answer stage keeps the user's format task."""
    from nexent.core.agents.context.manager import ContextManager

    templates = AgentPromptComposer(_bundle()).compatibility_templates()
    stable, dynamic = ContextManager()._purpose_messages(
        purpose="final_answer", task=task, final_answer_templates=templates,
    )
    assert stable[0]["content"][0]["text"] == "Answer within the user's requested format."
    assert task in dynamic[0]["content"][0]["text"]
    assert "summary" not in str(stable).lower()
    assert "1. What has been accomplished" not in str(stable)


def test_ut_sdk_dpr_003_bundle_is_immutable_and_context_only():
    """UT-SDK-DPR-003: a prompt bundle cannot leak mutable state across runs."""
    bundle = _bundle()
    composer = AgentPromptComposer(bundle)

    assert isinstance(bundle.system_sections, MappingProxyType)
    with pytest.raises(TypeError):
        bundle.system_sections["header"] = "changed"
    assert composer.render_system_section("header") == "### Header\nAgent"
    assert bundle.language == "en"
    assert bundle.role == "managed"


def test_ut_sdk_dpr_003_component_has_no_private_service_or_env_imports():
    """UT-SDK-DPR-003: prompt modules remain service-independent SDK code."""
    sdk_root = Path(__file__).parents[4] / "sdk" / "nexent" / "core"
    for path in (
        sdk_root / "agents" / "prompt" / "schema.py",
        sdk_root / "agents" / "prompt" / "validator.py",
        sdk_root / "agents" / "prompt" / "bundle.py",
        sdk_root / "agents" / "prompt" / "composer.py",
        sdk_root / "tools" / "prompt_registry.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"(?:from|import)\s+(?:backend|management|database)(?:\.|\s)", source)
        assert "os.getenv" not in source
        assert "os.environ" not in source


def test_ut_sdk_dpr_003_two_context_snapshots_do_not_share_resources():
    """UT-SDK-DPR-003: composer instances hold only their own run inputs."""
    first = AgentPromptComposer(_bundle(role="manager"))
    second = AgentPromptComposer(_bundle(role="managed"))
    first_items = first.compose_context_inputs(
        language="en", is_manager=True,
        tools={"weather": {"description": "forecast"}},
        worker_agents={"worker": {"description": "helper"}},
    )
    second_items = second.compose_context_inputs(
        language="en", is_manager=False,
        tools={"news": {"description": "headlines"}},
    )

    assert "tool:weather" in {item.id for item in first_items}
    assert "worker_agent:worker" in {item.id for item in first_items}
    worker_item = next(item for item in first_items if item.id == "worker_agent:worker")
    assert worker_item.metadata["render_group"] == "worker_agents"
    assert "tool:news" not in {item.id for item in first_items}
    assert "tool:news" in {item.id for item in second_items}
    assert "tool:weather" not in {item.id for item in second_items}
    assert "worker_agent:worker" not in {item.id for item in second_items}


def test_ut_sdk_dpr_001_nested_manager_call_uses_manager_role():
    """UT-SDK-DPR-001: a called manager retains its own task/report module."""
    from nexent.core.agents.core_agent import CoreAgent

    agent = CoreAgent.__new__(CoreAgent)
    agent.workspace_path = None
    agent.name = "nested"
    agent.state = {}
    agent.prompt_templates = AgentPromptComposer(_bundle(role="manager")).compatibility_templates()
    agent.run = MagicMock(return_value='{"answer":"done"}')
    agent.observer = MagicMock()
    with patch("nexent.core.agents.core_agent.RunResult", type("UnusedRunResult", (), {})):
        report = agent(task='Return JSON with only the key "answer".')

    assert agent.run.call_args.args[0] == 'Return JSON with only the key "answer".'
    assert report == '{"answer":"done"}'


def test_ut_sdk_dpr_004_effective_tools_and_audit_are_run_scoped():
    """UT-SDK-DPR-004: filtering and audit must describe exactly visible tools."""
    registry = {
        "weather": {"description": "forecast", "schema_version": "v1"},
        "news": {"description": "headlines", "schema_version": "v1"},
        "blocked": {"description": "forbidden", "schema_version": "v1"},
        "stale": {"description": "old", "schema_version": "v0"},
    }
    first = filter_effective_prompt_tools(
        registry,
        enabled={"weather", "blocked", "stale"},
        allowed={"weather", "news", "stale"},
        policy_version="p1",
        tool_schema_version="v1",
    )
    second = filter_effective_prompt_tools(
        registry,
        enabled={"news"},
        allowed={"news", "weather"},
        policy_version="p2",
        tool_schema_version="v1",
    )

    assert set(first.tools) == {"weather"}
    assert set(second.tools) == {"news"}
    assert first.audit["policy_version"] == "p1"
    assert second.audit["policy_version"] == "p2"
    assert first.audit["tool_schema_version"] == "v1"
    assert first.audit["visible_tools"] == ("weather",)
    assert second.audit["visible_tools"] == ("news",)
    assert first.audit["registry_hash"] != second.audit["registry_hash"]
    assert "blocked" not in str(first.tools)
    assert "stale" not in str(first.tools)


def test_ut_sdk_dpr_004_hidden_system_tool_executes_without_prompt_visibility():
    """UT-SDK-DPR-004: default hidden tools stay executable but invisible."""
    result = filter_effective_prompt_tools(
        {"visible": {"description": "shown"}, "hidden": {"description": "system"}},
        enabled={"visible"}, allowed={"visible"}, system_default_hidden={"hidden"},
        policy_version="p1", tool_schema_version="v1",
    )
    assert set(result.tools) == {"visible"}
    assert set(result.execution_tools) == {"visible", "hidden"}
    assert result.audit["visible_tools"] == ("visible",)


def test_ut_sdk_dpr_005_renders_runtime_specific_human_interaction_policy():
    """UT-SDK-DPR-005: HITL text comes from the localized SDK resource."""
    composer = AgentPromptComposer(_bundle(language="en"))

    native = composer.render_human_interaction(preserves_executor=True)
    durable = composer.render_human_interaction(preserves_executor=False)

    assert native.instructions.startswith("### Clarifying with the User")
    assert durable.instructions.endswith("Human approval never expands resource permissions.")
    assert native.questions_description.startswith("Include only 1-5 essential questions.")
    assert "ask_user" in native.instructions
    assert "single_choice" in native.instructions


def test_ut_be_dpr_005_sandbox_workspace_guidance_is_enabled_explicitly():
    """UT-BE-DPR-005: sandbox workspace rules are an explicitly gated system item."""
    composer = AgentPromptComposer(_bundle())

    disabled = composer.compose_context_inputs(language="en", is_manager=False)
    enabled = composer.compose_context_inputs(
        language="en", is_manager=False, sandbox_workspace_enabled=True,
    )

    assert "system:sandbox_workspace_guidance" not in {item.id for item in disabled}
    item = next(item for item in enabled if item.id == "system:sandbox_workspace_guidance")
    assert item.type.value == "system"
    assert item.content["text"] == "### Sandbox workspace\nUse /mnt/nexent/workdir/<run_id>/outputs."


@pytest.mark.parametrize(
    ("language", "expected_description", "unexpected_description"),
    [("zh", "中文说明", "English description"), ("en", "English description", "中文说明")],
)
def test_ut_sdk_dpr_006_localizes_tool_descriptions_and_schema(
    language, expected_description, unexpected_description,
):
    """UT-SDK-DPR-006: tool prose follows language while protocol names stay stable."""
    from nexent.core.agents.context.rendering import ContextItemRenderer

    composer = AgentPromptComposer(_bundle(language=language))
    items = composer.compose_context_inputs(
        language=language,
        is_manager=False,
        tools={
            "ask_user": {
                "description": "English description",
                "description_zh": "中文说明",
                "inputs": {
                    "mode": {
                        "type": "string",
                        "description": "English mode",
                        "description_zh": "中文模式",
                        "enum": ["single_choice"],
                    }
                },
                "output_type": "string",
            }
        },
    )
    rendered = "\n".join(
        message["content"][0]["text"] for message in ContextItemRenderer().render(items)
    )

    assert expected_description in rendered
    assert unexpected_description not in rendered
    assert "ask_user" in rendered
    assert "single_choice" in rendered


def test_ut_sdk_dpr_006_resources_have_headings_and_skills_not_duplicated():
    """UT-SDK-DPR-006: resource groups are present once with stable headings."""
    from nexent.core.agents.context.rendering import ContextItemRenderer

    composer = AgentPromptComposer(_bundle(language="en"))
    empty = composer.compose_context_inputs(language="en", is_manager=False)
    assert not any(
        item.id in {"system:available_resources_header", "system:agent_fallback", "system:skills_usage"}
        for item in empty
    )

    items = composer.compose_context_inputs(
        language="en",
        is_manager=False,
        tools={"reader": {"description": "Read data"}},
        skills=[{"name": "writer", "description": "Write documents"}],
    )
    rendered = "\n".join(
        message["content"][0]["text"] for message in ContextItemRenderer().render(items)
    )

    assert rendered.count("Skill Usage") == 1
    assert "### Tools" in rendered
    assert "### Skills" in rendered
    assert "1. Tools" not in rendered
    assert 'read_skill_md(skill_name="skill-name", additional_files=[])' in rendered
    assert 'run_skill_script(skill_name="skill-name", script_path="scripts/example.py", params="", source="skill")' in rendered


def test_ut_sdk_dpr_007_optional_prompt_sections_follow_run_facts():
    """UT-SDK-DPR-007: optional policies are injected only for enabled run facts."""
    from nexent.core.agents.context.rendering import ContextItemRenderer

    composer = AgentPromptComposer(_bundle(language="en"))
    local_items = composer.compose_context_inputs(
        language="en",
        is_manager=False,
        enable_planning=False,
        verification_enabled=False,
        sandbox_workspace_enabled=False,
        restricted_python_authorized_imports=["json"],
        skills=[],
    )
    sandbox_items = composer.compose_context_inputs(
        language="en",
        is_manager=False,
        enable_planning=True,
        verification_enabled=True,
        sandbox_workspace_enabled=True,
        restricted_python_authorized_imports=["json"],
        skills=[{"name": "writer", "description": "Write documents"}],
    )

    local_ids = {item.id for item in local_items}
    sandbox_ids = {item.id for item in sandbox_items}
    local_text = "\n".join(
        message["content"][0]["text"] for message in ContextItemRenderer().render(local_items)
    )
    sandbox_text = "\n".join(
        message["content"][0]["text"] for message in ContextItemRenderer().render(sandbox_items)
    )

    assert "system:restricted_python_execution" in local_ids
    assert "system:sandbox_workspace_guidance" not in local_ids
    assert "Planning" not in local_text
    assert "Self-verification" not in local_text
    assert "Skill Usage" not in local_text
    assert "system:sandbox_workspace_guidance" in sandbox_ids
    assert "system:restricted_python_execution" not in sandbox_ids
    assert sandbox_text.count("### Planning") == 1
    assert sandbox_text.count("### Self-verification") == 1
    assert sandbox_text.count("Skill Usage") == 1


@pytest.mark.parametrize(
    "values",
    [{"enabled": ["a"], "allowed": ["a"]},
     {"enabled": ["a"], "allowed": ["a"], "policy_version": "p1", "tool_schema_version": ""},
     {"enabled": "a", "allowed": ["a"], "policy_version": "p1", "tool_schema_version": "v1"}],
)
def test_ut_sdk_dpr_004_rejects_unversioned_or_invalid_policy(values):
    """UT-SDK-DPR-004: SDK never guesses a missing policy version."""
    with pytest.raises(ValueError, match="prompt tool policy"):
        PromptToolPolicySnapshot.from_mapping(values)



def test_scheduled_task_internal_tool_appears_only_in_policy():
    composer = AgentPromptComposer(_bundle())
    tools = {
        "create_scheduled_task_proposal": {"name": "create_scheduled_task_proposal", "description": "duplicate"},
        "search": {"name": "search", "description": "Search documents"},
    }
    items = composer.compose_context_inputs(
        language="en", is_manager=False, tools=tools, enable_automation_tool_policy=True,
    )
    ids = {item.id for item in items}
    assert "tool:create_scheduled_task_proposal" not in ids
    assert "tool:search" in ids
    assert "system:automation_tool_policy" in ids
    assert "create_scheduled_task_proposal" in tools
