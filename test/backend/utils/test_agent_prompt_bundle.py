"""D1 contracts for Management-owned Agent prompt templates."""

from pathlib import Path

import pytest
from nexent.core.agents.prompt import AgentPromptComposer
from nexent.core.prompts import load_prompt

from backend.management.services.agent.prompt_template_loader import (
    load_agent_prompt_bundle,
)
from backend.utils.context_utils import build_context_inputs


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("is_manager", [False, True])
def test_ut_be_dpr_001_system_sections_keep_existing_context_metadata(language, is_manager):
    """UT-BE-DPR-001: fixed YAML sections retain context item identity and order."""
    bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    items = build_context_inputs(
        language=language,
        is_manager=is_manager,
        duty="configured duty",
        prompt_bundle=bundle,
    )

    ids = [item.id for item in items]
    assert ids[0] == "system:header"
    assert "system:duty" in ids
    assert "system:execution_flow" in ids
    assert "system:code_norms" in ids
    assert ids.index("system:header") < ids.index("system:duty") < ids.index("system:code_norms")
    assert next(item for item in items if item.id == "system:header").priority == 100
    assert next(item for item in items if item.id == "system:header").metadata["authority"] == "platform"
    assert next(item for item in items if item.id == "system:header").source == ("agent_prompt:header",)
    assert "configured duty" in next(item for item in items if item.id == "system:duty").content["text"]
    assert bundle.system_sections["header"]


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("is_manager", [False, True])
def test_ut_be_dpr_001_fixed_sections_are_complete_and_localized(language, is_manager):
    """UT-BE-DPR-001: policy prose is loaded from one localized YAML bundle."""
    bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    composer = AgentPromptComposer(bundle)
    execution = composer.render_system_section("execution_flow")
    format_override = (
        "用户明确指定响应格式时，应严格按该格式回答；不擅自增加用户未要求的标题、段落或字段。\n"
        if language == "zh" else
        "Follow the user's requested response format strictly; do not add headings, paragraphs, or fields the user did not request.\n"
    )
    assert format_override in composer.render_system_section("final_answer_guidance")
    assert composer.render_system_section("sandbox_workspace_guidance")
    assert composer.render_system_section("self_verification_guidance")
    assert composer.render_system_section("skill_usage")
    code_norms = composer.render_system_section("code_norms")
    if language == "zh":
        assert "在权限和可用工具范围内完成任务" in code_norms
        assert "避免在Markdown中使用HTML标签" not in execution
    else:
        assert "within current permissions and available tools" in code_norms
        assert "Avoid HTML tags" not in execution


@pytest.mark.parametrize("bad_template", [{}, {"system_sections": {"header": "{{unknown}}"}}])
def test_ut_be_dpr_002_bad_template_fails_without_disclosing_content(bad_template):
    """UT-BE-DPR-002: malformed template content must fail at the loading boundary."""
    with pytest.raises(ValueError) as error:
        load_agent_prompt_bundle(is_manager=False, language="en", template_override=bad_template)

    assert "prompt" in str(error.value).lower() or "template" in str(error.value).lower()
    assert "{{unknown}}" not in str(error.value)


def test_ut_be_dpr_002_unsupported_language_fails_before_template_read():
    """UT-BE-DPR-002: unsupported locales cannot silently fall back."""
    with pytest.raises(ValueError, match="language"):
        load_agent_prompt_bundle(is_manager=False, language="fr")


def test_ut_be_dpr_002_unknown_variable_in_complete_template_is_rejected():
    """UT-BE-DPR-002: variable validation runs after structural validation."""
    template = load_prompt("en", "agent/agent_worker")
    template["system_sections"]["header"] = "{{private_unknown_variable}}"
    with pytest.raises(ValueError, match="system_sections.header") as error:
        load_agent_prompt_bundle(is_manager=False, language="en", template_override=template)
    assert "private_unknown_variable" not in str(error.value)


