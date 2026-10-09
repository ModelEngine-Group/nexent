"""User-message additions are rendered from matching SDK locale resources."""

import importlib
import importlib.util
from pathlib import Path
import sys
import types

import pytest


PROMPTS_ROOT = Path(__file__).resolve().parents[4] / "sdk/nexent/core/prompts"
ASSEMBLY_ROOT = PROMPTS_ROOT.parent / "agents/prompt"
PREFIX = "_user_context_test_package"
for name in (PREFIX, f"{PREFIX}.core", f"{PREFIX}.core.agents"):
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
spec = importlib.util.spec_from_file_location(
    f"{PREFIX}.core.prompts", PROMPTS_ROOT / "__init__.py",
    submodule_search_locations=[str(PROMPTS_ROOT)],
)
assert spec is not None and spec.loader is not None
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
assembly = types.ModuleType(f"{PREFIX}.core.agents.prompt")
assembly.__path__ = [str(ASSEMBLY_ROOT)]
sys.modules[assembly.__name__] = assembly
user_context = importlib.import_module(f"{assembly.__name__}.user_context")


@pytest.mark.parametrize("language,marker,workspace_label", [
    ("zh", "[当前时间:", "Run workspace"),
    ("en", "[Current time:", "Run workspace"),
])
def test_user_context_matches_page_language(language, marker, workspace_label):
    value = user_context.render_user_context(language, "current_time", {
        "time": "2026-09-28 12:30:00", "query": "question",
    })
    assert value.startswith("question\n\n" + marker)
    assert user_context.has_current_time_prefix(value)
    workspace = user_context.render_user_context(language, "workspace_note", {
        "workspace": "/run/1", "outputs": "/run/1/outputs",
    })
    assert workspace_label in workspace
    assert workspace == "\n\nRun workspace: /run/1"


def test_file_context_keeps_dynamic_values_and_separate_locales():
    values = {"name": "brief.pdf", "s3_url": "s3://bucket/brief.pdf", "presigned_url": "https://example.test/file"}
    zh = user_context.render_user_context("zh", "file_with_presigned_url", values)
    en = user_context.render_user_context("en", "file_with_presigned_url", values)
    assert "文件名" in zh and "File name" in en
    assert all(value in zh and value in en for value in values.values())


def test_missing_runtime_value_is_an_error():
    with pytest.raises(Exception):
        user_context.render_user_context("zh", "workspace_note", {})


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("role", ["agent_worker", "agent_manager"])
def test_workspace_instructions_are_owned_by_system_section(language, role):
    guidance = package.load_prompt(language, f"agent/{role}")["system_sections"]["sandbox_workspace_guidance"]
    assert "Run workspace:" in guidance
    assert "inputs" in guidance and "outputs" in guidance
    skills = package.load_prompt(language, f"agent/{role}")["system_sections"]["skill_usage"]
    assert 'run_skill_script(source="workspace")' in skills
    assert "outputs/<" in skills
    assert "sys.executable -m pip install" in guidance
    delegated = user_context.render_user_context(language, "delegated_workspace", {
        "task": "task", "workspace": "/run/1",
    })
    assert delegated == "task\n\nRun workspace: /run/1"


@pytest.mark.parametrize("language,marker", [("en", "Current time"), ("zh", "当前时间")])
def test_time_follows_request_and_precedes_workspace(language, marker):
    query = "question\n\nRun workspace: /run/1"
    result = user_context.render_user_context(language, "current_time", {"query": query, "time": "2026-10-09 09:00:00"})
    assert result == f"question\n\n[{marker}: 2026-10-09 09:00:00]\n\nRun workspace: /run/1"
    assert user_context.has_current_time_prefix(result)


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("role", ["agent_worker", "agent_manager"])
def test_updated_execution_and_code_rules(language, role):
    sections = package.load_prompt(language, f"agent/{role}")["system_sections"]
    norms = sections["code_norms"]
    flow = sections["execution_flow"]
    assert "<code>...</code>" in norms and "```python" in norms
    assert "<display" not in norms + flow
    assert "`print()`" in norms
    assert "simple Python" not in flow and "用简单的Python编写代码" not in flow
    assert "Multiple code blocks" not in norms and "多个代码块" not in norms
    assert "skill-creator" not in sections["sandbox_workspace_guidance"]
    policy = package.load_prompt(language, "agent/automation_tool_policy")["policy"]
    assert "`final_answer`" not in policy
    assert "<final_answer>...</final_answer>" in policy
    assert "<code>" in policy and "</code>" in policy
    assert "result = create_scheduled_task_proposal(request_text=" in policy
