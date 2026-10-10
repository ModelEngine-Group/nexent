"""D1 contracts for SDK-owned static context prose."""

import pytest
from nexent.core.agents.context.formatting import (
    _format_external_agents_description,
    _format_tools_description,
    _format_worker_agents_description,
)
from nexent.core.prompts import load_prompt
from nexent.core.tools.prompt_registry import filter_effective_prompt_tools


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_014_context_sections_are_localized(language):
    sections = load_prompt(language, "agent/context_sections")
    assert sections["tools"]["heading"]
    assert sections["tools"]["file_url_guide_manager"]
    assert sections["tools"]["file_url_guide_worker"]
    assert sections["skills"]["intro"]
    assert "memory" not in sections
    assert "managed_agents" not in sections
    assert sections["worker_agents"]["guidance"]
    assert sections["external_agents"]["guidance"]
    if language == "zh":
        for name in ("worker_agents", "external_agents"):
            assert "子智能体" in str(sections[name])
            assert "助手" not in str(sections[name])
    assert {"run_skill_script", "read_skill_md", "download_from_s3", "upload_to_s3", "create_plan"} <= sections["builtin_tools"].keys()
    assert "{%" not in str(sections)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_018_builtin_descriptions_do_not_add_available_tools(language):
    sections = load_prompt(language, "agent/context_sections")
    assert sections["builtin_tools"]["run_skill_script"]
    registry = {
        "download_from_s3": {"description": sections["builtin_tools"]["download_from_s3"], "inputs": {}, "output_type": "string"},
        "run_skill_script": {"description": sections["builtin_tools"]["run_skill_script"], "inputs": {}, "output_type": "string"},
    }
    effective = filter_effective_prompt_tools(
        registry, enabled={"download_from_s3"}, allowed=set(registry),
        policy_version="1", tool_schema_version="1",
    )
    rendered = _format_tools_description(effective.tools, language=language)
    assert "download_from_s3" in rendered
    assert "run_skill_script" not in rendered
    assert set(effective.execution_tools) == {"download_from_s3"}


def test_ut_sdk_fps_018_worker_and_external_agents_share_subagent_term():
    worker = _format_worker_agents_description({"researcher": {"description": "检索资料"}}, "zh")
    external = _format_external_agents_description({"remote": {"name": "remote", "description": "总结资料"}}, "zh")
    assert "子智能体" in worker and "researcher: 检索资料" in worker
    assert "子智能体" in external
    assert "助手" not in worker + external


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_015_runtime_policies_are_localized(language):
    for path in ("agent/memory_tool_policy", "agent/automation_tool_policy", "agent/knowledge_scope"):
        assert load_prompt(language, path)


@pytest.mark.parametrize("language", ["zh", "en"])
def test_ut_sdk_fps_017_role_resources_do_not_restore_legacy_memory_guidance(language):
    for role in ("agent_manager", "agent_worker"):
        sections = load_prompt(language, f"agent/{role}")["system_sections"]
        assert "memory_guidance" not in sections