def test_ut_be_dpr_002_known_variable_in_wrong_section_is_rejected():
    """UT-BE-DPR-002: a placeholder valid elsewhere cannot enter the header."""
    template = load_prompt("en", "agent/agent_worker")
    template["system_sections"]["header"] = "{{duty}}"
    with pytest.raises(ValueError, match="system_sections.header"):
        load_agent_prompt_bundle(is_manager=False, language="en", template_override=template)


def test_ut_be_dpr_003_manager_orchestration_only_for_available_agents():
    """UT-BE-DPR-003: manager instructions cannot expose unavailable delegates."""
    manager = load_agent_prompt_bundle(is_manager=True, language="en")
    leaf = load_agent_prompt_bundle(is_manager=False, language="en")
    manager_items = build_context_inputs(
        is_manager=True,
        language="en",
        worker_agents={"worker": {"description": "available"}},
        prompt_bundle=manager,
    )
    leaf_items = build_context_inputs(is_manager=False, language="en", prompt_bundle=leaf)
    unavailable_items = build_context_inputs(
        is_manager=False, language="en",
        worker_agents={"unavailable": {"description": "not authorized"}},
        prompt_bundle=leaf,
    )

    manager_text = str(manager_items)
    leaf_text = str(leaf_items)
    assert "manager_agent" in manager.template
    assert "user's requested format" in manager_text.lower()
    assert "worker" in manager_text
    assert "worker_agent:unavailable" not in manager_text
    assert "manager_agent" not in leaf.template
    assert "delegate" not in leaf_text.lower()
    assert "worker_agent:unavailable" not in str(unavailable_items)


def test_ut_be_dpr_004_bundle_versions_and_fields_are_isolated():
    """UT-BE-DPR-004: template snapshots cannot share mutable role or locale state."""
    first = load_agent_prompt_bundle(is_manager=True, language="zh")
    second = load_agent_prompt_bundle(is_manager=False, language="en")

    assert first.role == "manager"
    assert second.role == "managed"
    assert first.language == "zh"
    assert second.language == "en"
    assert first.digest != second.digest
    for bundle in (first, second):
        assert "planning" not in bundle.template
        assert "verification" not in bundle.template
        assert "final_answer" in bundle.template
    template_dir = Path(__file__).parents[3] / "sdk" / "nexent" / "core" / "prompts"
    assert len(list(template_dir.glob("*/agent/agent_manager.yaml"))) == 2
    assert len(list(template_dir.glob("*/agent/agent_worker.yaml"))) == 2


def test_ut_be_cftp_002_production_prompts_use_only_the_final_tag_contract():
    """UT-BE-cftp-002: model-facing completion prompts contain no final-answer tool call."""
    template_dir = Path(__file__).parents[3] / "sdk" / "nexent" / "core" / "prompts"
    prompt_paths = [
        *template_dir.glob("*/agent/agent_manager.yaml"),
        *template_dir.glob("*/agent/agent_worker.yaml"),
        *template_dir.glob("*/meta/nl2agent.yaml"),
        *template_dir.glob("*/meta/nl2skill_*.yaml"),
        *template_dir.glob("*/meta/generate_prompt.yaml"),
    ]

    assert prompt_paths
    for path in prompt_paths:
        content = path.read_text(encoding="utf-8")
        assert "<final_answer>" in content, path
        assert "<final>" not in content, path
        assert "</final>" not in content, path
        assert "final_answer(" not in content, path


def test_ut_be_dpr_004_orphan_yaml_field_is_rejected():
    """UT-BE-DPR-004: the loader keeps only fields with active consumers."""
    template = load_prompt("en", "agent/agent_worker")
    template["verification"] = {"pre_messages": "unused"}
    with pytest.raises(ValueError, match="root fields"):
        load_agent_prompt_bundle(is_manager=False, language="en", template_override=template)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_be_dpr_006_skill_guidance_is_absent_without_skills(language):
    """UT-BE-DPR-006: workspace guidance cannot advertise unavailable skill tools."""
    bundle = load_agent_prompt_bundle(is_manager=False, language=language)
    without_skills = build_context_inputs(
        is_manager=False,
        language=language,
        sandbox_workspace_enabled=True,
        skills=[],
        prompt_bundle=bundle,
    )
    with_skills = build_context_inputs(
        is_manager=False,
        language=language,
        sandbox_workspace_enabled=True,
        skills=[{"name": "analysis", "description": "Analyze data"}],
        prompt_bundle=bundle,
    )

    without_text = str(without_skills)
    with_text = str(with_skills)
    for tool_name in ("run_skill_script", "read_skill_md", "read_skill_config"):
        assert tool_name not in without_text
        assert tool_name in with_text
    assert "write_skill_file" not in without_text
    assert "write_skill_file" not in with_text


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("is_manager", [False, True])
def test_ut_be_dpr_008_templates_expose_dynamic_policy_sections(language, is_manager):
    """UT-BE-DPR-008: all role-language templates expose the same policy gates."""
    bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    sections = bundle.system_sections

    assert "sandbox_workspace_guidance" in sections
    assert "self_verification_guidance" in sections
    assert "workspace_guidance" not in sections
    assert "Self-verification" not in sections["execution_flow"]
    assert "自验证" not in sections["execution_flow"]
    assert "Behavioral Safety" not in sections["duty"]
    assert "行为安全" not in sections["duty"]


def test_ut_be_dpr_007_backend_uses_canonical_sandbox_configuration():
    """UT-BE-DPR-007: prompt assembly consumes the const-owned sandbox level."""
    source = (
        Path(__file__).parents[3] / "backend" / "agents" / "create_agent_info.py"
    ).read_text(encoding="utf-8")

    assert 'os.getenv("NEXENT_SANDBOX_DEFAULT_LEVEL"' not in source
    assert "NEXENT_SANDBOX_DEFAULT_LEVEL," in source
    assert "sandbox_workspace_enabled=not is_local_python_executor" in source
    assert "verification_enabled=verification_config.enabled" in source


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_be_dpr_007_actual_bundle_gates_optional_sections(language):
    """UT-BE-DPR-007: actual YAML sections follow local and sandbox run facts."""
    from nexent.core.agents.context.rendering import ContextItemRenderer

    bundle = load_agent_prompt_bundle(is_manager=False, language=language)
    local = build_context_inputs(
        is_manager=False,
        language=language,
        restricted_python_authorized_imports=["json"],
        prompt_bundle=bundle,
    )
    sandbox = build_context_inputs(
        is_manager=False,
        language=language,
        enable_planning=True,
        verification_enabled=True,
        sandbox_workspace_enabled=True,
        restricted_python_authorized_imports=["json"],
        skills=[{"name": "writer", "description": "Write documents"}],
        prompt_bundle=bundle,
    )

    local_ids = {item.id for item in local}
    sandbox_ids = {item.id for item in sandbox}
    sandbox_text = "\n".join(
        message["content"][0]["text"]
        for message in ContextItemRenderer().render(sandbox)
    )
    assert "system:restricted_python_execution" in local_ids
    assert "system:sandbox_workspace_guidance" not in local_ids
    assert "system:sandbox_workspace_guidance" in sandbox_ids
    assert "system:restricted_python_execution" not in sandbox_ids
    assert "create_plan" in sandbox_text
    assert "Verification feedback" in sandbox_text
    assert "read_skill_md" in sandbox_text


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_be_dpr_008_common_role_sections_are_synchronized(language):
    """UT-BE-DPR-008: role variants share all role-neutral prompt sections."""
    manager = load_agent_prompt_bundle(is_manager=True, language=language)
    managed = load_agent_prompt_bundle(is_manager=False, language=language)
    role_neutral_sections = {
        "header",
        "planning_guidance",
        "sandbox_workspace_guidance",
        "skill_usage",
        "duty",
        "constraint",
        "footer",
        "knowledge_guidance_scoped",
        "knowledge_guidance_unscoped",
    }

    for section in role_neutral_sections:
        assert manager.system_sections[section] == managed.system_sections[section]

    assert "human_interaction" not in manager.template
    assert "human_interaction" not in managed.template


def test_ut_be_dpr_008_english_templates_follow_latest_manager_zh_policies():
    """UT-BE-DPR-008: English templates carry the latest shared policy semantics."""
    for is_manager in (True, False):
        bundle = load_agent_prompt_bundle(is_manager=is_manager, language="en")
        restricted_python = bundle.system_sections["restricted_python_execution"]
        assert "This policy takes precedence over general instructions" not in restricted_python
        assert "When a capability is unavailable" in restricted_python

    clarification = load_prompt("en", "agent/human_interaction")["clarification_policy"]
    assert "human-in-the-loop capability" in clarification
    assert "critical points" in clarification
    assert "small number of essential core questions" in clarification
    assert "Normally ask up to 3" not in clarification


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("is_manager", [False, True])
def test_ut_be_dpr_008_final_stage_and_verifier_keep_their_runtime_contract(
    language,
    is_manager,
):
    """UT-BE-DPR-008: max-step task anchoring and SDK verification remain active."""
    bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    post_message = bundle.template["final_answer"]["post_messages"]

    assert "{{task}}" in post_message
    assert "清晰、简洁的总结" not in post_message
    assert "clear and concise summary" not in post_message
    assert "verification" not in bundle.template

    verification_source = (
        Path(__file__).parents[3]
        / "sdk" / "nexent" / "core" / "agents" / "verification.py"
    ).read_text(encoding="utf-8")
    assert "def _build_verifier_messages(" in verification_source
    assert 'load_prompt("en", "agent/answer_verifier")' in verification_source
    assert "Return JSON only with keys: passed, score, status" not in verification_source
    assert "def verify_final_answer(" in verification_source


def test_ut_be_dpr_009_management_loader_is_a_thin_template_provider():
    """UT-BE-DPR-009: Management delegates the prompt contract to the SDK."""
    loader_source = (
        Path(__file__).parents[3]
        / "backend" / "management" / "services" / "agent"
        / "prompt_template_loader.py"
    ).read_text(encoding="utf-8")

    assert "_REQUIRED_SECTIONS" not in loader_source
    assert "_FIELD_VARIABLES" not in loader_source
    assert "jinja2" not in loader_source
    assert "AgentPromptBundle.from_resource" in loader_source


def test_ut_be_dpr_009_context_adapter_requires_an_explicit_bundle():
    """UT-BE-DPR-009: Backend cannot reload Management templates implicitly."""
    context_source = (
        Path(__file__).parents[3] / "backend" / "utils" / "context_utils.py"
    ).read_text(encoding="utf-8")

    assert "management.services.agent.prompt_template_loader" not in context_source
    with pytest.raises(TypeError, match="prompt_bundle"):
        build_context_inputs()


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("is_manager", [False, True])
def test_ut_be_dpr_012_agent_yaml_excludes_sdk_owned_hitl(language, is_manager):
    """UT-BE-DPR-012: Backend Agent YAML contains no SDK-owned HITL text."""
    template = load_prompt(language, "agent/agent_manager" if is_manager else "agent/agent_worker")

    assert "human_interaction" not in template
    bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    assert "human_interaction" not in bundle.template


def test_ut_be_dpr_012_obsolete_joint_optimizer_is_removed():
    """UT-BE-DPR-012: the unused experimental optimizer has no remaining files."""
    repository_root = Path(__file__).parents[3]
    tune_root = repository_root / "experimental" / "tune"

    assert not (tune_root / "joint_prompt_pool.yaml").exists()
    assert not (tune_root / "joint_optimizer.py").exists()
    for path in (repository_root / "experimental").rglob("*.py"):
        assert "joint_prompt_pool" not in path.read_text(encoding="utf-8")
